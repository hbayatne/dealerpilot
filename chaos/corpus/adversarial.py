"""
The adversarial corpus — the messy email patterns that break naive detectors.

Every case here was added because it produced a wrong finding at some point. An
out-of-office reply read as a customer's silence. A bounce read as a broken
promise. A six-line signature read as an unanswered question. Each is the kind
of visibly false claim that costs an owner's trust in every *correct* finding
beside it, which is why they are tested as hard as the true positives.

A case whose reason contains "SHOULD FIRE" must produce a finding. Every other
case must produce silence.
"""
import datetime

NOW = datetime.datetime(2026, 9, 9, 10, 0)
US = "northsideroofing.example"
REP = f"dana@{US}"


def dt(days=0, hours=0):
    return (NOW + datetime.timedelta(days=days, hours=hours)).strftime(
        "%a, %d %b %Y %H:%M:%S -0500")


def msg(mid, subject, frm, name, to, date, body, refs=None, headers=None):
    h = {"message-id": mid}
    if refs:
        h["references"] = refs; h["in-reply-to"] = refs
    h.update(headers or {})
    return {"source_id": mid, "message_id": mid, "headers": h, "subject": subject,
            "from_name": name, "from_addr": frm,
            "to": [{"name": "", "addr": a} for a in (to if isinstance(to, list) else [to])],
            "cc": [], "date": date, "body": body, "attachments": []}


CASES = []

# A1 Out-of-office auto-reply sitting as the last inbound message.
CASES.append(("A1 out-of-office autoreply", [
    msg("<a1a>", "Quote request", "lee@acme.example", "Lee Park", REP, dt(-20),
        "Could you send pricing for the warehouse roof?"),
    msg("<a1b>", "Re: Quote request", REP, "Dana", "lee@acme.example", dt(-19),
        "Sure — quote attached, $22,000 for the full tear-off."),
    msg("<a1c>", "Automatic reply: Quote request", "lee@acme.example", "Lee Park", REP,
        dt(-19), "I am out of the office until October 1 with limited email access.",
        refs="<a1a>", headers={"auto-submitted": "auto-replied", "x-autoreply": "yes"}),
], "auto-reply is not a customer waiting"))

# A2 Bounce / delivery failure.
CASES.append(("A2 bounce message", [
    msg("<a2a>", "Follow up", REP, "Dana", "gone@dead.example", dt(-15),
        "Just checking in on the estimate. I'll call you Friday."),
    msg("<a2b>", "Undeliverable: Follow up", "MAILER-DAEMON@dead.example", "Mail Delivery",
        REP, dt(-15), "Your message could not be delivered. 550 user unknown.",
        headers={"auto-submitted": "auto-generated"}),
], "SHOULD FIRE: the email never arrived — that is the finding, not a broken promise"))

# A3 Vendor invoice thread — a supplier, not a customer, and it is handled.
CASES.append(("A3 vendor thread, handled", [
    msg("<a3a>", "September statement", "ar@supplyco.example", "Supply Co AR", REP, dt(-10),
        "Attached is your September statement, balance $4,320 due on the 30th."),
    msg("<a3b>", "Re: September statement", REP, "Dana", "ar@supplyco.example", dt(-9),
        "Got it, payment scheduled. Thanks!", refs="<a3a>"),
], "handled vendor thread"))

# A4 Customer explicitly defers — the ball is in their court.
CASES.append(("A4 customer defers to later", [
    msg("<a4a>", "Roof replacement", "sam.ortiz@gmail.com", "Sam Ortiz", REP, dt(-30),
        "What would a full replacement run?"),
    msg("<a4b>", "Re: Roof replacement", REP, "Dana", "sam.ortiz@gmail.com", dt(-30),
        "Roughly $18,500 depending on decking. Happy to come measure.", refs="<a4a>"),
    msg("<a4c>", "Re: Roof replacement", "sam.ortiz@gmail.com", "Sam Ortiz", REP, dt(-29),
        "Thanks. We're not doing anything until the spring — I'll reach out then.",
        refs="<a4a>"),
], "customer said they'd come back; nothing is owed by us"),)

