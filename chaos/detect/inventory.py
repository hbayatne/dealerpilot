"""
Inventory findings — the money dimension, from the DMS.

Until a cost column arrives, Chaos Control can see that a customer was ignored
but not what it cost. Inventory changes that: acquisition cost, recon and
flooring are the only numbers in this product that come from a system of record
rather than being read out of prose, so they are the one place we can state a
dollar figure without hedging.

Two rules carried over from every other detector:

* **Nothing is invented.** A unit with no cost column produces a finding that
  says the margin is unknown, never an estimate. `impact_cents` is set only from
  a figure the DMS actually exported.
* **Aggregate where the aggregate is the point.** Fourteen separate "this car is
  old" findings is a list a dealer already has. One finding that says
  *$214,000 of your cash is sitting in units past 90 days, and here are the six
  worst* is information they can act on this morning.

Thresholds are the ones a dealer would recognise, and they are conservative:
a 60-day unit is aging, a 90-day unit is a problem.
"""
import datetime
import hashlib

from chaos import db
from chaos.detect import base

AGED_WARN_DAYS = 60
AGED_CRITICAL_DAYS = 90
THIN_MARGIN_PCT = 8.0
RECON_STALL_DAYS = 21
# Below this, a lot isn't big enough for an aggregate to mean anything.
MIN_AGED_UNITS = 2


def _key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _days_in_stock(v, today):
    d = v.get("date_in_stock")
    if not d:
        return None
    try:
        return (today - datetime.date.fromisoformat(str(d)[:10])).days
    except Exception:
        return None


def _label(v):
    parts = [str(v.get("year") or "").strip(), v.get("make"), v.get("model"), v.get("trim")]
    name = " ".join(p for p in parts if p).strip()
    return name or v.get("vin") or v.get("stock_no") or "this unit"


def _unit_ref(v):
    bits = [b for b in (v.get("stock_no") and f"stock {v['stock_no']}",
                        v.get("vin") and f"VIN {v['vin'][-8:]}") if b]
    return " · ".join(bits)


def margin_pct(v):
    """Gross margin percent, or None when either side is missing."""
    price, cost = v.get("price_cents"), v.get("cost_cents")
    if not price or cost is None:
        return None
    return round(100.0 * (price - cost) / price, 1)


# ---------------------------------------------------------------- rules
def aged_capital(org, vehicles, now_iso, today):
    """Cash sitting on the lot past 90 days.

    One finding for the whole lot, because the dealer's decision is about the
    lot. The per-unit detail rides along as evidence, worst first.
    """
    aged = []
    for v in vehicles:
        if v.get("status") == "sold":
            continue
        d = _days_in_stock(v, today)
        if d is not None and d >= AGED_CRITICAL_DAYS:
            aged.append((d, v))
    if len(aged) < MIN_AGED_UNITS:
        return None
    aged.sort(key=lambda p: -p[0])

    costed = [v for _d, v in aged if v.get("cost_cents") is not None]
    tied_up = sum(v["cost_cents"] for v in costed)
    flooring = sum(v.get("flooring_cents") or 0 for _d, v in aged)
    unknown = len(aged) - len(costed)

    ev = []
    for d, v in aged[:8]:
        cost = v.get("cost_cents")
        ev.append(base.evidence(
            v.get("date_in_stock"), f"{_label(v)} — {d} days in stock",
            (f"{base.money(cost)} of cost carried" if cost is not None
             else "no cost recorded in the export, so its capital is not counted here")
            + (f" · {_unit_ref(v)}" if _unit_ref(v) else ""),
            "vehicle", v["id"]))
    if unknown:
        ev.append(base.evidence(
            now_iso, "Not all units could be counted",
            f"{unknown} aged unit{'s' if unknown != 1 else ''} had no cost in the export, "
            f"so the figure above is a floor, not a total."))
    if flooring:
        ev.append(base.evidence(
            now_iso, "Flooring still accruing",
            f"{base.money(flooring)} of flooring cost is recorded against these units."))

    summary = (f"{len(aged)} units have been in stock more than {AGED_CRITICAL_DAYS} days"
               + (f", carrying {base.money(tied_up)} of cost" if costed else "")
               + ". The oldest is "
               + f"{aged[0][0]} days old.")
    f, _ = base.finding(
        _key("aged_capital", org["id"], today.isoformat()),
        "financial",
        (f"{base.money(tied_up)} tied up in aged inventory" if costed
         else f"{len(aged)} units aged past {AGED_CRITICAL_DAYS} days"),
        subcategory="aged_capital",
        summary=summary,
        severity="high" if len(aged) >= 5 else "medium",
        confidence=0.95,                      # counted from the DMS, not inferred
        urgency=min(0.8, 0.4 + len(aged) / 25.0),
        impact_cents=tied_up or None,
        impact_basis=("acquisition and recon cost as exported by DealerCenter"
                      if costed else None),
        source_systems=["dealercenter"],
        recommended_action="Review the oldest units for a price move or wholesale.",
        ai_actionable=False, approval_required=True, risk="medium",
        detector="aged_capital", detected_at=now_iso, evidence=ev)
    return f, ev


