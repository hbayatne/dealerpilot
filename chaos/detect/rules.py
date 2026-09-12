"""
The finding rules — where stored business memory becomes "here is what you're
missing".

Each rule works on a *thread*, not a message, because that is the unit a human
judges. "Customer asked, nobody answered" only means something when you can see
the whole exchange, and that is exactly what a CRM cannot show you.

Shared exclusions live in `_eligible`. Every one of them exists because it
removed a class of false positive:

  * automated mail — newsletters and receipts are not neglected customers,
  * internal-only threads — colleagues are not clients,
  * threads that ended cleanly — "Perfect, thanks!" needs no reply,
  * contacts who asked us to stop — never recommend contacting them again,
  * anything still inside its response window — not yet a failure.
"""
import hashlib

from chaos import db, memory
from chaos.detect import base, commitments as commit_mod, signals as S

# Thresholds. Deliberately conservative: a finding that fires too early is a
# false accusation, and a business owner forgives a miss long before they
# forgive being told off for something they were about to do.
UNANSWERED_HOURS = 24          # business hours before silence is a problem
COMPLAINT_HOURS = 8            # an upset customer waits far less
STALE_OPP_DAYS = 7             # calendar days of total silence on a live deal
QUOTE_SILENT_DAYS = 5          # a quote nobody chased
MAX_AGE_DAYS = 120             # older than this is history, not a to-do


def _key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _thread_view(org_id, conv):
    msgs = db.messages_in(org_id, conv["id"])
    real = [m for m in msgs if not m.get("automated")]
    return {
        "conv": conv,
        "messages": msgs,
        "real": real,
        "inbound": [m for m in real if m["direction"] == "in"],
        "outbound": [m for m in real if m["direction"] == "out"],
        "bounces": [m for m in msgs if m.get("auto_kind") == "bounce"],
        "out_of_office": [m for m in msgs if m.get("auto_kind") == "out_of_office"],
    }


def _eligible(org, view, now_iso):
    """Why this thread can't produce a finding, or None when it can."""
    real = view["real"]
    if not real:
        return "no human messages"
    if not view["inbound"] and not view["outbound"]:
        return "internal only"
    last = real[-1]
    if base.days_between(last["sent_at"], now_iso) > MAX_AGE_DAYS:
        return "older than the review window"
    for m in view["inbound"]:
        if S.opted_out(m.get("body") or ""):
            return "contact asked not to be contacted"
    return None


def _replied_after(view, ts):
    """Any inbound after `ts`, counting auto-replies.

    An out-of-office is a reply. Saying "they never replied" when the mailbox
    answered to say they are away is a false statement, and one visibly false
    finding costs the credibility of the rest.
    """
    # `>=` on purpose: an auto-reply lands in the same second as the message it
    # answers often enough that a strict `>` silently misses it.
    return [m for m in view["messages"]
            if m["direction"] == "in" and (m["sent_at"] or "") >= (ts or "")
            and m.get("direction") == "in"]


# ---------------------------------------------------------------- rules
def _addressed_to_us(org, msg):
    """Was this message actually asking *us*, or were we just copied?

    Being CC'd on a conversation between other people carries no obligation to
    reply, and treating it as one fills the feed with other organizations'
    business. We only owe an answer when one of our addresses is in To.
    """
    to = msg.get("to_addrs") or []
    cc = msg.get("cc_addrs") or []
    if any(memory.is_internal(org, a) for a in to):
        return True
    # Nobody internal in To. If we're not in Cc either, the addressing is
    # unusual (BCC, a list, a forward) — assume it is ours rather than drop it.
    return not any(memory.is_internal(org, a) for a in cc)


