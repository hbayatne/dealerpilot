"""
Commitment Engine — finding the promises a business made and didn't keep.

"I'll call you Friday." "Let me check and get back to you." "We'll send that
today." These are the sentences a business gets judged on, and they live nowhere
except inside a mailbox. No CRM records them. Nobody is tracking them.

Detection is rule-based, not model-based, for three reasons that matter more than
sophistication: it can be unit-tested, it costs nothing per message, and — most
importantly — it can *show its work*. Every commitment we report carries the
exact sentence it came from, so a human can see in one second whether we read it
right. A model that is right 90% of the time but cannot be checked is worse here
than a rule that is right 80% of the time and shows the quote.

The hard part is not finding promises; it is **not** finding things that only
look like promises. The guards below (offers, conditionals, negations, past
tense, pleasantries) exist because each one produced a false positive in testing.
"""
import re

from chaos.detect import timeref

# ---------------------------------------------------------------- the promise
# First person, future tense, concrete action. "I'll" / "we'll" / "I will" /
# "let me ... and I'll" — plus the standing idiom "let me check and get back
# to you", which is a promise even though it starts as an imperative.
_SUBJECT = r"(?:i|we|someone|somebody|our team|the team|my (?:team|assistant|office)|accounting|dispatch|service)"
_MODAL = r"(?:'ll|\s+will|\s+am going to|\s+are going to|\s+can|\s+shall|\s+should be able to)"

_ACTION_VERBS = (
    r"call|phone|ring|reach out|follow up|circle back|touch base|"
    r"get back to (?:you|him|her|them|the (?:customer|client|owner))|"
    r"send|email|forward|share|provide|deliver|drop off|ship|mail|"
    r"get (?:you|that|it|those|them)|pull|prepare|put together|draw up|draft|write up|"
    r"check|look into|confirm|verify|find out|figure out|review|"
    r"quote|price|estimate|invoice|bill|refund|credit|issue|process|"
    r"schedule|book|set up|arrange|order|fix|repair|replace|update|let you know|"
    # Showing up is a commitment too, and a broken one is the most visible kind.
    r"come by|come out|stop by|swing by|be (?:out|there|by)|get (?:out|over) there|"
    r"head (?:out|over)|drop by|bring|meet you|see you"
)

_PROMISE_RES = [
    re.compile(rf"\b{_SUBJECT}{_MODAL}\s+(?:{_ACTION_VERBS})\b[^.!?\n]*", re.I),
    re.compile(r"\blet me\s+(?:check|look|see|confirm|find out|dig)\b[^.!?\n]*?"
               r"(?:and\s+)?(?:i'?ll|get back|let you know|revert)\b[^.!?\n]*", re.I),
    re.compile(r"\b(?:you'?ll|you will)\s+(?:have|receive|get)\b[^.!?\n]*", re.I),
    re.compile(r"\b(?:we're|we are|i'?m)\s+(?:going to|about to)\s+"
               rf"(?:{_ACTION_VERBS})\b[^.!?\n]*", re.I),
    re.compile(r"\b(?:will|shall)\s+be\s+(?:sent|delivered|ready|issued|processed|refunded)"
               r"\b[^.!?\n]*", re.I),
    # Delegation: the promise is still ours even when someone else does the work.
    # "I'll have accounting refund it", "I'll get someone to call you",
    # "I'll make sure that goes out today."
    re.compile(rf"\b{_SUBJECT}{_MODAL}\s+(?:make sure\b|"
               rf"(?:have|get|ask|tell)\s+(?!to\b|back\b)\w+\s+(?:to\s+)?\w+)"
               r"[^.!?\n]*", re.I),
]

# ---------------------------------------------------------------- the guards
# An *offer* hands the next move to the customer. "Let me know if you'd like me
# to call" is not a commitment to call — treating it as one blames someone for
# a decision the customer never made.
_OFFER = re.compile(
    r"\b(?:if you(?:'d| would)? (?:like|want|prefer)|if you're interested|"
    r"let me know if|just let me know|happy to|glad to|i can also|"
    r"would you like|do you want (?:me )?to|should i|if needed|if that works|"
    r"feel free to|whenever you're ready|if you decide)\b", re.I)

