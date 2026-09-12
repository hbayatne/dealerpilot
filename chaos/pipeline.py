"""
Ingestion pipeline — raw messages in, business memory out.

One pass over each message does four things, in this order, because each depends
on the last:

  1. classify direction (in / out / internal) against the org's own domains,
  2. resolve the people involved into entities (business memory),
  3. store the message on its reconstructed conversation,
  4. append to the event ledger.

Detection does **not** run here. Detectors read the stored, resolved corpus, so
they can reason across a whole thread rather than one message at a time — and so
they can be re-run and improved without re-fetching anyone's mailbox.

Everything is idempotent: re-ingesting the same mailbox produces no duplicates.
"""
from chaos import db, memory
from chaos.ingest import mailbox as M


def _recipients_of_bounced_subject(org_id, bounce_subject, bounce_at):
    """Who we last wrote to under the subject this bounce names.

    The fallback for servers that report a failure without quoting the address.
    Scoped to the fortnight before the bounce so an old thread with the same
    subject can't be blamed for it.
    """
    original = M.bounced_subject(bounce_subject)
    if not original:
        return []
    original = original.lower()
    import datetime
    try:
        floor = (datetime.datetime.fromisoformat(bounce_at)
                 - datetime.timedelta(days=14)).isoformat(timespec="seconds")
    except Exception:
        floor = ""
    with db._conn() as c:
        rows = c.execute(
            """SELECT to_addrs, subject FROM messages
               WHERE org_id=? AND direction='out' AND sent_at<=? AND sent_at>=?
               ORDER BY sent_at DESC LIMIT 50""",
            (org_id, bounce_at or "9999", floor)).fetchall()
    import json
    rows = [r for r in rows
            if M.normalize_subject(r["subject"] or "").lower() == original]
    for r in rows:
        try:
            addrs = json.loads(r["to_addrs"] or "[]")
        except Exception:
            continue
        for a in addrs:
            return [a]
    return []


def internals_of(org, addrs):
    return [a for a in (addrs or []) if memory.is_internal(org, a)]


def classify_direction(org, from_addr, to_addrs):
    """in = from the outside world, out = from us, internal = only us.

    Decided from the org's verified domains, not from folder names — folder
    layout varies per provider and per user, and 'Sent' lies often enough.
    """
    from_internal = memory.is_internal(org, from_addr)
    recipients = [a for a in (to_addrs or []) if a]
    to_internal = [a for a in recipients if memory.is_internal(org, a)]
    if from_internal and recipients and len(to_internal) == len(recipients):
        return "internal"
    if from_internal:
        return "out"
    return "in"


def infer_domains(raw_messages, mailbox_addr=None, limit=3):
    """Guess which email domains belong to the business.

    A messy business will not have told us. The mailbox owner's own domain is the
    strongest signal; otherwise we take the most frequent non-freemail domain
    among senders. The user confirms this in onboarding — we propose, they
    approve, which is the rule everywhere in this product.
    """
    counts = {}
    for m in raw_messages:
        for addr in [m.get("from_addr")] + [t["addr"] for t in (m.get("to") or [])]:
            dom = M.domain_of(addr)
            if dom and dom not in memory.FREEMAIL:
                counts[dom] = counts.get(dom, 0) + 1
    ranked = sorted(counts, key=lambda d: -counts[d])
    own = M.domain_of(mailbox_addr) if mailbox_addr else ""
    out = []
    if own:
        out.append(own)
    for d in ranked:
        if d not in out and len(out) < limit:
            out.append(d)
    return out


