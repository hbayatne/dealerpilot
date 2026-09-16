"""
A realistic demo mailbox — clearly labelled, never presented as real findings.

Two jobs. It lets someone see the product before connecting a mailbox, and it is
the fixture the detectors are measured against. It deliberately contains threads
that *must not* produce findings (newsletters, internal chatter, threads that
ended politely, a weekend that only looks like a delay, a contact who opted out)
alongside the ones that should. A corpus of only true positives measures nothing.

`expected` on each thread is the ground truth the accuracy harness scores against.
"""
import datetime

DEMO_BANNER = "DEMO DATA — this is a sample business, not your real findings."

ORG = {"name": "Northside Roofing (demo)", "website": "https://example.com",
       "industry": "roofing", "domains": ["northsideroofing.example"]}


def _dt(base, days=0, hours=0, minutes=0):
    return (base + datetime.timedelta(days=days, hours=hours, minutes=minutes)
            ).strftime("%a, %d %b %Y %H:%M:%S -0500")


def _msg(mid, subject, frm, frm_name, to, date, body, refs=None, headers=None):
    h = {"message-id": mid}
    if refs:
        h["references"] = refs
        h["in-reply-to"] = refs
    h.update(headers or {})
    return {"source_id": mid, "message_id": mid, "headers": h, "subject": subject,
            "from_name": frm_name, "from_addr": frm,
            "to": [{"name": "", "addr": a} for a in (to if isinstance(to, list) else [to])],
            "cc": [], "date": date, "body": body, "attachments": []}


US = "northsideroofing.example"
REP = f"dana@{US}"
OWNER = f"owner@{US}"
OFFICE = f"office@{US}"