_CONDITIONAL = re.compile(
    r"\b(?:if|once|as soon as|when|after|unless|provided|assuming|pending|"
    r"depending on)\b\s+(?:you|we|they|it|the|i)\b", re.I)

_NEGATION = re.compile(
    r"\b(?:won'?t|will not|can'?t|cannot|unable to|not able to|no longer|"
    r"don'?t think (?:i|we)|isn'?t possible|not going to)\b", re.I)

_PAST = re.compile(
    r"\b(?:i|we)\s+(?:already\s+)?(?:called|sent|emailed|forwarded|shared|"
    r"provided|checked|confirmed|quoted|scheduled|booked|left you|reached out|"
    r"followed up|got back|dropped off|mailed|issued|processed)\b", re.I)

# Turns of phrase that use "I'll" without promising anything at all.
_PLEASANTRY = re.compile(
    r"\b(?:i'?ll be honest|i'?ll say|i'?ll admit|i'?ll bet|i'?ll tell you what|"
    r"we'?ll see|i'?ll leave (?:it|that) (?:to|with) you|we'?ll miss|"
    r"i'?ll keep that in mind|i'?ll be there|we'?ll be closed|i'?ll be out|"
    r"i'?ll have to|we'?ll have to|i'?ll need to think|"
    r"we'?ll be in touch soon\?|i'?ll take a look when)\b", re.I)

_QUESTION_TAIL = re.compile(r"\?\s*$")

# Signals that raise or lower how sure we are, and why.
_STRONG_ACTION = re.compile(
    r"\b(call|send|email|refund|quote|estimate|invoice|schedule|deliver|ship)\b", re.I)
_HEDGE = re.compile(r"\b(try to|hopefully|probably|might|may|aim to|do my best|"
                    r"attempt to|see if (?:i|we) can)\b", re.I)


def _sentences(text):
    """Split into sentences, keeping it simple — mail is not literature."""
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _reject(sentence):
    """Why this sentence is not a commitment, or None when it is one."""
    if _NEGATION.search(sentence):
        return "negated"
    if _PLEASANTRY.search(sentence):
        return "figure of speech"
    if _OFFER.search(sentence):
        return "an offer, not a commitment"
    if _PAST.search(sentence) and not re.search(r"\b(?:i'?ll|we'?ll|i will|we will)\b",
                                                sentence, re.I):
        return "describes something already done"
    if _QUESTION_TAIL.search(sentence):
        return "phrased as a question"
    if _CONDITIONAL.search(sentence) and not re.search(
            r"\b(?:i'?ll|we'?ll|i will|we will)\b[^,]{0,40}$", sentence, re.I):
        return "conditional on something else happening"
    return None


def extract(text, sent_at=None):
    """Commitments stated in `text`.

    Each is {quote, action, due_at, due_basis, due_phrase, confidence}. `due_at`
    is None when the sentence names no deadline — an open commitment, which we
    still track but never call overdue.
    """
    out, seen = [], set()
    for sentence in _sentences(text):
        if len(sentence) > 400:
            continue
        if _reject(sentence):
            continue
        for rx in _PROMISE_RES:
            m = rx.search(sentence)
            if not m:
                continue
            quote = re.sub(r"\s+", " ", sentence).strip()[:300]
            if quote.lower() in seen:
                break
            seen.add(quote.lower())

            when = timeref.extract(quote, sent_at) if sent_at else None
            conf = 0.55
            if when:
                conf += 0.18 if when["basis"] in ("explicit date", "named weekday") else 0.10
            if _STRONG_ACTION.search(m.group(0)):
                conf += 0.12
            if _HEDGE.search(sentence):
                conf -= 0.18
            if re.search(r"\b(?:i'?ll|we'?ll|i will|we will)\b", sentence, re.I):
                conf += 0.08
            out.append({
                "quote": quote,
                "action": re.sub(r"\s+", " ", m.group(0)).strip()[:160],
                "due_at": when["due_at"] if when else None,
                "due_basis": when["basis"] if when else None,
                "due_phrase": when["phrase"] if when else None,
                "confidence": round(max(0.3, min(0.95, conf)), 2),
            })
            break
    return out