def unanswered_inbound(org, view, now_iso):
    """A customer asked us something and nobody answered."""
    real = view["real"]
    last = real[-1]
    if last["direction"] != "in":
        return None
    if not _addressed_to_us(org, last):
        return None
    body = last.get("body") or ""
    if not S.asks_something(body):
        return None
    if S.looks_closed(body):
        return None

    waited = base.business_hours_between(last["sent_at"], now_iso)
    complaint = S.complaint(body)
    threshold = COMPLAINT_HOURS if complaint else UNANSWERED_HOURS
    if waited < threshold:
        return None

    # How many times have they written since we last said anything?
    last_out = view["outbound"][-1]["sent_at"] if view["outbound"] else None
    chasing = [m for m in view["inbound"]
               if not last_out or (m["sent_at"] or "") > last_out]
    nudges = len(chasing)

    intent = S.buying_intent(body) or (
        S.buying_intent(view["inbound"][0].get("body") or "") if view["inbound"] else None)
    value = None
    for m in real:
        value = value or S.deal_value(m.get("body") or "")

    conf = 0.62
    if nudges >= 2:
        conf += 0.18
    if waited > threshold * 3:
        conf += 0.08
    if intent:
        conf += 0.07
    if not view["outbound"]:
        conf += 0.05                 # we never replied at all
    conf = min(0.95, conf)

    severity = "high" if (nudges >= 2 or waited > 72) else "medium"
    if complaint and complaint["confidence"] >= 0.85:
        severity = "critical"

    ev = []
    for m in real[-6:]:
        ev.append(base.message_evidence(m))
    ev.append(base.evidence(
        now_iso, "No reply detected",
        f"No outbound email to this contact in the {base.humanize_hours(waited)} since "
        f"their last message."))

    who = view["conv"].get("subject") or "this conversation"
    name = _entity_name(org["id"], view["conv"].get("entity_id")) or last.get("from_addr")
    f, _ = base.finding(
        _key("unanswered", org["id"], view["conv"]["id"], last["id"]),
        "client_communication",
        f"{name} is waiting for a reply",
        subcategory="unanswered",
        summary=(f"{name} wrote {'again ' if nudges >= 2 else ''}about “{who}” and has "
                 f"had no response for {base.humanize_hours(waited)}."
                 + (f" They have written {nudges} times since our last reply."
                    if nudges >= 2 else "")),
        severity=severity, confidence=conf,
        urgency=min(1.0, 0.45 + waited / 200.0 + (0.2 if complaint else 0)),
        impact_cents=value["cents"] if value else None,
        impact_basis=value["basis"] if value else None,
        entity_id=view["conv"].get("entity_id"),
        owner=_last_owner(view),
        recommended_action=f"Reply to {name} today.",
        ai_actionable=True, approval_required=True, risk="low",
        detector="unanswered_inbound", detected_at=now_iso, evidence=ev)
    return f, ev


def overdue_commitment(org, view, now_iso):
    """We promised something by a date and no follow-through is detectable."""
    out = []
    for m in view["outbound"]:
        for c in commit_mod.extract(m.get("body") or "", m.get("sent_at")):
            if not c["due_at"] or c["due_at"] >= now_iso:
                continue
            # Anything we sent after the promise counts as possible follow-through.
            later = [x for x in view["outbound"]
                     if (x["sent_at"] or "") > (m["sent_at"] or "") and x["id"] != m["id"]]
            fulfilled_before_due = [x for x in later if (x["sent_at"] or "") <= c["due_at"]]
            if fulfilled_before_due:
                continue                       # looks handled — say nothing
            # We only see email. A promise to call, or to come by on Friday, is
            # kept in person — so silence in the mailbox is weak evidence. The
            # customer saying "perfect, thanks, all sorted" afterwards is much
            # stronger evidence the other way, and we defer to it.
            if _customer_closed_after(view, m["sent_at"]):
                continue
            overdue_by = base.days_between(c["due_at"], now_iso)
            # Due dates land at end-of-day, so a few hours past is genuinely past.
            if overdue_by < 0.25:
                continue

            conf = c["confidence"] * (0.9 if later else 1.0)
            if len(view["outbound"]) == 1:
                conf = min(0.95, conf + 0.05)
            value = S.deal_value(m.get("body") or "") or _thread_value(view)

            ev = [base.message_evidence(x) for x in view["real"]
                  if (x["sent_at"] or "") <= (m["sent_at"] or "")][-3:]
            ev.append(base.evidence(m["sent_at"], "Commitment made",
                                    f"“{c['quote']}”", "message", m["id"]))
            ev.append(base.evidence(
                c["due_at"], "Due",
                f"Interpreted from “{c['due_phrase']}” ({c['due_basis']})."))
            if later:
                ev.append(base.message_evidence(later[0], "Later contact (after the due date)"))
            else:
                ev.append(base.evidence(now_iso, "No follow-through detected",
                                        "No outbound email to this contact since the "
                                        "commitment was made."))

            name = _entity_name(org["id"], view["conv"].get("entity_id")) or "this contact"
            f, _ = base.finding(
                _key("commitment", org["id"], m["id"], c["quote"][:60]),
                "commitments",
                f"Possible unfulfilled commitment to {name}",
                subcategory="overdue",
                summary=(f"We said “{c['action']}” and the deadline passed "
                         f"{overdue_by:.0f} days ago with no matching follow-up."),
                severity="high" if overdue_by > 3 else "medium",
                confidence=round(conf, 3),
                urgency=min(1.0, 0.5 + overdue_by / 14.0),
                impact_cents=value["cents"] if value else None,
                impact_basis=value["basis"] if value else None,
                entity_id=view["conv"].get("entity_id"),
                owner=m.get("from_addr"),
                recommended_action=f"Close the loop with {name} on what was promised.",
                ai_actionable=True, approval_required=True, risk="low",
                detector="overdue_commitment", detected_at=now_iso, evidence=ev)
            out.append((f, ev))
    return out