def build(now=None):
    """(messages, expectations). `now` anchors every relative timestamp."""
    now = now or datetime.datetime(2026, 9, 9, 10, 0)      # a Wednesday
    m, expect = [], []

    # 1. TRUE POSITIVE — overdue commitment + unanswered chase.
    m += [
        _msg("<d1a>", "Roof estimate for 412 Oak St", "marcus.webb@gmail.com", "Marcus Webb",
             REP, _dt(now, days=-12, hours=-2),
             "Hi, we had some shingles come off in the storm. Can you send me an "
             "estimate for the repair? Our address is 412 Oak St."),
        _msg("<d1b>", "Re: Roof estimate for 412 Oak St", REP, "Dana Reyes",
             "marcus.webb@gmail.com", _dt(now, days=-11), 
             "Hi Marcus — thanks for reaching out. I'll come by Thursday and get you "
             "a written estimate.", refs="<d1a>"),
        _msg("<d1c>", "Re: Roof estimate for 412 Oak St", "marcus.webb@gmail.com",
             "Marcus Webb", REP, _dt(now, days=-4),
             "Hi Dana, just following up again — did you get a chance to put that "
             "estimate together? We're getting more rain this week.", refs="<d1a>"),
    ]
    expect.append({"thread": "<d1a>", "should": ["overdue_commitment", "unanswered_inbound"],
                   "why": "promised Thursday, never delivered, customer chased"})

    # 2. TRUE POSITIVE — quote sent, never chased.
    m += [
        _msg("<d2a>", "Gutter replacement quote", "j.calder@brightway.example", "Julia Calder",
             OFFICE, _dt(now, days=-25),
             "Following up on our call — could you price out full gutter replacement "
             "for the Brightway building?"),
        _msg("<d2b>", "Re: Gutter replacement quote", OFFICE, "Northside Office",
             "j.calder@brightway.example", _dt(now, days=-22),
             "Hi Julia — our quote for the full gutter replacement is $14,800 total, "
             "including tear-off and disposal. Let me know how you'd like to proceed.",
             refs="<d2a>"),
    ]
    expect.append({"thread": "<d2a>", "should": ["quote_without_followup"],
                   "why": "$14,800 quote, 22 days, no reply and no chase"})

    # 3. TRUE POSITIVE — escalating complaint, unanswered.
    m += [
        _msg("<d3a>", "Leak is back", "pat.nguyen@gmail.com", "Pat Nguyen", REP,
             _dt(now, days=-9),
             "The repair you did in June is leaking again in the same spot."),
        _msg("<d3b>", "Re: Leak is back", REP, "Dana Reyes", "pat.nguyen@gmail.com",
             _dt(now, days=-8), "Sorry to hear that Pat — I'll get someone out there "
             "this week to take a look.", refs="<d3a>"),
        _msg("<d3c>", "Re: Leak is back", "pat.nguyen@gmail.com", "Pat Nguyen", REP,
             _dt(now, days=-2),
             "This is the third time I've written and nobody has come out. The ceiling "
             "is staining now. This is completely unacceptable — if someone isn't here "
             "this week I'm going to dispute the charge.", refs="<d3a>"),
    ]
    expect.append({"thread": "<d3a>",
                   "should": ["unresolved_complaint", "unanswered_inbound",
                              "overdue_commitment"],
                   "why": "escalation with chargeback threat, unanswered"})

    # 4. TRUE POSITIVE — stale opportunity with buying intent.
    m += [
        _msg("<d4a>", "New roof - ready to move", "t.okafor@gmail.com", "Tola Okafor",
             OFFICE, _dt(now, days=-30),
             "We're ready to move forward on the full roof replacement we discussed. "
             "What's the next step?"),
        _msg("<d4b>", "Re: New roof - ready to move", OFFICE, "Northside Office",
             "t.okafor@gmail.com", _dt(now, days=-29),
             "Great news! Let me get the crew schedule and confirm dates.", refs="<d4a>"),
    ]
    expect.append({"thread": "<d4a>", "should": ["stale_opportunity"],
                   "why": "ready-to-buy signal, silent 29 days"})

    # ---------------- the cases that must produce NOTHING ----------------

    # 5. Newsletter.
    m.append(_msg("<d5>", "🍂 Fall roofing trends + 15% off materials",
                  "news@mailchimp.com", "Supply Co", OFFICE, _dt(now, days=-3),
                  "Check out our fall promotions! Unsubscribe here.",
                  headers={"list-unsubscribe": "<https://x/u>", "precedence": "bulk"}))
    expect.append({"thread": "<d5>", "should": [], "why": "bulk newsletter"})

    # 6. Internal only.
    m.append(_msg("<d6>", "Crew schedule Thursday", REP, "Dana Reyes", [OWNER, OFFICE],
                  _dt(now, days=-1),
                  "Can you confirm we have three guys for the Oak St job? I'll update "
                  "the board tomorrow."))
    expect.append({"thread": "<d6>", "should": [], "why": "internal chatter, no customer"})

    # 7. Thread that ended cleanly.
    m += [
        _msg("<d7a>", "Invoice question", "beth.moreau@gmail.com", "Beth Moreau", OFFICE,
             _dt(now, days=-6), "Quick question — does the invoice include the permit fee?"),
        _msg("<d7b>", "Re: Invoice question", OFFICE, "Northside Office",
             "beth.moreau@gmail.com", _dt(now, days=-6, hours=1),
             "Hi Beth — yes, the permit fee is included in the $9,200 total.",
             refs="<d7a>"),
        _msg("<d7c>", "Re: Invoice question", "beth.moreau@gmail.com", "Beth Moreau",
             OFFICE, _dt(now, days=-6, hours=2), "Perfect, thanks!", refs="<d7a>"),
    ]
    expect.append({"thread": "<d7a>", "should": [],
                   "why": "answered in an hour and closed politely"})

    # 8. Weekend boundary — looks like 60 hours of silence, is zero business hours.
    friday = now - datetime.timedelta(days=(now.weekday() - 4) % 7 or 7)
    friday = friday.replace(hour=17, minute=40)
    m.append(_msg("<d8>", "Saturday availability?", "rick.alvarez@gmail.com",
                  "Rick Alvarez", OFFICE,
                  friday.strftime("%a, %d %b %Y %H:%M:%S -0500"),
                  "Are you guys available to look at a chimney flashing issue?"))
    expect.append({"thread": "<d8>", "should": [],
                   "why": "arrived Friday evening — no business hours have passed"})

    # 9. Opted out.
    m += [
        _msg("<d9a>", "Please stop", "former.client@gmail.com", "Former Client", OFFICE,
             _dt(now, days=-20),
             "Please remove me from your list and do not contact me again."),
        _msg("<d9b>", "Re: Please stop", OFFICE, "Northside Office",
             "former.client@gmail.com", _dt(now, days=-20, hours=1),
             "Understood — you've been removed.", refs="<d9a>"),
    ]
    expect.append({"thread": "<d9a>", "should": [], "why": "explicit opt-out"})

    # 10. An offer, not a commitment — and answered.
    m += [
        _msg("<d10a>", "Skylight options", "hana.suzuki@gmail.com", "Hana Suzuki", REP,
             _dt(now, days=-15), "Do you install skylights?"),
        _msg("<d10b>", "Re: Skylight options", REP, "Dana Reyes", "hana.suzuki@gmail.com",
             _dt(now, days=-15, hours=3),
             "We do. Let me know if you'd like me to send over some options and "
             "pricing — happy to put something together whenever you're ready.",
             refs="<d10a>"),
    ]
    expect.append({"thread": "<d10a>", "should": [],
                   "why": "an offer awaiting the customer, not a broken promise"})

    # 11. Receipt / transactional.
    m.append(_msg("<d11>", "Your receipt from Home Depot", "no-reply@homedepot.example",
                  "Home Depot", OFFICE, _dt(now, days=-2), "Order confirmation #4421."))
    expect.append({"thread": "<d11>", "should": [], "why": "automated receipt"})

    # 12. Promise that WAS kept — must stay silent.
    m += [
        _msg("<d12a>", "Inspection report", "greg.li@harborview.example", "Greg Li", REP,
             _dt(now, days=-10), "Can you send over the inspection report when you have it?"),
        _msg("<d12b>", "Re: Inspection report", REP, "Dana Reyes",
             "greg.li@harborview.example", _dt(now, days=-9),
             "Absolutely — I'll send it tomorrow.", refs="<d12a>"),
        _msg("<d12c>", "Re: Inspection report", REP, "Dana Reyes",
             "greg.li@harborview.example", _dt(now, days=-8),
             "Here's the inspection report, attached.", refs="<d12a>"),
        _msg("<d12d>", "Re: Inspection report", "greg.li@harborview.example", "Greg Li",
             REP, _dt(now, days=-8, hours=2), "Got it, appreciate it.", refs="<d12a>"),
    ]
    expect.append({"thread": "<d12a>", "should": [],
                   "why": "commitment was kept the next day"})

    return m, expect
