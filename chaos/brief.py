"""
The Morning Brief — the thing an owner actually reads.

Written as prose a person would say out loud, assembled from counted facts. No
model is involved: every sentence is a template filled from the same numbers the
dashboard shows, which means the brief can never claim something the evidence
doesn't support.

Two rules learned from every other product that sends a daily digest:

* A brief that is usually empty stops being opened, and a brief that is always
  long stops being read. This one leads with what changed, and says plainly when
  nothing did.
* It never lists more than a handful of items. The whole point of the product is
  to reduce what the owner has to hold in their head.
"""
from chaos import attention, db, entitlements, score as score_mod
from chaos.brand import BRAND
from chaos.detect import base


def _score_movement(history):
    """(current, delta, direction) — delta is vs. the previous saved score."""
    if not history:
        return None, None, None
    current = history[-1]["score"]
    if len(history) < 2:
        return current, None, None
    prev = history[-2]["score"]
    delta = current - prev
    return current, delta, ("down" if delta < 0 else ("up" if delta > 0 else "flat"))


def build(org_id, now_iso=None):
    """The brief as structured data; `render_text` turns it into prose."""
    org = db.get_org(org_id)
    now_iso = now_iso or db.now()
    ranked = attention.rank(org_id, now_iso=now_iso)
    summary = attention.summarize(org_id, ranked)
    history = db.score_history(org_id, limit=30)
    score, delta, direction = _score_movement(history)

    today = attention.today(org_id, ranked, limit=4, now_iso=now_iso)
    commitments = db.commitments(org_id, limit=500)
    overdue = [c for c in commitments if c["state"] == "overdue"]

    # Anything detected since the last brief is what "new" means here.
    fresh = [f for f in ranked if base.days_between(f.get("detected_at"), now_iso) <= 1]

    latest = db.latest_score(org_id)
    coverage = (latest or {}).get("coverage") or {}

    return {
        "org": {"id": org_id, "name": org["name"]},
        "generated_at": now_iso,
        "score": score,
        "score_delta": delta,
        "score_direction": direction,
        "band": (latest or {}).get("band"),
        "needs_you": today,
        "new_since_yesterday": len(fresh),
        "totals": summary,
        "overdue_commitments": len(overdue),
        "kept_commitments": len([c for c in commitments
                                 if c["state"] == "likely_fulfilled"]),
        "coverage": coverage,
        "plan": entitlements.plan_of(org),
    }


def render_text(brief):
    """Plain text, for email or a phone notification."""
    lines = [f"{BRAND.brief_name} — {brief['org']['name']}", ""]

    if brief["score"] is None:
        lines.append("No scan has run yet. Connect a mailbox and run a scan to get "
                     "your first picture.")
        return "\n".join(lines)

    if brief["score_delta"] is None:
        lines.append(f"Your {BRAND.score_name} is {brief['score']} "
                     f"({brief['band'] or 'unscored'}). This is your first reading, "
                     f"so there's nothing to compare it against yet.")
    elif brief["score_delta"] == 0:
        lines.append(f"Your {BRAND.score_name} is unchanged at {brief['score']}.")
    else:
        moved = "improved" if brief["score_delta"] < 0 else "worsened"
        lines.append(f"Your {BRAND.score_name} {moved} from "
                     f"{brief['score'] - brief['score_delta']} to {brief['score']}.")

    t = brief["totals"]
    if t["revenue_at_risk_cents"]:
        lines.append(f"{base.money(t['revenue_at_risk_cents'])} of identified revenue is "
                     f"sitting in conversations that have stalled"
                     + (f", plus {t['unvalued_findings']} more where no amount was "
                        f"stated." if t["unvalued_findings"] else "."))

    if brief["overdue_commitments"]:
        lines.append(f"{brief['overdue_commitments']} commitment"
                     f"{'s' if brief['overdue_commitments'] != 1 else ''} made to "
                     f"customers "
                     f"{'are' if brief['overdue_commitments'] != 1 else 'is'} past the "
                     f"date "
                     f"{'they were' if brief['overdue_commitments'] != 1 else 'it was'} "
                     f"promised.")

    lines.append("")
    if brief["needs_you"]:
        lines.append("Needs you today:")
        for f in brief["needs_you"]:
            value = base.money(f["impact_cents"]) if f.get("impact_cents") else None
            lines.append(f"  · {f['title']}"
                         + (f" — {value}" if value else "")
                         + f" ({int(round((f.get('confidence') or 0) * 100))}% confidence)")
            if f.get("summary"):
                lines.append(f"      {f['summary']}")
    else:
        lines.append("Nothing needs your personal attention today.")

    lines.append("")
    if brief["new_since_yesterday"]:
        lines.append(f"{brief['new_since_yesterday']} of these were found in the last day.")
    lines.append(f"{brief['kept_commitments']} commitment"
                 f"{'s' if brief['kept_commitments'] != 1 else ''} looked handled.")

    cov = brief["coverage"]
    if cov.get("unavailable"):
        # Human labels, not internal keys — this text is read by a business owner.
        names = [score_mod.DIMENSIONS.get(k, {}).get("label", k).lower()
                 for k in cov["unavailable"][:4]]
        lines.append("")
        lines.append(f"Still blind to: {', '.join(names)}"
                     f"{' and more' if len(cov['unavailable']) > 4 else ''}. "
                     f"{cov.get('statement', '')}")
    return "\n".join(lines)