def stale_opportunity(org, view, now_iso):
    """A live opportunity that everyone stopped talking about."""
    real = view["real"]
    intent = None
    for m in view["inbound"]:
        intent = S.buying_intent(m.get("body") or "") or intent
    if not intent or intent["confidence"] < 0.6:
        return None
    last = real[-1]
    if S.looks_closed(last.get("body") or ""):
        return None
    quiet = base.days_between(last["sent_at"], now_iso)
    if quiet < STALE_OPP_DAYS:
        return None
    if last["direction"] == "in":
        return None                    # that's an unanswered message, not a stale deal

    value = _thread_value(view)
    conf = 0.55 + min(0.2, quiet / 60.0) + (0.1 if intent["confidence"] >= 0.85 else 0)
    name = _entity_name(org["id"], view["conv"].get("entity_id")) or "this contact"
    ev = [base.message_evidence(m) for m in real[-4:]]
    ev.insert(0, base.evidence(None, "Buying signal",
                               f"{intent['kind'].capitalize()}: “{intent['quote']}”"))
    ev.append(base.evidence(now_iso, "Silence",
                            f"No activity either way for {quiet:.0f} days."))
    f, _ = base.finding(
        _key("stale", org["id"], view["conv"]["id"]),
        "revenue",
        f"Opportunity with {name} has gone quiet",
        subcategory="stale_opportunity",
        summary=(f"{name} {intent['kind']} and the conversation has been silent for "
                 f"{quiet:.0f} days."),
        severity="high" if quiet > 21 else "medium",
        confidence=round(min(0.9, conf), 3),
        urgency=min(0.75, 0.28 + quiet / 60.0),
        impact_cents=value["cents"] if value else None,
        impact_basis=value["basis"] if value else None,
        entity_id=view["conv"].get("entity_id"),
        owner=_last_owner(view),
        recommended_action=f"Re-engage {name} with a specific next step.",
        ai_actionable=True, approval_required=True, risk="low",
        detector="stale_opportunity", detected_at=now_iso, evidence=ev)
    return f, ev


def quote_without_followup(org, view, now_iso):
    """We sent a number and never chased it."""
    priced = None
    for m in view["outbound"]:
        v = S.deal_value(m.get("body") or "")
        if v:
            priced = (m, v)
    if not priced:
        return None
    msg, value = priced
    if _replied_after(view, msg["sent_at"]):
        return None          # they responded (an out-of-office counts) — not this finding
    after = [m for m in view["real"] if (m["sent_at"] or "") > (msg["sent_at"] or "")]
    if any(m["direction"] == "out" for m in after):
        return None                     # we did chase
    quiet = base.days_between(msg["sent_at"], now_iso)
    if quiet < QUOTE_SILENT_DAYS:
        return None

    name = _entity_name(org["id"], view["conv"].get("entity_id")) or "this contact"
    ev = [base.message_evidence(m) for m in view["real"][-4:]]
    ev.append(base.evidence(msg["sent_at"], "Amount quoted",
                            f"{base.money(value['cents'])} — “{value['context']}”",
                            "message", msg["id"]))
    ev.append(base.evidence(now_iso, "No response and no follow-up",
                            f"{quiet:.0f} days since the quote; no reply from the "
                            f"customer and no chase from us."))
    f, _ = base.finding(
        _key("quote", org["id"], msg["id"]),
        "revenue",
        f"{base.money(value['cents'])} quote to {name} was never followed up",
        subcategory="quote_no_followup",
        summary=(f"We quoted {base.money(value['cents'])} {quiet:.0f} days ago. "
                 f"{name} never replied and nobody followed up."),
        severity="high" if quiet > 14 else "medium",
        confidence=round(min(0.9, 0.6 + quiet / 60.0), 3),
        urgency=min(0.8, 0.3 + quiet / 60.0),
        impact_cents=value["cents"], impact_basis=value["basis"],
        entity_id=view["conv"].get("entity_id"),
        owner=msg.get("from_addr"),
        recommended_action=f"Follow up with {name} on the {base.money(value['cents'])} quote.",
        ai_actionable=True, approval_required=True, risk="low",
        detector="quote_without_followup", detected_at=now_iso, evidence=ev)
    return f, ev


