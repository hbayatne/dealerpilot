"""
The adversarial corpus — the messy email patterns that break naive detectors.

Every case here was added because it produced a wrong finding at some point. An
out-of-office reply read as a customer's silence. A bounce read as a broken
promise. A six-line signature read as an unanswered question. A conversation
between two other people that we were merely copied on. Each is the kind of
visibly false claim that costs an owner's trust in every *correct* finding
beside it, which is why they are tested as hard as the true positives.

Each case declares the detectors it must produce; an empty list means the corpus
must stay silent. Asserting the *detector* rather than merely that something
fired is what catches the subtler failure — a thread that yields a finding of the
wrong kind, blaming the wrong party for the wrong thing.

A case is `(name, messages, expected_detectors, why)`.
"""
import datetime

NOW = datetime.datetime(2026, 9, 9, 10, 0)          # a Wednesday
US = "northsideroofing.example"
REP = f"dana@{US}"
OWNER = f"owner@{US}"
OFFICE = f"office@{US}"


def dt(days=0, hours=0, now=None):
    return ((now or NOW) + datetime.timedelta(days=days, hours=hours)).strftime(
        "%a, %d %b %Y %H:%M:%S -0500")


def msg(mid, subject, frm, name, to, date, body, refs=None, headers=None, cc=None):
    h = {"message-id": mid}
    if refs:
        h["references"] = refs
        h["in-reply-to"] = refs
    h.update(headers or {})
    return {"source_id": mid, "message_id": mid, "headers": h, "subject": subject,
            "from_name": name, "from_addr": frm,
            "to": [{"name": "", "addr": a} for a in (to if isinstance(to, list) else [to])],
            "cc": [{"name": "", "addr": a} for a in (cc or [])],
            "date": date, "body": body, "attachments": []}


CASES = []

# ---------------------------------------------------------------- must fire
CASES.append(("A1 promised Thursday, never delivered", [
    msg("<a1a>", "Roof estimate for 412 Oak St", "marcus.webb@gmail.com", "Marcus Webb",
        REP, dt(-12, -2),
        "Hi, we had some shingles come off in the storm. Can you send me an "
        "estimate for the repair? Our address is 412 Oak St."),
    msg("<a1b>", "Re: Roof estimate for 412 Oak St", REP, "Dana Reyes",
        "marcus.webb@gmail.com", dt(-11),
        "Hi Marcus — thanks for reaching out. I'll come by Thursday and get you "
        "a written estimate.", refs="<a1a>"),
    msg("<a1c>", "Re: Roof estimate for 412 Oak St", "marcus.webb@gmail.com",
        "Marcus Webb", REP, dt(-4),
        "Hi Dana, just following up again — did you get a chance to put that "
        "estimate together? We're getting more rain this week.", refs="<a1a>"),
], ["overdue_commitment"], "promised Thursday, never delivered, customer chased"))

CASES.append(("A2 quote sent, never chased", [
    msg("<a2a>", "Gutter replacement quote", "j.calder@brightway.example", "Julia Calder",
        OFFICE, dt(-25),
        "Following up on our call — could you price out full gutter replacement "
        "for the Brightway building?"),
    msg("<a2b>", "Re: Gutter replacement quote", OFFICE, "Northside Office",
        "j.calder@brightway.example", dt(-22),
        "Hi Julia — our quote for the full gutter replacement is $14,800 total, "
        "including tear-off and disposal. Let me know how you'd like to proceed.",
        refs="<a2a>"),
], ["quote_without_followup"], "$14,800 quote, 22 days, no reply and no chase"))

CASES.append(("A3 escalating complaint, unanswered", [
    msg("<a3a>", "Leak is back", "pat.nguyen@gmail.com", "Pat Nguyen", REP, dt(-9),
        "The repair you did in June is leaking again in the same spot."),
    msg("<a3b>", "Re: Leak is back", REP, "Dana Reyes", "pat.nguyen@gmail.com", dt(-8),
        "Sorry to hear that Pat — I'll get someone out there this week to take "
        "a look.", refs="<a3a>"),
    msg("<a3c>", "Re: Leak is back", "pat.nguyen@gmail.com", "Pat Nguyen", REP, dt(-2),
        "This is the third time I've written and nobody has come out. The ceiling "
        "is staining now. This is completely unacceptable — if someone isn't here "
        "this week I'm going to dispute the charge.", refs="<a3a>"),
], ["unresolved_complaint"], "escalation with a chargeback threat, unanswered"))

