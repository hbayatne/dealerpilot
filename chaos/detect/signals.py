"""
Text signals — money, urgency, complaints, buying intent, opt-out.

These are the small classifiers the finding rules lean on. All deterministic and
all *explainable*: each returns the matched phrase alongside the verdict, so a
finding can quote the evidence instead of asserting a conclusion.

Money extraction is the one that needs the most care. A number in an email is not
automatically the value of an opportunity — "$3.50 a gallon" and "call 800-555
-0199" are not deals. We extract amounts, then require corroborating context
before any of it is allowed to become a financial impact estimate. When we can't
justify a number, the finding says VALUE UNKNOWN. Inventing revenue figures is
the fastest way to lose a business owner's trust permanently.
"""
import re

# ---------------------------------------------------------------- money
_MONEY_RE = re.compile(
    r"(?<![\w.])\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2})?)(?![\d.])"
    r"|(?<![\w$.])(\d{1,3}(?:,\d{3})+(?:\.\d{2})?)\s?(?:dollars|usd)\b", re.I)

_MONEY_CONTEXT = re.compile(
    r"\b(quote|quoted|estimate|estimated|price|pricing|priced|total|invoice|"
    r"invoiced|balance|deposit|down payment|payment|proposal|offer|bid|cost|"
    r"budget|out the door|otd|financing|finance|monthly|per month|refund|"
    r"credit|owe|owed|due|outstanding|past due|contract|agreement)\b", re.I)

# Contexts where a dollar figure is explicitly NOT the deal value.
_MONEY_EXCLUDE = re.compile(
    r"\b(per gallon|per hour|hourly|tip|shipping|tax|fee only|late fee|"
    r"gift card|coupon|discount of|save \$|off your)\b", re.I)


def money_amounts(text):
    """Dollar amounts in `text`, largest first, as cents."""
    if not text:
        return []
    out = []
    for m in _MONEY_RE.finditer(text):
        raw = m.group(1) or m.group(2) or ""
        try:
            cents = int(round(float(raw.replace(",", "")) * 100))
        except ValueError:
            continue
        if cents <= 0:
            continue
        out.append({"cents": cents, "text": m.group(0).strip(),
                    "context": _around(text, m.start(), m.end())})
    out.sort(key=lambda d: -d["cents"])
    return out


def _around(text, start, end, pad=70):
    return re.sub(r"\s+", " ", text[max(0, start - pad):min(len(text), end + pad)]).strip()


def deal_value(text):
    """The amount in `text` that plausibly represents a deal, or None.

    Requires the number to sit near deal language and to clear a floor that rules
    out incidental figures. Returns None rather than guessing — a finding that
    says VALUE UNKNOWN is honest; one that says $3.50 is embarrassing.
    """
    for amt in money_amounts(text):
        ctx = amt["context"]
        if _MONEY_EXCLUDE.search(ctx):
            continue
        if amt["cents"] < 10000:            # under $100: almost never the deal
            continue
        if _MONEY_CONTEXT.search(ctx):
            return {"cents": amt["cents"], "text": amt["text"], "context": ctx,
                    "basis": "amount stated in the conversation"}
    return None


# ---------------------------------------------------------------- complaints
_COMPLAINT = [
    (re.compile(r"\b(cancel(l)?ing|cancel my (order|account|contract)|"
                r"take my business elsewhere|going with someone else|"
                r"want a refund|demand a refund|refund my|dispute the charge|"
                r"charge ?back|report(ing)? (you|this) to|better business bureau|"
                r"bbb|attorney|lawyer|legal action|sue)\b", re.I), 0.9, "escalation"),
    (re.compile(r"\b(unacceptable|ridiculous|appalling|disgusted|furious|outrageous|"
                r"worst (experience|service)|never again|complete(ly)? unprofessional|"
                r"fed up|had enough)\b", re.I), 0.85, "strong dissatisfaction"),
    (re.compile(r"\b(still (haven'?t|have not|no) (heard|received|gotten)|"
                r"no one (has )?(called|responded|replied|gotten back)|"
                r"nobody (has )?(called|responded|replied)|"
                r"(third|3rd|fourth|4th|several) time (i'?ve|i have|we'?ve)|"
                r"i'?ve (called|emailed|written) (you )?(twice|three times|multiple times|"
                r"several times)|as i mentioned (before|previously)|"
                r"following up again|checking in again|any update)\b", re.I),
     0.75, "repeated unanswered contact"),
    (re.compile(r"\b(very disappointed|extremely disappointed|not happy|unhappy with|"
                r"frustrated|frustrating|upset about|poor service|bad experience|"
                r"let down|this is a problem|not what (i|we) (was|were) told)\b", re.I),
     0.7, "dissatisfaction"),
    (re.compile(r"\b(broken|defective|doesn'?t work|not working|stopped working|"
                r"damaged|wrong (item|part|order|vehicle)|missing (parts?|items?)|"
                r"leak(ing|s)?|failed again)\b", re.I), 0.55, "reported service failure"),
]