def unresolved_complaint(org, view, now_iso):
    """An unhappy customer who has not been put right."""
    worst, worst_msg = None, None
    for m in view["inbound"]:
        c = S.complaint(m.get("body") or "")
        if c and (worst is None or c["confidence"] > worst["confidence"]):
            worst, worst_msg = c, m
    if not worst or worst["confidence"] < 0.7:
        return None
    after_out = [m for m in view["outbound"]
                 if (m["sent_at"] or "") > (worst_msg["sent_at"] or "")]
    later_in = [m for m in view["inbound"]
                if (m["sent_at"] or "") > (worst_msg["sent_at"] or "")]
    # Answered, and they didn't come back upset — treat it as handled.
    if after_out and not any(S.complaint(m.get("body") or "") for m in later_in):
        if view["real"][-1]["direction"] != "in":
            return None

    waited = base.business_hours_between(worst_msg["sent_at"], now_iso)
    name = _entity_name(org["id"], view["conv"].get("entity_id")) or worst_msg.get("from_addr")
    ev = [base.message_evidence(m) for m in view["real"][-5:]]
    ev.insert(0, base.evidence(worst_msg["sent_at"], f"Complaint signal — {worst['kind']}",
                               f"“{worst['quote']}”", "message", worst_msg["id"]))
    if not after_out:
        ev.append(base.evidence(now_iso, "No response",
                                "No outbound reply after the complaint."))
    f, _ = base.finding(
        _key("complaint", org["id"], worst_msg["id"]),
        "client_problems",
        f"{name} appears unhappy and unresolved",
        subcategory=worst["kind"].replace(" ", "_"),
        summary=(f"{name} — {worst['kind']} {base.humanize_hours(waited)} ago, "
                 f"and the thread has not been closed out."),
        severity="critical" if worst["confidence"] >= 0.9 else "high",
        confidence=round(min(0.92, worst["confidence"] * 0.95 +
                             (0.08 if not after_out else 0)), 3),
        # An escalating customer is the single most time-critical thing a
        # business faces: the window to save the relationship is measured in
        # hours, and it closes whether or not anyone noticed.
        urgency=min(1.0, 0.62 + worst["confidence"] * 0.3 + waited / 400.0),
        entity_id=view["conv"].get("entity_id"),
        owner=_last_owner(view),
        recommended_action=f"Have a manager contact {name} personally today.",
        ai_actionable=False, approval_required=True, risk="medium",
        detector="unresolved_complaint", detected_at=now_iso, evidence=ev)
    return f, ev


def undelivered_email(org, now_iso):
    """We think we contacted this customer. We didn't — the email bounced.

    This is the quietest way a business loses someone: the message sits in Sent,
    everybody assumes it landed, and the customer hears nothing. Nobody reads
    bounce notices.

    Driven off the event ledger rather than a single thread, because a bounce
    almost never threads with the message it is about — different subject, no
    References. The pipeline resolves which contact failed; this reads that.
    """
    out = []
    for ev in db.events(org["id"], kind="EMAIL_BOUNCED", limit=500):
        eid = ev.get("entity_id")
        if not eid:
            continue
        bounce_at = ev.get("occurred_at")
        sent = db.last_outbound_to(org["id"], eid, before=bounce_at)
        later = db.last_outbound_to(org["id"], eid, after=bounce_at)
        if sent is None or later:
            continue          # nothing failed, or somebody has since got through

        name = _entity_name(org["id"], eid) or (ev.get("payload") or {}).get("address") \
            or "this contact"
        reason = (ev.get("payload") or {}).get("reason") or "The mail server rejected it."
        ev_rows = [
            base.message_evidence(sent, "What we sent"),
            base.evidence(bounce_at, "Delivery failed", reason),
            base.evidence(now_iso, "Never re-sent",
                          "No later outbound email to this contact."),
        ]
        f, _ = base.finding(
            _key("bounce", org["id"], sent["id"]),
            "client_communication",
            f"Your email to {name} never arrived",
            subcategory="undeliverable",
            summary=(f"A message to {name} bounced and was never re-sent. As far as "
                     f"they know, you never replied."),
            severity="high", confidence=0.9, urgency=0.8,
            entity_id=eid, owner=sent.get("from_addr"),
            recommended_action=f"Check {name}'s address and reach them another way.",
            ai_actionable=False, approval_required=True, risk="low",
            detector="undelivered_email", detected_at=now_iso, evidence=ev_rows)
        out.append((f, ev_rows))
    return out