CASES.append(("A4 ready-to-buy signal gone quiet", [
    msg("<a4a>", "New roof - ready to move", "t.okafor@gmail.com", "Tola Okafor",
        OFFICE, dt(-30),
        "We're ready to move forward on the full roof replacement we discussed. "
        "What's the next step?"),
    msg("<a4b>", "Re: New roof - ready to move", OFFICE, "Northside Office",
        "t.okafor@gmail.com", dt(-29),
        "Great news! Let me get the crew schedule and confirm dates.", refs="<a4a>"),
], ["stale_opportunity"], "ready-to-buy signal, silent 29 days"))

CASES.append(("A5 bounced email nobody noticed", [
    msg("<a5a>", "Follow up", REP, "Dana", "gone@dead.example", dt(-15),
        "Just checking in on the estimate. I'll call you Friday."),
    msg("<a5b>", "Undeliverable: Follow up", "MAILER-DAEMON@dead.example",
        "Mail Delivery", REP, dt(-15),
        "Your message could not be delivered. 550 user unknown.",
        headers={"auto-submitted": "auto-generated"}),
], ["undelivered_email"],
    "the email never arrived — that is the finding, not a broken promise"))

CASES.append(("A6 our own autoresponder is not an answer", [
    msg("<a6a>", "Gutter leak", "rosa.diaz@gmail.com", "Rosa Diaz", REP, dt(-10),
        "Our gutter is overflowing badly. Can someone come out this week?"),
    msg("<a6b>", "Automatic reply: Gutter leak", REP, "Dana Reyes",
        "rosa.diaz@gmail.com", dt(-10), "I'm out of the office until the 15th.",
        refs="<a6a>", headers={"auto-submitted": "auto-replied", "x-autoreply": "yes"}),
], ["unanswered_inbound"],
    "our autoresponder is not an answer — the customer is still waiting"))

CASES.append(("A7 a vendor chasing us, ignored", [
    msg("<a7a>", "Overdue: statement 88214", "ar@metalsupply.example", "Metal Supply AR",
        OFFICE, dt(-16),
        "Your account is 45 days past due at $6,900. Can you confirm when payment "
        "will be sent?"),
    msg("<a7b>", "Re: Overdue: statement 88214", "ar@metalsupply.example",
        "Metal Supply AR", OFFICE, dt(-4),
        "Following up again — we still haven't heard back and the account is now "
        "on hold.", refs="<a7a>"),
], ["unresolved_complaint"],
    "ignoring a vendor stops your supply — a business problem, not just rudeness"))

CASES.append(("A8 customer asked questions about a quote", [
    msg("<a8a>", "Deck replacement", "sofia.rossi@gmail.com", "Sofia Rossi", OFFICE,
        dt(-20), "What would a deck replacement cost?"),
    msg("<a8b>", "Re: Deck replacement", OFFICE, "Northside Office",
        "sofia.rossi@gmail.com", dt(-19),
        "Roughly $11,200 for composite, $7,800 for pressure-treated.", refs="<a8a>"),
    msg("<a8c>", "Re: Deck replacement", "sofia.rossi@gmail.com", "Sofia Rossi",
        OFFICE, dt(-18),
        "Does the composite price include railings? And how long would it take?",
        refs="<a8a>"),
], ["unanswered_inbound"], "two direct questions, nothing back"))

CASES.append(("A9 quote unchased even though a colleague answered", [
    msg("<a9a>", "Skylight quote", "ana.vidal@gmail.com", "Ana Vidal", REP, dt(-9),
        "Could you quote a skylight install for the back bedroom?"),
    msg("<a9b>", "Re: Skylight quote", OFFICE, "Northside Office", "ana.vidal@gmail.com",
        dt(-8), "Hi Ana — Dana's out this week so I've got this. Quote is $3,400 "
        "installed, and I can book you for the 22nd.", refs="<a9a>"),
], ["quote_without_followup"],
    "whoever answered, the quote itself was never followed up — that is the finding"))

# ---------------------------------------------------------------- must stay silent
CASES.append(("B1 bulk newsletter", [
    msg("<b1>", "Fall roofing trends + 15% off materials", "news@mailchimp.com",
        "Supply Co", OFFICE, dt(-3),
        "Check out our fall promotions! Unsubscribe here.",
        headers={"list-unsubscribe": "<https://x/u>", "precedence": "bulk"}),
], [], "a newsletter is not a neglected customer"))

CASES.append(("B2 internal chatter", [
    msg("<b2>", "Crew schedule Thursday", REP, "Dana Reyes", [OWNER, OFFICE], dt(-1),
        "Can you confirm we have three guys for the Oak St job? I'll update the "
        "board tomorrow."),
], [], "colleagues are not clients"))

