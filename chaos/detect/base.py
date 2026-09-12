"""
Shared detector plumbing: the Finding shape, aging maths, and evidence helpers.

Two rules every detector obeys:

1. **No finding without evidence.** Each evidence row points at a stored record
   (a message id, a commitment id) and states a fact with a timestamp. We never
   generate a narrative and call it evidence.
2. **No invented money.** `impact_cents` is only set when an amount was actually
   observed. Otherwise the finding carries a value of None and the UI says
   VALUE UNKNOWN. A range is allowed when the method is stated.
"""
import datetime

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def parse_ts(value):
    if isinstance(value, datetime.datetime):
        return value
    try:
        return datetime.datetime.fromisoformat((value or "").replace("Z", ""))
    except Exception:
        return None


def business_hours_between(start, end):
    """Working hours between two timestamps, Mon-Fri 9-17.

    Response-time expectations have to respect the weekend. An email that lands
    at 6pm Friday and is answered 9am Monday was answered promptly; measured in
    wall-clock hours it looks like a 63-hour failure, and a product that says so
    is wrong in a way owners notice immediately.
    """
    s, e = parse_ts(start), parse_ts(end)
    if not s or not e or e <= s:
        return 0.0
    total, cur = 0.0, s
    while cur < e:
        day_end = cur.replace(hour=17, minute=0, second=0, microsecond=0)
        day_start = cur.replace(hour=9, minute=0, second=0, microsecond=0)
        if cur.weekday() < 5:
            window_start = max(cur, day_start)
            window_end = min(e, day_end)
            if window_end > window_start:
                total += (window_end - window_start).total_seconds() / 3600.0
        nxt = (cur + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                         microsecond=0)
        cur = nxt
    return round(total, 2)


def business_days_between(start, end):
    return round(business_hours_between(start, end) / 8.0, 2)


def days_between(start, end):
    s, e = parse_ts(start), parse_ts(end)
    if not s or not e:
        return 0.0
    return round((e - s).total_seconds() / 86400.0, 2)


def humanize_hours(h):
    if h is None:
        return "unknown"
    if h < 1:
        return f"{int(round(h * 60))} minutes"
    if h < 16:
        return f"{h:.0f} business hours" if h >= 2 else "about an hour"
    return f"{h / 8:.1f} business days"


def money(cents):
    if cents is None:
        return "value unknown"
    return "${:,.0f}".format(cents / 100.0)


def evidence(occurred_at, label, detail, ref_kind=None, ref_id=None):
    return {"occurred_at": occurred_at, "label": label, "detail": detail,
            "ref_kind": ref_kind, "ref_id": ref_id}


def message_evidence(msg, label=None):
    """One evidence row from a stored message — quoting what was actually said."""
    who = msg.get("from_name") or msg.get("from_addr") or "unknown"
    side = {"in": "Customer", "out": "Us", "internal": "Internal"}.get(
        msg.get("direction"), "Message")
    return evidence(msg.get("sent_at"), label or f"{side} — {who}",
                    (msg.get("snippet") or "")[:300], "message", msg.get("id"))


def finding(dedupe_key, category, title, **kw):
    """Assemble a finding. Callers pass evidence separately."""
    f = {
        "dedupe_key": dedupe_key,
        "category": category,
        "subcategory": kw.get("subcategory"),
        "title": title,
        "summary": kw.get("summary"),
        "severity": kw.get("severity", "medium"),
        "confidence": round(float(kw.get("confidence", 0.6)), 3),
        "impact_cents": kw.get("impact_cents"),
        "impact_basis": kw.get("impact_basis"),
        "impact_low_cents": kw.get("impact_low_cents"),
        "impact_high_cents": kw.get("impact_high_cents"),
        "urgency": round(float(kw.get("urgency", 0.5)), 3),
        "entity_id": kw.get("entity_id"),
        "owner": kw.get("owner"),
        "source_systems": kw.get("source_systems") or ["email"],
        "recommended_action": kw.get("recommended_action"),
        "ai_actionable": kw.get("ai_actionable", False),
        "approval_required": kw.get("approval_required", True),
        "risk": kw.get("risk", "low"),
        "detector": kw.get("detector"),
        "detected_at": kw.get("detected_at"),
    }
    return f, kw.get("evidence") or []