# ---------------------------------------------------------------- helpers
_NAME_CACHE = {}


def _entity_name(org_id, entity_id):
    if not entity_id:
        return None
    key = (org_id, entity_id)
    if key not in _NAME_CACHE:
        e = db.get_entity(org_id, entity_id)
        _NAME_CACHE[key] = e["display_name"] if e else None
    return _NAME_CACHE[key]


def _customer_closed_after(view, ts):
    """Did the customer signal satisfaction after this point?"""
    for x in view["inbound"]:
        if (x["sent_at"] or "") > (ts or "") and S.looks_closed(x.get("body") or ""):
            return True
    return False


def _last_owner(view):
    return view["outbound"][-1].get("from_addr") if view["outbound"] else None


def _thread_value(view):
    for m in reversed(view["real"]):
        v = S.deal_value(m.get("body") or "")
        if v:
            return v
    return None


THREAD_RULES = [unanswered_inbound, overdue_commitment, stale_opportunity,
                quote_without_followup, unresolved_complaint]

# Rules that need the whole org, not one thread.
ORG_RULES = [undelivered_email]

# When several rules fire on one thread they are describing one situation, not
# several. The owner should see "Pat Nguyen is upset and nobody has replied",
# not four rows about the same customer. Higher number wins the thread.
_PRIORITY = {
    "undelivered_email": 6,          # nothing else on the thread is true if this is
    "unresolved_complaint": 5,
    "overdue_commitment": 4,
    "unanswered_inbound": 3,
    "quote_without_followup": 2,
    "stale_opportunity": 1,
}


def _priority(f):
    """How well a finding describes the whole thread.

    A customer writing "just following up again" is a *symptom* of our silence,
    not a complaint about us. Leading with "they seem unhappy" when the real,
    fixable fact is "we promised an estimate on Thursday and never sent it"
    misplaces the blame and buries the action. So a complaint only outranks
    everything else when the customer actually escalated.
    """
    p = _PRIORITY.get(f.get("detector"), 0)
    if f.get("detector") == "unresolved_complaint" and \
            f.get("subcategory") in ("repeated_unanswered_contact", "dissatisfaction"):
        p = 2
    return p


def consolidate(results):
    """Collapse each thread's findings into the one that best describes it.

    The losers are not discarded — their evidence is folded into the survivor and
    named in its summary, so nothing detected is lost and the feed still has one
    row per real-world problem. This is the difference between a product that
    reduces chaos and one that adds to it.
    """
    by_thread = {}
    for f, ev in results:
        by_thread.setdefault(f.get("_conversation_id"), []).append((f, ev))

    out = []
    for cid, group in by_thread.items():
        if cid is None or len(group) == 1:
            out.extend(group)
            continue
        group.sort(key=lambda pair: (
            _priority(pair[0]),
            base.SEVERITY_RANK.get(pair[0]["severity"], 0),
            pair[0]["confidence"]), reverse=True)
        primary, primary_ev = group[0]
        extras = group[1:]

        # Severity and money take the worst/best of everything seen on the thread.
        for other, _ in extras:
            if base.SEVERITY_RANK.get(other["severity"], 0) > base.SEVERITY_RANK.get(
                    primary["severity"], 0):
                primary["severity"] = other["severity"]
            if primary.get("impact_cents") is None and other.get("impact_cents"):
                primary["impact_cents"] = other["impact_cents"]
                primary["impact_basis"] = other["impact_basis"]
            primary["urgency"] = max(primary["urgency"], other["urgency"])

        merged_ev = list(primary_ev)
        notes = []
        seen = {(e.get("label"), e.get("detail")) for e in merged_ev}
        for other, other_ev in extras:
            notes.append(_ALSO.get(other["detector"], other["detector"]))
            for e in other_ev:
                if (e.get("label"), e.get("detail")) not in seen and e.get("ref_kind") != "message":
                    merged_ev.append(e)
                    seen.add((e.get("label"), e.get("detail")))
        if notes:
            uniq = sorted(set(notes))
            primary["summary"] = (primary.get("summary") or "") + \
                " Also on this thread: " + "; ".join(uniq) + "."
        merged_ev.sort(key=lambda e: (e.get("occurred_at") or ""))
        out.append((primary, merged_ev))
    return out


