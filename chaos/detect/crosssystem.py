"""
Cross-system findings — where the mailbox and the DMS disagree.

This is the part no single system can do. DealerCenter knows a unit has sat for
140 days and what it cost. The mailbox knows somebody asked about that exact car
nine days ago and nobody answered. Neither system knows the other, so nobody in
the building has ever seen those two facts side by side:

    "$18,900 is sitting in a 2018 Macan that's 140 days old — and Marcus Webb
     emailed about that car nine days ago. Nobody replied."

Matching a conversation to a unit is where this can go wrong, so it is
deliberately strict and every match carries the evidence that produced it:

* **VIN** — exact, unambiguous, high confidence.
* **Stock number** — exact, but only when it's long enough not to collide with
  an ordinary number in a sentence.
* **Year + make + model** — a real signal, but "2018 Porsche" alone is not; we
  require the model too, and we only ever match units still on the lot.

A wrong match here would put a customer's name against the wrong car in front of
a salesperson, so when in doubt this module matches nothing.
"""
import hashlib
import re

from chaos import db
from chaos.detect import base, inventory as inv, signals as S

# Only look at conversations this recent — an email about a car from last year
# tells you nothing about today's lot.
LOOKBACK_DAYS = 120
# A stock number shorter than this collides with ordinary numbers in prose.
MIN_STOCK_LEN = 4
# One working day. Lower than the generic unanswered-email threshold on purpose:
# this rule has already established that the person named a specific unit we own
# and asked a question about it. That is an in-market buyer, not correspondence —
# a dealer who lets one sit a full working day is usually losing the deal to
# whoever answered first.
UNANSWERED_HOURS = 8

_VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b", re.I)


def _key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def match_vehicle(text, subject, vehicles_by_vin, vehicles_by_stock, vehicles):
    """Which unit is this message about? Returns (vehicle, how, quote) or None."""
    blob = f"{subject or ''}\n{text or ''}"
    low = _norm(blob)

    for m in _VIN_RE.finditer(blob):
        vin = m.group(1).upper()
        v = vehicles_by_vin.get(vin)
        if v:
            return v, "VIN quoted in the message", m.group(1)

    for stock, v in vehicles_by_stock.items():
        if len(stock) < MIN_STOCK_LEN:
            continue
        if re.search(rf"\b{re.escape(stock.lower())}\b", low):
            return v, "stock number quoted in the message", stock

    # Year + make + model. All three, in the same message, and only for units
    # still on the lot — two of the three is how you match the wrong car.
    for v in vehicles:
        year, make, model = v.get("year"), _norm(v.get("make")), _norm(v.get("model"))
        if not (year and make and model):
            continue
        model_head = model.split()[0] if model else ""
        if len(model_head) < 3:
            continue
        if (str(year) in low and make in low and model_head in low):
            return v, "year, make and model named in the message", \
                f"{year} {v.get('make')} {v.get('model')}"
    return None


def _days_in_stock(v, today):
    return inv._days_in_stock(v, today)


def unanswered_lead_on_unit(org, now_iso, today):
    """Someone asked about a car that is still sitting on the lot, and nobody replied.

    The single most expensive gap a dealership has, and structurally invisible:
    the DMS shows an aging unit with no idea a buyer exists, and the mailbox
    shows an unanswered email with no idea what it is worth.
    """
    vehicles = [v for v in db.vehicles(org["id"]) if v.get("status") != "sold"]
    if not vehicles:
        return []
    by_vin = {v["vin"]: v for v in vehicles if v.get("vin")}
    by_stock = {v["stock_no"]: v for v in vehicles if v.get("stock_no")}

    out = []
    for conv in db.conversations(org["id"], limit=2000):
        msgs = [m for m in db.messages_in(org["id"], conv["id"]) if not m.get("automated")]
        if not msgs:
            continue
        inbound = [m for m in msgs if m["direction"] == "in"]
        outbound = [m for m in msgs if m["direction"] == "out"]
        if not inbound:
            continue
        last = msgs[-1]
        if base.days_between(last["sent_at"], now_iso) > LOOKBACK_DAYS:
            continue

        # Which unit is this thread about?
        hit = None
        for m in inbound:
            hit = match_vehicle(m.get("body"), m.get("subject"), by_vin, by_stock, vehicles)
            if hit:
                break
        if not hit:
            continue
        vehicle, how, quote = hit

        # Is anyone actually waiting? Same test the mailbox detectors use, so
        # this never contradicts them.
        if last["direction"] != "in":
            continue
        body = last.get("body") or ""
        if not S.asks_something(body) or S.looks_closed(body):
            continue
        if any(S.opted_out(m.get("body") or "") for m in inbound):
            continue
        waited = base.business_hours_between(last["sent_at"], now_iso)
        if waited < UNANSWERED_HOURS:
            continue

        days = _days_in_stock(vehicle, today)
        cost = vehicle.get("cost_cents")
        price = vehicle.get("price_cents")
        name = None
        if conv.get("entity_id"):
            e = db.get_entity(org["id"], conv["entity_id"])
            name = e["display_name"] if e else None
        name = name or last.get("from_addr") or "a customer"
        label = inv._label(vehicle)

        ev = [base.message_evidence(m) for m in msgs[-4:]]
        ev.append(base.evidence(
            last["sent_at"], f"Matched to {label}", f"{how}: “{quote}”",
            "vehicle", vehicle["id"]))
        ev.append(base.evidence(
            vehicle.get("date_in_stock"), "That unit is still on the lot",
            (f"{days} days in stock" if days is not None else "in stock")
            + (f", {base.money(cost)} of cost carried" if cost is not None else "")
            + (f", advertised at {base.money(price)}" if price else "")))
        ev.append(base.evidence(
            now_iso, "No reply detected",
            f"No outbound email to this contact in the {base.humanize_hours(waited)} "
            f"since they asked."))

        # The value at stake is the advertised price of a unit we still own and
        # a buyer who asked about it. That is an observed number on both sides.
        f, _ = base.finding(
            _key("lead_on_unit", org["id"], conv["id"], vehicle["id"]),
            "revenue",
            f"{name} asked about a {label} you still have — and got no reply",
            subcategory="unanswered_lead_on_unit",
            summary=(f"{name} asked about {label}"
                     + (f", which has been in stock {days} days" if days is not None else "")
                     + (f" carrying {base.money(cost)} of cost" if cost is not None else "")
                     + f". Nobody has replied in {base.humanize_hours(waited)}."),
            severity="critical" if (days or 0) >= inv.AGED_CRITICAL_DAYS else "high",
            confidence=0.9 if how.startswith("VIN") else 0.78,
            urgency=min(1.0, 0.7 + waited / 200.0),
            impact_cents=price,
            impact_basis=("advertised price of the unit they asked about, as exported "
                          "by DealerCenter") if price else None,
            entity_id=conv.get("entity_id"),
            owner=(outbound[-1].get("from_addr") if outbound else None),
            source_systems=["email", "dealercenter"],
            recommended_action=f"Reply to {name} about the {label} today.",
            ai_actionable=True, approval_required=True, risk="low",
            detector="unanswered_lead_on_unit", detected_at=now_iso, evidence=ev)
        # Tagged so the orchestrator folds this together with any mailbox finding
        # on the same thread — one situation, one row in the feed.
        f["_conversation_id"] = conv["id"]
        out.append((f, ev))
    return out


