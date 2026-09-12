"""
Turning "I'll call you Friday" into an actual date.

A commitment without a deadline cannot be overdue, and a deadline we get wrong
produces an accusation that is simply false. So this module is deliberately
conservative: when a phrase is ambiguous it returns a *later* due date rather
than an earlier one, because being early to nag is the error that destroys trust.

Every result carries the phrase it came from, so a finding can always show the
customer the words it read.
"""
import datetime
import re

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
            "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4,
            "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
_MONTHS.update({m[:3]: i + 1 for i, m in enumerate(list(_MONTHS))})

# Business-day horizon for vague phrases. Generous on purpose.
_VAGUE = {
    "shortly": 2, "soon": 3, "asap": 1, "right away": 1, "today": 0,
    "this afternoon": 0, "this morning": 0, "this evening": 0, "tonight": 0,
    "end of day": 0, "eod": 0, "close of business": 0, "cob": 0,
    "tomorrow": 1, "tomorrow morning": 1, "tomorrow afternoon": 1,
    "in the morning": 1, "first thing": 1, "next day": 1,
    "this week": 5, "end of the week": 5, "end of week": 5, "eow": 5,
    "next week": 10, "early next week": 8, "later this week": 4,
    "in a few days": 4, "in a couple of days": 3, "in a couple days": 3,
    "within the week": 6, "next month": 30, "in a week": 8,
    "in two weeks": 15, "in a month": 32,
}

_VAGUE_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in _VAGUE), key=len, reverse=True)) + r")\b",
    re.I)
_WEEKDAY_RE = re.compile(
    r"\b(?:on\s+|by\s+|this\s+|next\s+|come\s+)?(" + "|".join(WEEKDAYS) + r")\b", re.I)
_DATE_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.I)
_NUM_UNIT_RE = re.compile(
    r"\bin\s+(?:the\s+next\s+)?(\d{1,2}|a|an|two|three|four|five|couple(?:\s+of)?)\s+"
    r"(hour|day|business day|week|month)s?\b", re.I)
_WORD_NUM = {"a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "couple": 2, "couple of": 2}


def _parse(dt):
    if isinstance(dt, datetime.datetime):
        return dt
    try:
        return datetime.datetime.fromisoformat((dt or "").replace("Z", ""))
    except Exception:
        return None


def _end_of_day(dt):
    return dt.replace(hour=23, minute=59, second=0, microsecond=0)


def _add_business_days(dt, n):
    """Weekends aren't work days; a Friday 'tomorrow' means Monday."""
    d = dt
    step = 1 if n >= 0 else -1
    left = abs(int(n))
    while left > 0:
        d += datetime.timedelta(days=step)
        if d.weekday() < 5:
            left -= 1
    return d


def extract(text, sent_at):
    """First time reference in `text`, resolved against `sent_at`.

    Returns {"due_at": iso, "phrase": str, "basis": str} or None when the text
    names no deadline at all — in which case the caller must treat the commitment
    as open-ended rather than inventing one.
    """
    base = _parse(sent_at)
    if not base or not text:
        return None
    low = text.lower()

    m = _DATE_RE.search(low)
    if m:
        month, day = _MONTHS[m.group(1).lower()[:3]], int(m.group(2))
        year = base.year
        try:
            due = datetime.datetime(year, month, day, 23, 59)
            if due < base - datetime.timedelta(days=1):
                due = datetime.datetime(year + 1, month, day, 23, 59)
            return {"due_at": due.isoformat(timespec="seconds"),
                    "phrase": m.group(0), "basis": "explicit date"}
        except ValueError:
            pass

    m = _WEEKDAY_RE.search(low)
    if m:
        target = WEEKDAYS[m.group(1).lower()]
        ahead = (target - base.weekday()) % 7
        if ahead == 0:
            ahead = 7                      # "Friday" said on a Friday means next Friday
        if "next " in low[max(0, m.start() - 6):m.start() + 5] and ahead < 7:
            ahead += 7
        return {"due_at": _end_of_day(base + datetime.timedelta(days=ahead)).isoformat(
                    timespec="seconds"),
                "phrase": m.group(0).strip(), "basis": "named weekday"}

    m = _NUM_UNIT_RE.search(low)
    if m:
        raw_n, unit = m.group(1).lower(), m.group(2).lower()
        n = _WORD_NUM.get(raw_n, None)
        if n is None:
            try:
                n = int(raw_n)
            except ValueError:
                n = 1
        if unit == "hour":
            due = base + datetime.timedelta(hours=n)
        elif unit == "week":
            due = _end_of_day(base + datetime.timedelta(days=7 * n + 1))
        elif unit == "month":
            due = _end_of_day(base + datetime.timedelta(days=31 * n))
        else:
            due = _end_of_day(_add_business_days(base, n))
        return {"due_at": due.isoformat(timespec="seconds"),
                "phrase": m.group(0), "basis": "relative interval"}

    m = _VAGUE_RE.search(low)
    if m:
        days = _VAGUE[m.group(1).lower()]
        due = _end_of_day(base if days == 0 else _add_business_days(base, days))
        return {"due_at": due.isoformat(timespec="seconds"),
                "phrase": m.group(1), "basis": "approximate ('%s')" % m.group(1)}
    return None