_ALSO = {
    "undelivered_email": "an email to them bounced",
    "unresolved_complaint": "the customer sounds unhappy",
    "overdue_commitment": "a commitment we made is past due",
    "unanswered_inbound": "their last message has no reply",
    "quote_without_followup": "a quote was never followed up",
    "stale_opportunity": "an open opportunity has gone quiet",
}


def record_commitments(org, now_iso=None, limit=2000):
    """Persist every commitment we can find, with its current state.

    Findings are the urgent slice; this is the full ledger. An owner asking
    "what did we promise customers?" is asking for this table, and it has to
    contain the kept promises too — a record that only lists failures is a
    complaints log, not a commitment register.
    """
    now_iso = now_iso or db.now()
    counts = {"total": 0, "open": 0, "overdue": 0, "likely_fulfilled": 0}
    for conv in db.conversations(org["id"], limit=limit):
        view = _thread_view(org["id"], conv)
        for m in view["outbound"]:
            for c in commit_mod.extract(m.get("body") or "", m.get("sent_at")):
                later = [x for x in view["outbound"]
                         if (x["sent_at"] or "") > (m["sent_at"] or "") and x["id"] != m["id"]]
                if c["due_at"] and any((x["sent_at"] or "") <= c["due_at"] for x in later):
                    state = "likely_fulfilled"
                elif later:
                    state = "likely_fulfilled"
                elif _customer_closed_after(view, m["sent_at"]):
                    # Kept off-email, and the customer confirmed it.
                    state = "likely_fulfilled"
                elif c["due_at"] and c["due_at"] < now_iso:
                    state = "overdue"
                elif not c["due_at"]:
                    state = "open"
                else:
                    state = "open"
                db.upsert_commitment(
                    org["id"], message_id=m["id"], conversation_id=conv["id"],
                    entity_id=conv.get("entity_id"), promiser=m.get("from_addr"),
                    direction="out", text=c["action"], quote=c["quote"],
                    due_at=c["due_at"], due_basis=c["due_basis"], state=state,
                    confidence=c["confidence"], detector="commitment_engine")
                counts["total"] += 1
                counts[state] = counts.get(state, 0) + 1
    return counts


def bounced_entities(org_id):
    """Contacts whose mail has failed, from the event ledger.

    Held org-wide rather than per-thread because a bounce rarely threads with
    the message it concerns.
    """
    return {e["entity_id"] for e in db.events(org_id, kind="EMAIL_BOUNCED", limit=2000)
            if e.get("entity_id")}


def run(org, now_iso=None, limit=2000):
    """Every finding the corpus currently supports, with evidence."""
    _NAME_CACHE.clear()
    now_iso = now_iso or db.now()
    bounced_contacts = bounced_entities(org["id"])
    out = []
    for conv in db.conversations(org["id"], limit=limit):
        view = _thread_view(org["id"], conv)
        if _eligible(org, view, now_iso):
            continue
        bounced = (bool(view["bounces"])
                   or conv.get("entity_id") in bounced_contacts)
        for rule in THREAD_RULES:
            if bounced and rule.__name__ in (
                    "overdue_commitment", "unanswered_inbound", "stale_opportunity",
                    "quote_without_followup"):
                continue     # the mail never arrived; none of those conclusions hold
            try:
                res = rule(org, view, now_iso)
            except Exception:
                continue                     # one bad thread must not kill the scan
            if not res:
                continue
            for f, ev in (res if isinstance(res, list) else [res]):
                f["_conversation_id"] = conv["id"]
                out.append((f, ev))

    for rule in ORG_RULES:
        try:
            for f, ev in rule(org, now_iso):
                f["_conversation_id"] = None
                out.append((f, ev))
        except Exception:
            continue
    return consolidate(out)