def negative_margin(org, vehicles, now_iso, today):
    """Units priced at or below what they cost."""
    out = []
    for v in vehicles:
        if v.get("status") == "sold":
            continue
        m = margin_pct(v)
        if m is None or m >= 0:
            continue
        loss = v["cost_cents"] - v["price_cents"]
        d = _days_in_stock(v, today)
        ev = [
            base.evidence(v.get("date_in_stock"), f"{_label(v)}",
                          f"Priced at {base.money(v['price_cents'])}, cost "
                          f"{base.money(v['cost_cents'])}"
                          + (f" · {_unit_ref(v)}" if _unit_ref(v) else ""),
                          "vehicle", v["id"]),
            base.evidence(now_iso, "Margin",
                          f"{m}% — a sale at the advertised price loses "
                          f"{base.money(loss)} before any pack or commission."),
        ]
        if d is not None:
            ev.append(base.evidence(now_iso, "Age", f"{d} days in stock."))
        f, _ = base.finding(
            _key("neg_margin", org["id"], v["id"]),
            "financial",
            f"{_label(v)} is priced below cost",
            subcategory="negative_margin",
            summary=(f"Advertised at {base.money(v['price_cents'])} against "
                     f"{base.money(v['cost_cents'])} of cost — {m}% gross."),
            severity="high", confidence=0.95,
            urgency=0.6,
            impact_cents=loss,
            impact_basis="advertised price minus cost as exported by DealerCenter",
            source_systems=["dealercenter"],
            recommended_action="Check whether this is a deliberate loss-leader or a pricing error.",
            ai_actionable=False, approval_required=True, risk="medium",
            detector="negative_margin", detected_at=now_iso, evidence=ev)
        out.append((f, ev))
    return out


def unsellable_units(org, vehicles, now_iso, today):
    """Units that cannot be sold online as listed — no price, or no photos.

    Aggregated: the dealer fixes these as a batch in the DMS, not one at a time.
    """
    unpriced = [v for v in vehicles
                if v.get("status") == "frontline" and not v.get("price_cents")]
    photoless = [v for v in vehicles
                 if v.get("status") == "frontline" and not v.get("photo_count")]
    if not unpriced and not photoless:
        return None
    blocked = {v["id"]: v for v in unpriced + photoless}
    at_risk = sum(v.get("cost_cents") or 0 for v in blocked.values())

    ev = []
    if unpriced:
        ev.append(base.evidence(
            now_iso, f"{len(unpriced)} frontline units with no price",
            ", ".join(_label(v) for v in unpriced[:6])
            + (" …" if len(unpriced) > 6 else "")))
    if photoless:
        ev.append(base.evidence(
            now_iso, f"{len(photoless)} frontline units with no photos",
            ", ".join(_label(v) for v in photoless[:6])
            + (" …" if len(photoless) > 6 else "")))
    ev.append(base.evidence(
        now_iso, "Why it matters",
        "A shopper filtering by price never sees an unpriced unit, and almost "
        "nobody clicks a listing with no photo. These are on the lot but not "
        "in the market."))

    f, _ = base.finding(
        _key("unsellable", org["id"], today.isoformat()),
        "revenue",
        f"{len(blocked)} frontline units can't be shopped online",
        subcategory="unsellable",
        summary=(f"{len(unpriced)} ha{'ve' if len(unpriced) != 1 else 's'} no price and "
                 f"{len(photoless)} ha{'ve' if len(photoless) != 1 else 's'} no photos"
                 + (f", against {base.money(at_risk)} of cost carried" if at_risk else "")
                 + "."),
        severity="high" if len(blocked) >= 5 else "medium",
        confidence=0.9,
        urgency=0.55,
        impact_cents=at_risk or None,
        impact_basis=("cost carried on units that are not shoppable"
                      if at_risk else None),
        source_systems=["dealercenter"],
        recommended_action="Set prices and add photos in DealerCenter for these units.",
        ai_actionable=False, approval_required=True, risk="low",
        detector="unsellable_units", detected_at=now_iso, evidence=ev)
    return f, ev