CASES.append(("B3 answered quickly and closed politely", [
    msg("<b3a>", "Invoice question", "beth.moreau@gmail.com", "Beth Moreau", OFFICE,
        dt(-6), "Quick question — does the invoice include the permit fee?"),
    msg("<b3b>", "Re: Invoice question", OFFICE, "Northside Office",
        "beth.moreau@gmail.com", dt(-6, 1),
        "Hi Beth — yes, the permit fee is included in the $9,200 total.", refs="<b3a>"),
    msg("<b3c>", "Re: Invoice question", "beth.moreau@gmail.com", "Beth Moreau",
        OFFICE, dt(-6, 2), "Perfect, thanks!", refs="<b3a>"),
], [], "answered in an hour and closed"))

CASES.append(("B4 arrived Friday evening", [
    msg("<b4>", "Saturday availability?", "rick.alvarez@gmail.com", "Rick Alvarez",
        OFFICE,
        (NOW - datetime.timedelta(days=(NOW.weekday() - 4) % 7 or 7)
         ).replace(hour=17, minute=40).strftime("%a, %d %b %Y %H:%M:%S -0500"),
        "Are you guys available to look at a chimney flashing issue?"),
], [], "no business hours have passed — answering Monday is prompt"))

CASES.append(("B5 explicit opt-out", [
    msg("<b5a>", "Please stop", "former.client@gmail.com", "Former Client", OFFICE,
        dt(-20), "Please remove me from your list and do not contact me again."),
    msg("<b5b>", "Re: Please stop", OFFICE, "Northside Office",
        "former.client@gmail.com", dt(-20, 1), "Understood — you've been removed.",
        refs="<b5a>"),
], [], "never recommend contacting someone who asked us not to"))

CASES.append(("B6 an offer, not a commitment", [
    msg("<b6a>", "Skylight options", "hana.suzuki@gmail.com", "Hana Suzuki", REP,
        dt(-15), "Do you install skylights?"),
    msg("<b6b>", "Re: Skylight options", REP, "Dana Reyes", "hana.suzuki@gmail.com",
        dt(-15, 3),
        "We do. Let me know if you'd like me to send over some options and "
        "pricing — happy to put something together whenever you're ready.",
        refs="<b6a>"),
], [], "the next move is the customer's, so nothing is overdue"))

CASES.append(("B7 automated receipt", [
    msg("<b7>", "Your receipt from Home Depot", "no-reply@homedepot.example",
        "Home Depot", OFFICE, dt(-2), "Order confirmation #4421."),
], [], "a transactional receipt"))

CASES.append(("B8 commitment kept the next day", [
    msg("<b8a>", "Inspection report", "greg.li@harborview.example", "Greg Li", REP,
        dt(-10), "Can you send over the inspection report when you have it?"),
    msg("<b8b>", "Re: Inspection report", REP, "Dana Reyes",
        "greg.li@harborview.example", dt(-9), "Absolutely — I'll send it tomorrow.",
        refs="<b8a>"),
    msg("<b8c>", "Re: Inspection report", REP, "Dana Reyes",
        "greg.li@harborview.example", dt(-8),
        "Here's the inspection report, attached.", refs="<b8a>"),
    msg("<b8d>", "Re: Inspection report", "greg.li@harborview.example", "Greg Li",
        REP, dt(-8, 2), "Got it, appreciate it.", refs="<b8a>"),
], [], "kept the next day"))

CASES.append(("B9 customer defers to later", [
    msg("<b9a>", "Roof replacement", "sam.ortiz@gmail.com", "Sam Ortiz", REP, dt(-30),
        "What would a full replacement run?"),
    msg("<b9b>", "Re: Roof replacement", REP, "Dana", "sam.ortiz@gmail.com", dt(-30),
        "Roughly $18,500 depending on decking. Happy to come measure.", refs="<b9a>"),
    msg("<b9c>", "Re: Roof replacement", "sam.ortiz@gmail.com", "Sam Ortiz", REP,
        dt(-29),
        "Thanks. We're not doing anything until the spring — I'll reach out then.",
        refs="<b9a>"),
], [], "the customer said they would come back; nothing is owed by us"))

CASES.append(("B10 promise only inside quoted history", [
    msg("<b10a>", "Flashing repair", "ruth.kim@gmail.com", "Ruth Kim", REP, dt(-6),
        "Thanks for coming out yesterday."),
    msg("<b10b>", "Re: Flashing repair", REP, "Dana", "ruth.kim@gmail.com", dt(-5),
        "Anytime! All wrapped up.\n\n"
        "On Mon, Sep 1, 2026 at 9:00 AM Dana <dana@northsideroofing.example> wrote:\n"
        "> I'll call you Friday with the numbers.\n"
        "> I'll also send the warranty over tomorrow.\n", refs="<b10a>"),
], [], "quoted history must not be re-detected as new promises"))