def interest_in_aged_stock(org, now_iso, today):
    """Aged units people are still asking about — the ones worth pricing, not wholesaling.

    The useful inverse of the aging report: a dealer deciding what to do with
    old stock normally can't tell which units are dead and which simply keep
    being asked about at the wrong price.
    """
    vehicles = [v for v in db.vehicles(org["id"]) if v.get("status") != "sold"]
    aged = {v["id"]: v for v in vehicles
            if (_days_in_stock(v, today) or 0) >= inv.AGED_WARN_DAYS}
    if not aged:
        return None
    by_vin = {v["vin"]: v for v in vehicles if v.get("vin")}
    by_stock = {v["stock_no"]: v for v in vehicles if v.get("stock_no")}

    interest = {}
    for conv in db.conversations(org["id"], limit=2000):
        msgs = [m for m in db.messages_in(org["id"], conv["id"]) if not m.get("automated")]
        ins = [m for m in msgs if m["direction"] == "in"]
        if not ins:
            continue
        if base.days_between(msgs[-1]["sent_at"], now_iso) > LOOKBACK_DAYS:
            continue
        for m in ins:
            hit = match_vehicle(m.get("body"), m.get("subject"), by_vin, by_stock, vehicles)
            if hit and hit[0]["id"] in aged:
                interest.setdefault(hit[0]["id"], []).append(conv)
                break

    if not interest:
        return None
    rows = sorted(interest.items(), key=lambda kv: -len(kv[1]))
    total = sum(len(v) for v in interest.values())

    ev = []
    for vid, convs in rows[:6]:
        v = aged[vid]
        d = _days_in_stock(v, today)
        ev.append(base.evidence(
            v.get("date_in_stock"),
            f"{inv._label(v)} — {d} days in stock, {len(convs)} enquir"
            f"{'ies' if len(convs) != 1 else 'y'}",
            (f"advertised at {base.money(v['price_cents'])}" if v.get("price_cents")
             else "no price set")
            + (f", cost {base.money(v['cost_cents'])}" if v.get("cost_cents") is not None
               else ""),
            "vehicle", vid))
    ev.append(base.evidence(
        now_iso, "Why this is worth knowing",
        "These units are aging but people are still asking about them. That is "
        "usually a pricing or follow-up problem rather than a unit nobody wants."))

    f, _ = base.finding(
        _key("interest_aged", org["id"], today.isoformat()),
        "revenue",
        f"{len(interest)} aged units are still getting enquiries",
        subcategory="interest_in_aged_stock",
        summary=(f"{total} enquir{'ies' if total != 1 else 'y'} across {len(interest)} "
                 f"units that have been in stock over {inv.AGED_WARN_DAYS} days. "
                 f"There is demand at the wrong price, not no demand."),
        severity="medium", confidence=0.75, urgency=0.5,
        impact_cents=None, impact_basis=None,
        source_systems=["email", "dealercenter"],
        recommended_action="Re-price these before wholesaling them.",
        ai_actionable=False, approval_required=True, risk="low",
        detector="interest_in_aged_stock", detected_at=now_iso, evidence=ev)
    return f, ev


RULES = [unanswered_lead_on_unit, interest_in_aged_stock]


def run(org, now_iso=None, today=None):
    import datetime
    now_iso = now_iso or db.now()
    today = today or datetime.date.fromisoformat(now_iso[:10])
    out = []
    for rule in RULES:
        try:
            res = rule(org, now_iso, today)
        except Exception:
            continue
        if not res:
            continue
        out.extend(res if isinstance(res, list) else [res])
    return out