_COMPLAINT_EXCLUDE = re.compile(
    r"\b(no complaints|not a complaint|just checking|no rush|no worries|"
    r"take your time|not urgent|whenever you (get a chance|can))\b", re.I)


def complaint(text):
    """Strongest complaint signal in `text`, or None."""
    if not text or _COMPLAINT_EXCLUDE.search(text):
        return None
    best = None
    for rx, weight, kind in _COMPLAINT:
        m = rx.search(text)
        if m and (best is None or weight > best["confidence"]):
            best = {"confidence": weight, "kind": kind,
                    "quote": _around(text, m.start(), m.end(), 90)}
    return best


# ---------------------------------------------------------------- buying intent
_INTENT = [
    (re.compile(r"\b(ready to (buy|purchase|move forward|sign)|"
                r"send (me )?the (paperwork|contract|agreement)|"
                r"where do i sign|let'?s do it|i'?ll take it|"
                r"put a deposit|wire the (funds|money))\b", re.I), 0.95, "ready to buy"),
    (re.compile(r"\b(what'?s? (the|your) (best )?price|how much (is|for|would)|"
                r"can you (send|give) (me )?(a |an )?(quote|estimate|price|pricing)|"
                r"quote me|pricing on|cost to|what would it cost|ballpark)\b", re.I),
     0.85, "asked for pricing"),
    (re.compile(r"\b(is (it|this|that) (still )?available|do you (still )?have|"
                r"in stock|availability|can i (see|come by|come in|test drive|"
                r"schedule a (visit|viewing|showing|consultation)))\b", re.I),
     0.8, "asked about availability or a visit"),
    (re.compile(r"\b(financing|finance options|monthly payment|trade[- ]?in|"
                r"apr|lease options?|payment plan|pre[- ]?approv)\b", re.I),
     0.75, "asked about financing or trade-in"),
    (re.compile(r"\b(interested in|looking for|need a quote|request(ing)? (a )?quote|"
                r"shopping for|in the market for)\b", re.I), 0.6, "expressed interest"),
]


def buying_intent(text):
    """Strongest buying-intent signal in `text`, or None."""
    if not text:
        return None
    best = None
    for rx, weight, kind in _INTENT:
        m = rx.search(text)
        if m and (best is None or weight > best["confidence"]):
            best = {"confidence": weight, "kind": kind,
                    "quote": _around(text, m.start(), m.end(), 90)}
    return best


# ---------------------------------------------------------------- questions
_QUESTION_WORDS = re.compile(
    r"\b(can you|could you|would you|will you|do you|does it|is it|are you|"
    r"when (can|will|would)|what (is|are|would|about)|how (much|long|many|do)|"
    r"where (is|can)|why (is|did)|any chance|any update|let me know|"
    r"please (send|advise|confirm|let me know|call|email))\b", re.I)


def asks_something(text):
    """Does this message put the ball in our court?

    A question, or an explicit request, is what makes silence a failure rather
    than a normal end to a conversation. "Thanks, got it." needs no reply;
    "When can you come out?" does.
    """
    if not text:
        return False
    if "?" in text:
        return True
    return bool(_QUESTION_WORDS.search(text))


# ---------------------------------------------------------------- closers
_CLOSED = re.compile(
    r"\b(thanks?(,| )(again|so much|a lot)?!?$|thank you!?$|got it,? thanks|"
    r"perfect,? thanks|sounds good|no further questions|all set|we'?re good|"
    r"received,? thank|appreciate it|that works|great,? thanks|"
    r"no longer (interested|needed)|we (went|decided to go) (with|another)|"
    r"already (bought|purchased|found) )", re.I)


def looks_closed(text):
    """A message that ends a thread cleanly — nothing is owed after it."""
    if not text:
        return False
    tail = re.sub(r"\s+", " ", text).strip()[-120:]
    return bool(_CLOSED.search(tail))


_OPT_OUT = re.compile(
    r"\b(unsubscribe|stop emailing|remove me from|take me off (your|the) list|"
    r"do not contact|don'?t contact me|opt me out|stop contacting)\b", re.I)


def opted_out(text):
    """Explicit do-not-contact. A hard stop on any outbound recommendation."""
    return bool(text and _OPT_OUT.search(text))