# A5 Long chain with heavy quoting — the promise appears only in quoted history.
CASES.append(("A5 promise only in quoted history", [
    msg("<a5a>", "Flashing repair", "ruth.kim@gmail.com", "Ruth Kim", REP, dt(-6),
        "Thanks for coming out yesterday."),
    msg("<a5b>", "Re: Flashing repair", REP, "Dana", "ruth.kim@gmail.com", dt(-5),
        "Anytime! All wrapped up.\n\n"
        "On Mon, Sep 1, 2026 at 9:00 AM Dana <dana@northsideroofing.example> wrote:\n"
        "> I'll call you Friday with the numbers.\n"
        "> I'll also send the warranty over tomorrow.\n", refs="<a5a>"),
], "promises inside quoted history were already handled"))

# A6 Internal forward of a customer email — colleagues, not clients.
CASES.append(("A6 internal forward", [
    msg("<a6a>", "Fwd: leaking gutter", REP, "Dana", f"owner@{US}", dt(-4),
        "Can you take this one? I'll be out Thursday.\n\n"
        "---------- Forwarded message ----------\n"
        "From: angry.customer@gmail.com\n"
        "This is unacceptable, nobody has called me back."),
], "internal chatter, even when it quotes a customer"))

# A7 Newsletter that happens to ask a question.
CASES.append(("A7 marketing with a question", [
    msg("<a7>", "Ready to grow your roofing business?", "hello@leadgen.example", "LeadGen",
        REP, dt(-3), "Want more leads this quarter? Reply to book a demo!",
        headers={"list-unsubscribe": "<https://x>", "precedence": "bulk"}),
], "marketing email, not a customer"))

# A8 Signature-only content — nothing was actually asked.
CASES.append(("A8 signature noise", [
    msg("<a8>", "Re: invoice", "kay@bright.example", "Kay Diaz", REP, dt(-8),
        "Thanks!\n\n--\nKay Diaz | Bright Property Group\n"
        "Can you believe how fast this year is going?\n"
        "office: (214) 555-0100 | bright.example"),
], "polite close, signature is not a request"))

# A9 A promise we kept the same day.
CASES.append(("A9 promise kept same day", [
    msg("<a9a>", "Warranty copy", "nina.roy@gmail.com", "Nina Roy", REP, dt(-12),
        "Could you send the warranty paperwork?"),
    msg("<a9b>", "Re: Warranty copy", REP, "Dana", "nina.roy@gmail.com", dt(-12, 1),
        "Absolutely, I'll send it today.", refs="<a9a>"),
    msg("<a9c>", "Re: Warranty copy", REP, "Dana", "nina.roy@gmail.com", dt(-12, 3),
        "Here it is, attached.", refs="<a9a>"),
], "kept within hours"))

# A10 Genuine miss hidden in a long chain — this one SHOULD fire.
CASES.append(("A10 real miss in a long chain", [
    msg("<a10a>", "Storm damage claim", "omar.haddad@gmail.com", "Omar Haddad", REP, dt(-18),
        "Insurance approved the claim. When can you start?"),
    msg("<a10b>", "Re: Storm damage claim", REP, "Dana", "omar.haddad@gmail.com", dt(-17),
        "Great news. I'll get you on the schedule and confirm dates Monday.",
        refs="<a10a>"),
    msg("<a10c>", "Re: Storm damage claim", "omar.haddad@gmail.com", "Omar Haddad", REP,
        dt(-5), "Any word on dates? The tarp is starting to leak.\n\n"
        "On Wed Dana wrote:\n> I'll get you on the schedule and confirm dates Monday.",
        refs="<a10a>"),
], "SHOULD FIRE: promised dates, never delivered, customer chased"))



def build(now=None):
    """(cases, now) — the labelled corpus and the instant it is anchored to."""
    return CASES, now or NOW