def ingest(org, raw_messages, source="email"):
    """Store a batch of parsed messages. Returns a summary of what changed."""
    org_id = org["id"]
    stats = {"seen": len(raw_messages or []), "stored": 0, "duplicates": 0,
             "people": 0, "conversations": 0, "automated": 0}
    touched_convs = set()

    for raw in sorted(raw_messages or [], key=lambda r: (M.parse_date(r.get("date")) or "")):
        from_addr = (raw.get("from_addr") or "").strip().lower()
        if not from_addr:
            continue
        to_list = [t["addr"] for t in (raw.get("to") or [])]
        cc_list = [t["addr"] for t in (raw.get("cc") or [])]
        recipients = to_list + cc_list
        sent_at = M.parse_date(raw.get("date"))
        direction = classify_direction(org, from_addr, recipients)
        headers = raw.get("headers") or {}
        bounce = M.bounce_reason(headers, from_addr, raw.get("subject"), raw.get("body"))
        ooo = None if bounce else M.out_of_office_reason(headers, raw.get("subject"))
        automated = bounce or ooo or M.classify_automation(headers, from_addr,
                                                           raw.get("subject"))
        auto_kind = "bounce" if bounce else ("out_of_office" if ooo else
                                             ("bulk" if automated else None))
        if automated:
            stats["automated"] += 1
            stats[auto_kind] = stats.get(auto_kind, 0) + 1

        # The outside party is the counterparty of the conversation; the internal
        # address is whoever on our side is handling it.
        externals = [a for a in ([from_addr] + recipients) if not memory.is_internal(org, a)]
        internals = [a for a in ([from_addr] + recipients) if memory.is_internal(org, a)]

        # A bounce is *about* someone other than its sender. Re-point it at the
        # contact whose address failed, so the conversation that matters learns
        # its message never arrived.
        if bounce:
            failed = M.failed_recipients(headers, raw.get("body"),
                                         exclude=[from_addr] + internals_of(org, recipients))
            if not failed:
                failed = _recipients_of_bounced_subject(org_id, raw.get("subject"), sent_at)
            for addr in failed:
                target = db.find_by_identity(org_id, "email", addr)
                if target:
                    db.add_event(org_id, "EMAIL_BOUNCED", occurred_at=sent_at,
                                 source=source, source_id=raw.get("source_id"),
                                 entity_id=target["id"], confidence=0.95,
                                 payload={"address": addr, "reason": bounce})
                    externals = [addr] + [a for a in externals if a != addr]
                    break

        counterparty = None
        if externals:
            nm = raw.get("from_name") if from_addr == externals[0] else None
            before = db.find_by_identity(org_id, "email", externals[0])
            counterparty = memory.resolve_person(
                org_id, externals[0], nm, seen_at=sent_at,
                role="automated" if automated else "contact", source=source,
                own_domains=org.get("domains"))
            if counterparty and not before:
                stats["people"] += 1

        actor = None
        if internals:
            actor_addr = from_addr if direction in ("out", "internal") else internals[0]
            actor = memory.resolve_person(org_id, actor_addr,
                                          raw.get("from_name") if from_addr == actor_addr
                                          else None,
                                          seen_at=sent_at, role="employee", source=source,
                                          own_domains=org.get("domains"))

        tkeys = M.thread_keys(raw.get("headers") or {}, raw.get("subject"),
                              externals or [from_addr])
        tkey = tkeys[0]
        cid = db.resolve_conversation(org_id, source, tkeys,
                                      subject=M.normalize_subject(raw.get("subject")),
                                      entity_id=counterparty["id"] if counterparty else None)
        touched_convs.add(cid)

        clean = M.clean_body(raw.get("body") or "")
        mid = db.add_message(
            org_id, conversation_id=cid, source=source,
            source_id=raw.get("source_id") or raw.get("message_id"),
            direction=direction, from_addr=from_addr,
            from_name=raw.get("from_name"), to_addrs=to_list, cc_addrs=cc_list,
            sent_at=sent_at,
            subject=raw.get("subject"), body=clean, snippet=M.snippet_of(clean),
            automated=automated, auto_kind=auto_kind,
            attachments=len(raw.get("attachments") or []),
            thread_key=tkey,
            entity_id=counterparty["id"] if counterparty else None,
            actor_entity_id=actor["id"] if actor else None)
        if mid is None:
            stats["duplicates"] += 1
            continue
        stats["stored"] += 1

        db.add_event(org_id,
                     "EMAIL_SENT" if direction == "out" else
                     ("EMAIL_INTERNAL" if direction == "internal" else "EMAIL_RECEIVED"),
                     occurred_at=sent_at, source=source,
                     source_id=raw.get("source_id"),
                     entity_id=counterparty["id"] if counterparty else None,
                     ref_kind="message", ref_id=mid,
                     confidence=1.0,
                     payload={"subject": raw.get("subject"), "automated": automated,
                              "auto_kind": auto_kind})

    for cid in touched_convs:
        db.refresh_conversation(org_id, cid)
    stats["conversations"] = len(touched_convs)
    return stats
