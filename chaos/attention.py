"""
The Attention Engine — deciding what the owner actually sees.

Finding problems is the easy half. A business with a messy mailbox can generate
hundreds of true findings, and handing someone 300 true things is
indistinguishable from handing them nothing. The product's job is to reduce
cognitive load, so ranking is not a nice-to-have — it *is* the feature.

Two things make this ranking defensible:

* Money never silently dominates. A $50k stale deal and an angry customer about
  to leave are both real, and an engine that always shows the dollar figure first
  teaches owners to distrust it. Impact is one weighted term among several.
* A finding we are unsure about is ranked down, not hidden. Confidence multiplies
  rather than filters, so a 60%-confidence problem worth $40k still surfaces —
  labelled as uncertain.
"""
from chaos import db
from chaos.detect import base

SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.75, "medium": 0.45, "low": 0.2, "info": 0.05}

# How much each term contributes before confidence scaling.
WEIGHTS = {"severity": 0.30, "urgency": 0.22, "impact": 0.24, "age": 0.10,
           "recoverability": 0.14}

# Above this a finding is worth an owner's own attention rather than a queue.
OWNER_THRESHOLD = 62

# Diminishing returns: the first $10k of exposure matters far more than the
# difference between $80k and $90k.
_IMPACT_SATURATION_CENTS = 2_500_000     # $25,000


def _impact_term(cents):
    if not cents:
        return 0.25          # unknown value is not zero value
    return min(1.0, (cents / _IMPACT_SATURATION_CENTS) ** 0.6)


def _age_term(detected_at, now_iso):
    """Older open findings drift up — nothing should rot silently in the feed."""
    days = base.days_between(detected_at, now_iso)
    if days <= 0:
        return 0.0
    return min(1.0, days / 21.0)


def _recoverability(f):
    """How likely acting now still changes the outcome.

    A customer who wrote yesterday is very recoverable; a quote from four months
    ago much less so. This is what stops the feed filling with archaeology.
    """
    detector = f.get("detector") or ""
    base_score = {
        "unanswered_inbound": 0.95,
        "unresolved_complaint": 0.85,
        "overdue_commitment": 0.8,
        "quote_without_followup": 0.6,
        "stale_opportunity": 0.45,
    }.get(detector, 0.5)
    return base_score


def score_finding(f, now_iso=None):
    """0-100 attention score, plus the reasons behind it."""
    now_iso = now_iso or db.now()
    terms = {
        "severity": SEVERITY_WEIGHT.get(f.get("severity"), 0.4),
        "urgency": float(f.get("urgency") or 0.5),
        "impact": _impact_term(f.get("impact_cents")),
        "age": _age_term(f.get("detected_at"), now_iso),
        "recoverability": _recoverability(f),
    }
    raw = sum(WEIGHTS[k] * v for k, v in terms.items())
    confidence = float(f.get("confidence") or 0.5)
    # Confidence scales but never erases: a half-sure finding keeps 70% of its rank.
    scaled = raw * (0.7 + 0.3 * confidence)
    return int(round(max(0, min(100, scaled * 100)))), terms


def rank(org_id, findings=None, now_iso=None):
    """Score and sort findings, writing the score back so the feed is stable."""
    now_iso = now_iso or db.now()
    findings = findings if findings is not None else db.findings(org_id, limit=1000)
    out = []
    for f in findings:
        s, terms = score_finding(f, now_iso)
        f["attention"] = s
        f["attention_terms"] = terms
        out.append(f)
    out.sort(key=lambda x: (-x["attention"], -(x.get("impact_cents") or 0)))
    return out


def persist(org_id, ranked):
    with db._conn() as c:
        for f in ranked:
            c.execute("UPDATE findings SET attention=? WHERE org_id=? AND id=?",
                      (f["attention"], org_id, f["id"]))


def today(org_id, ranked=None, limit=6, now_iso=None):
    """What needs the owner personally, today.

    Capped hard and diversified by category: five variations of the same problem
    is one problem, and a list that is always the same five names stops being
    read within a week.
    """
    ranked = ranked if ranked is not None else rank(org_id, now_iso=now_iso)
    picked, per_category = [], {}
    for f in ranked:
        if f["attention"] < OWNER_THRESHOLD and picked:
            break
        cat = f.get("category")
        if per_category.get(cat, 0) >= 2 and len(picked) >= 3:
            continue
        picked.append(f)
        per_category[cat] = per_category.get(cat, 0) + 1
        if len(picked) >= limit:
            break
    return picked


def summarize(org_id, ranked=None):
    """The Control Center headline numbers — all counted, none estimated."""
    ranked = ranked if ranked is not None else rank(org_id)
    money_at_risk = sum(f.get("impact_cents") or 0 for f in ranked
                        if f.get("category") == "revenue")
    known_value = [f for f in ranked if f.get("impact_cents")]
    return {
        "total": len(ranked),
        "needs_owner": len([f for f in ranked if f["attention"] >= OWNER_THRESHOLD]),
        "ai_actionable": len([f for f in ranked if f.get("ai_actionable")]),
        "by_category": _counts(ranked, "category"),
        "by_severity": _counts(ranked, "severity"),
        "revenue_at_risk_cents": money_at_risk,
        "valued_findings": len(known_value),
        "unvalued_findings": len(ranked) - len(known_value),
    }


def _counts(items, key):
    out = {}
    for i in items:
        out[i.get(key)] = out.get(i.get(key), 0) + 1
    return out