def recon_stall(org, vehicles, now_iso, today):
    """Units that arrived weeks ago and still aren't frontline."""
    stalled = []
    for v in vehicles:
        if v.get("status") != "recon":
            continue
        d = _days_in_stock(v, today)
        if d is not None and d >= RECON_STALL_DAYS:
            stalled.append((d, v))
    if not stalled:
        return None
    stalled.sort(key=lambda p: -p[0])
    tied = sum(v.get("cost_cents") or 0 for _d, v in stalled)

    ev = [base.evidence(v.get("date_in_stock"),
                        f"{_label(v)} — {d} days since arrival, still in recon",
                        (f"{base.money(v['cost_cents'])} of cost"
                         if v.get("cost_cents") is not None else "no cost recorded")
                        + (f" · {_unit_ref(v)}" if _unit_ref(v) else ""),
                        "vehicle", v["id"])
          for d, v in stalled[:8]]
    ev.append(base.evidence(now_iso, "Why it matters",
                            "A unit in recon is capital that cannot be sold. Every day "
                            "there is a day it is not on the front line earning."))

    f, _ = base.finding(
        _key("recon_stall", org["id"], today.isoformat()),
        "financial",
        f"{len(stalled)} unit{'s' if len(stalled) != 1 else ''} stuck in recon",
        subcategory="recon_stall",
        summary=(f"{len(stalled)} unit{'s' if len(stalled) != 1 else ''} arrived more than "
                 f"{RECON_STALL_DAYS} days ago and "
                 f"{'are' if len(stalled) != 1 else 'is'} still not frontline"
                 + (f", holding {base.money(tied)}" if tied else "") + "."),
        severity="medium", confidence=0.9,
        urgency=0.5,
        impact_cents=tied or None,
        impact_basis="cost of units not yet available to sell" if tied else None,
        source_systems=["dealercenter"],
        recommended_action="Find out what each unit is waiting on — parts, a bay, or a title.",
        ai_actionable=False, approval_required=True, risk="low",
        detector="recon_stall", detected_at=now_iso, evidence=ev)
    return f, ev


def missing_cost_data(org, vehicles, now_iso, today):
    """We were given inventory but not the money. Say so rather than staying quiet.

    A dealer looking at a financial dashboard that silently omits half the lot is
    being misled by omission. This finding is the honest alternative to guessing.
    """
    active = [v for v in vehicles if v.get("status") != "sold"]
    if not active:
        return None
    missing = [v for v in active if v.get("cost_cents") is None]
    if not missing or len(missing) < max(2, len(active) * 0.15):
        return None
    ev = [
        base.evidence(now_iso, f"{len(missing)} of {len(active)} active units have no cost",
                      ", ".join(_label(v) for v in missing[:6])
                      + (" …" if len(missing) > 6 else "")),
        base.evidence(now_iso, "What this blocks",
                      "Margin, capital tied up and money-at-risk are all computed from "
                      "cost. Anything we show you about this lot's money is a floor "
                      "until these are filled in."),
    ]
    f, _ = base.finding(
        _key("missing_cost", org["id"], today.isoformat()),
        "data",
        f"{len(missing)} units have no cost in the DealerCenter export",
        subcategory="missing_cost",
        summary=(f"We can't compute margin or capital for {len(missing)} of "
                 f"{len(active)} active units, so every money figure for this lot "
                 f"is understated."),
        severity="medium", confidence=1.0, urgency=0.45,
        impact_cents=None,
        impact_basis=None,
        source_systems=["dealercenter"],
        recommended_action="Include the cost column in the export, or fill it in for these units.",
        ai_actionable=False, approval_required=True, risk="low",
        detector="missing_cost_data", detected_at=now_iso, evidence=ev)
    return f, ev


RULES = [aged_capital, negative_margin, unsellable_units, recon_stall, missing_cost_data]


def run(org, now_iso=None, today=None):
    """Every inventory finding the lot currently supports."""
    now_iso = now_iso or db.now()
    today = today or datetime.date.fromisoformat(now_iso[:10])
    vehicles = db.vehicles(org["id"])
    if not vehicles:
        return []
    out = []
    for rule in RULES:
        try:
            res = rule(org, vehicles, now_iso, today)
        except Exception:
            continue
        if not res:
            continue
        out.extend(res if isinstance(res, list) else [res])
    return out
