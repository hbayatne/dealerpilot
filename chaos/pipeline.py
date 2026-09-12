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
        automated = M.classify_automation(raw.get("headers") or {}, from_addr,
                                          raw.get("subject"))
        if automated:
            stats["automated"] += 1

        # The outside party is the counterparty of the conversation; the internal
        # address is whoever on our side is handling it.
        externals = [a for a in ([from_addr] + recipients) if not memory.is_internal(org, a)]
        internals = [a for a in ([from_addr] + recipients) if memory.is_internal(org, a)]

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
            from_name=raw.get("from_name"), to_addrs=recipients, sent_at=sent_at,
            subject=raw.get("subject"), body=clean, snippet=M.snippet_of(clean),
            automated=automated, attachments=len(raw.get("attachments") or []),
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
                     payload={"subject": raw.get("subject"), "automated": automated})

    for cid in touched_convs:
        db.refresh_conversation(org_id, cid)
    stats["conversations"] = len(touched_convs)
    return stats