CASES.append(("B11 internal forward quoting an angry customer", [
    msg("<b11>", "Fwd: leaking gutter", REP, "Dana", OWNER, dt(-4),
        "Can you take this one? I'll be out Thursday.\n\n"
        "---------- Forwarded message ----------\n"
        "From: angry.customer@gmail.com\n"
        "This is unacceptable, nobody has called me back."),
], [], "internal chatter, even when it quotes a customer"))

CASES.append(("B12 signature noise", [
    msg("<b12>", "Re: invoice", "kay@bright.example", "Kay Diaz", REP, dt(-8),
        "Thanks!\n\n--\nKay Diaz | Bright Property Group\n"
        "Can you believe how fast this year is going?\n"
        "office: (214) 555-0100 | bright.example"),
], [], "a polite close; the footer is not a question to us"))

CASES.append(("B13 handled vendor thread", [
    msg("<b13a>", "September statement", "ar@supplyco.example", "Supply Co AR", REP,
        dt(-10),
        "Attached is your September statement, balance $4,320 due on the 30th."),
    msg("<b13b>", "Re: September statement", REP, "Dana", "ar@supplyco.example",
        dt(-9), "Got it, payment scheduled. Thanks!", refs="<b13a>"),
], [], "answered and closed"))

CASES.append(("B14 we are only CC'd", [
    msg("<b14>", "HOA roof inspection", "liz.tran@hoaboard.example", "Liz Tran",
        "board@hoaboard.example", dt(-6),
        "Board — can someone confirm we're on for the inspection?", cc=[REP]),
], [], "a conversation between other people that we were copied on"))

CASES.append(("B15 CRM notification that looks like a lead", [
    msg("<b15>", "New Lead: Marcus Webb - Roof Replacement",
        "notifications@crmapp.example", "CRM", OFFICE, dt(-4),
        "A new lead was assigned to you.\nName: Marcus Webb\n"
        "Interest: roof replacement\nCan you follow up today?",
        headers={"auto-submitted": "auto-generated",
                 "list-unsubscribe": "<https://crmapp.example/u>"}),
], [], "an automated CRM notice, not a customer writing"))

CASES.append(("B16 brief acknowledgement closes the loop", [
    msg("<b16a>", "Invoice", OFFICE, "Northside Office", "ken.obi@gmail.com", dt(-7),
        "Hi Ken, invoice attached for the $2,150 repair."),
    msg("<b16b>", "Re: Invoice", "ken.obi@gmail.com", "Ken Obi", OFFICE, dt(-7, 2),
        "ok", refs="<b16a>"),
], [], "a one-word acknowledgement is still an answer"))

CASES.append(("B17 promise kept off-email, customer confirmed", [
    msg("<b17a>", "Chimney flashing", "ivy.park@gmail.com", "Ivy Park", REP, dt(-14),
        "Can you look at the chimney flashing?"),
    msg("<b17b>", "Re: Chimney flashing", REP, "Dana", "ivy.park@gmail.com", dt(-13),
        "Sure — I'll come by Friday and take a look.", refs="<b17a>"),
    msg("<b17c>", "Re: Chimney flashing", "ivy.park@gmail.com", "Ivy Park", REP,
        dt(-11), "Perfect, thanks! All sorted.", refs="<b17a>"),
], [],
    "we only see email; a promise to show up is kept in person, and the customer "
    "confirming it outweighs our silence"))

CASES.append(("B18 active back-and-forth, finished", [
    msg("<b18a>", "Scheduling the crew", "hugo.lemaire@propgroup.example",
        "Hugo Lemaire", OFFICE, dt(-5), "Can we move the start to the 20th?"),
    msg("<b18b>", "Re: Scheduling the crew", OFFICE, "Northside Office",
        "hugo.lemaire@propgroup.example", dt(-5, 1),
        "The 20th works. I'll confirm the crew tomorrow.", refs="<b18a>"),
    msg("<b18c>", "Re: Scheduling the crew", OFFICE, "Northside Office",
        "hugo.lemaire@propgroup.example", dt(-4),
        "Crew is confirmed for the 20th, 7am start.", refs="<b18a>"),
    msg("<b18d>", "Re: Scheduling the crew", "hugo.lemaire@propgroup.example",
        "Hugo Lemaire", OFFICE, dt(-4, 2), "Great, see you then.", refs="<b18a>"),
], [], "healthy, current, and concluded"))


def build(now=None):
    """(cases, now) — the labelled corpus and the instant it is anchored to.

    Each case is `(name, messages, expected_detectors, why)`.
    """
    return CASES, now or NOW
