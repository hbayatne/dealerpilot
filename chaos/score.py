"""
The Chaos Score — 0 (in control) to 100 (critical), and why.

Deliberately **not** produced by a language model. The number is computed from
counted facts, every input is shown, and the methodology carries a version so a
score can be compared against last month's honestly. An owner who cannot see why
the number moved will not trust it, and a number nobody trusts changes no
behaviour.

Dimensions are only scored when the connected integrations can actually support
them. A business with email connected gets a communication score and an explicit
"not analyzed" on collections — never a fabricated one. That honesty is also what
makes the next integration worth connecting.
"""
from chaos import db
from chaos.detect import base, signals as S

METHODOLOGY = "chaos-score-v1"

# Below this many analyzed dimensions, an overall score describes too little of
# the business to be stated as fact.
MIN_DIMENSIONS_FOR_SCORE = 3

BANDS = [(20, "excellent", "Excellent control"),
         (40, "controlled", "Controlled"),
         (60, "moderate", "Moderate chaos"),
         (80, "high", "High chaos"),
         (101, "critical", "Critical chaos")]

# Which integrations a dimension needs before it can be scored at all.
DIMENSIONS = {
    "client_communication": {"label": "Client communication", "needs": ["email"], "weight": 1.3},
    "followup":             {"label": "Follow-up", "needs": ["email"], "weight": 1.2},
    "commitments":          {"label": "Commitments", "needs": ["email"], "weight": 1.2},
    "revenue":              {"label": "Revenue at risk", "needs": ["email"], "weight": 1.3},
    "client_problems":      {"label": "Client problems", "needs": ["email"], "weight": 1.1},
    "digital":              {"label": "Digital presence", "needs": ["website"], "weight": 0.7},
    "inventory":            {"label": "Inventory & capital", "needs": ["inventory"], "weight": 1.3},
    "collections":          {"label": "Collections", "needs": ["accounting"], "weight": 1.2},
    "financial":            {"label": "Financial leakage", "needs": ["accounting"], "weight": 1.0},
    "reputation":           {"label": "Reputation", "needs": ["reviews"], "weight": 0.8},
    "scheduling":           {"label": "Scheduling", "needs": ["calendar"], "weight": 0.8},
    "marketing":            {"label": "Marketing", "needs": ["ads"], "weight": 0.8},
    "data":                 {"label": "Data consistency", "needs": ["crm"], "weight": 0.7},
}

# Which integration kinds satisfy which capability.
CAPABILITY = {
    "email": {"imap", "gmail", "outlook"},
    "website": {"website"},
    "accounting": {"quickbooks", "xero"},
    "reviews": {"google_business", "reviews"},
    "calendar": {"google_calendar", "outlook_calendar"},
    "ads": {"google_ads", "meta_ads"},
    "crm": {"hubspot", "salesforce", "gohighlevel", "pipedrive"},
    "inventory": {"dealercenter", "dms", "vauto", "frazer"},
}


def band(score):
    for cutoff, key, label in BANDS:
        if score < cutoff:
            return key, label
    return "critical", "Critical chaos"


def capabilities(org_id, extra=None):
    """Which analysis capabilities this org currently has."""
    kinds = {i["kind"] for i in db.integrations(org_id) if i["status"] != "error"}
    kinds |= set(extra or [])
    return {cap for cap, kset in CAPABILITY.items() if kinds & kset}


def _pct(n, d):
    return 0.0 if not d else n / float(d)


def _shape(rate, floor=0, ceiling=100):
    """A rate in 0..1 to a 0..100 dimension score, clamped."""
    return int(round(max(floor, min(ceiling, rate * 100))))


# ---------------------------------------------------------------- measurement
def measure(org_id, now_iso=None):
    """The counted facts every dimension score is derived from."""
    now_iso = now_iso or db.now()
    convs = db.conversations(org_id, limit=5000)
    inbound_threads = replied = 0
    latencies = []
    open_unanswered = 0

    for conv in convs:
        msgs = [m for m in db.messages_in(org_id, conv["id"]) if not m.get("automated")]
        ins = [m for m in msgs if m["direction"] == "in"]
        outs = [m for m in msgs if m["direction"] == "out"]
        if not ins:
            continue
        inbound_threads += 1
        first_in = ins[0]
        first_reply = next((m for m in outs
                            if (m["sent_at"] or "") > (first_in["sent_at"] or "")), None)
        if first_reply:
            replied += 1
            latencies.append(base.business_hours_between(first_in["sent_at"],
                                                         first_reply["sent_at"]))
        # "Waiting on us" means they asked something we have not answered — not
        # merely that theirs was the last message. "Got it, appreciate it." ends
        # a thread; counting it as an open obligation inflates the score and
        # makes every other number look less credible.
        last = msgs[-1] if msgs else None
        if last is not None and last["direction"] == "in":
            body = last.get("body") or ""
            if S.asks_something(body) and not S.looks_closed(body):
                open_unanswered += 1

    latencies.sort()
    median = latencies[len(latencies) // 2] if latencies else None

    open_findings = db.findings(org_id, limit=2000)
    by_detector = {}
    for f in open_findings:
        by_detector[f["detector"]] = by_detector.get(f["detector"], 0) + 1

    commits = db.commitments(org_id, limit=2000)
    overdue = [c for c in commits if c["state"] == "overdue"]

    money_at_risk = sum(f["impact_cents"] or 0 for f in open_findings
                        if f["category"] == "revenue")

    return {
        "threads": len(convs),
        "inbound_threads": inbound_threads,
        "replied_threads": replied,
        "never_replied": inbound_threads - replied,
        "open_unanswered": open_unanswered,
        "median_first_response_hours": median,
        "commitments_total": len(commits),
        "commitments_overdue": len(overdue),
        "findings_open": len(open_findings),
        "by_detector": by_detector,
        "money_at_risk_cents": money_at_risk,
        "messages": db.message_count(org_id),
        "contacts": len(db.entities(org_id, kind="person", role="contact", limit=5000)),
        "inventory": _inventory_measurements(org_id, now_iso),
    }


def _inventory_measurements(org_id, now_iso):
    """Counted facts about the lot. Empty when no DMS export has been loaded."""
    import datetime
    from chaos.detect import inventory as inv_rules
    rows = db.vehicles(org_id)
    if not rows:
        return {}
    try:
        today = datetime.date.fromisoformat(now_iso[:10])
    except Exception:
        today = datetime.date.today()
    active = [v for v in rows if v.get("status") != "sold"]
    aged = [v for v in active
            if (inv_rules._days_in_stock(v, today) or 0) >= inv_rules.AGED_CRITICAL_DAYS]
    frontline = [v for v in active if v.get("status") == "frontline"]
    unsellable = [v for v in frontline if not v.get("price_cents") or not v.get("photo_count")]
    negative = [v for v in active
                if (inv_rules.margin_pct(v) or 0) < 0 and inv_rules.margin_pct(v) is not None]
    return {
        "total": len(rows),
        "active": len(active),
        "aged_90": len(aged),
        "aged_capital_cents": sum(v["cost_cents"] for v in aged
                                  if v.get("cost_cents") is not None),
        "unsellable": len(unsellable),
        "negative_margin": len(negative),
        "no_cost": len([v for v in active if v.get("cost_cents") is None]),
        "total_cost_cents": sum(v["cost_cents"] for v in active
                                if v.get("cost_cents") is not None),
    }


def _dimension_scores(m, website_result=None):
    """Each dimension's 0-100 score plus the factors that produced it."""
    out = {}

    # --- client communication: are people getting answered, and how fast?
    if m["inbound_threads"]:
        never = _pct(m["never_replied"], m["inbound_threads"])
        waiting = _pct(m["open_unanswered"], m["inbound_threads"])
        med = m["median_first_response_hours"]
        # 4 business hours is good; 24 is poor. Linear between, capped.
        lat = 0.0 if med is None else max(0.0, min(1.0, (med - 4) / 20.0))
        score = _shape(never * 0.45 + waiting * 0.3 + lat * 0.25)
        out["client_communication"] = {
            "score": score,
            "factors": [
                _factor("Inbound conversations never answered", m["never_replied"],
                        m["inbound_threads"], f"{never:.0%}"),
                _factor("Conversations currently waiting on us", m["open_unanswered"],
                        m["inbound_threads"], f"{waiting:.0%}"),
                {"label": "Median first response",
                 "value": base.humanize_hours(med) if med is not None else "no data",
                 "detail": "Target: under 4 business hours."},
            ]}

    # --- follow-up: deals nobody chased
    stale = m["by_detector"].get("stale_opportunity", 0)
    unchased = m["by_detector"].get("quote_without_followup", 0)
    denom = max(m["inbound_threads"], 1)
    if m["inbound_threads"]:
        rate = _pct(stale + unchased, denom)
        out["followup"] = {
            "score": _shape(min(1.0, rate * 2.5)),
            "factors": [
                _factor("Opportunities that went quiet", stale, denom, None),
                _factor("Quotes never followed up", unchased, denom, None),
            ]}

    # --- commitments: promises kept
    if m["commitments_total"]:
        rate = _pct(m["commitments_overdue"], m["commitments_total"])
        out["commitments"] = {
            "score": _shape(rate),
            "factors": [
                _factor("Commitments past their date with no follow-through",
                        m["commitments_overdue"], m["commitments_total"], f"{rate:.0%}"),
            ]}

    # --- revenue at risk
    rev = m["by_detector"].get("stale_opportunity", 0) + \
        m["by_detector"].get("quote_without_followup", 0) + \
        m["by_detector"].get("unanswered_inbound", 0)
    if m["inbound_threads"]:
        rate = _pct(rev, max(m["inbound_threads"], 1))
        out["revenue"] = {
            "score": _shape(min(1.0, rate * 2.2)),
            "factors": [
                _factor("Conversations with revenue exposure", rev, m["inbound_threads"], None),
                {"label": "Identified value at risk",
                 "value": base.money(m["money_at_risk_cents"]) if m["money_at_risk_cents"]
                 else "value unknown",
                 "detail": "Only amounts actually stated in conversations are counted."},
            ]}

    # --- client problems
    problems = m["by_detector"].get("unresolved_complaint", 0)
    if m["contacts"]:
        rate = _pct(problems, max(m["contacts"], 1))
        out["client_problems"] = {
            "score": _shape(min(1.0, rate * 6)),
            "factors": [
                _factor("Contacts with an unresolved problem", problems, m["contacts"], None),
            ]}

    # --- inventory: how much capital is stuck, and how much of the lot is
    # actually shoppable. Every input is counted from the DMS export.
    inv = m.get("inventory") or {}
    if inv.get("active"):
        active = inv["active"]
        aged_rate = _pct(inv["aged_90"], active)
        unsellable_rate = _pct(inv["unsellable"], active)
        neg = _pct(inv["negative_margin"], active)
        score = _shape(min(1.0, aged_rate * 1.4 + unsellable_rate * 0.8 + neg * 2.0))
        factors = [
            _factor("Units in stock over 90 days", inv["aged_90"], active,
                    f"{aged_rate:.0%}"),
            _factor("Frontline units with no price or photos", inv["unsellable"],
                    active, f"{unsellable_rate:.0%}"),
            _factor("Units priced below cost", inv["negative_margin"], active, None),
        ]
        if inv.get("aged_capital_cents"):
            factors.append({"label": "Cost carried on aged units",
                            "value": base.money(inv["aged_capital_cents"]),
                            "detail": "Acquisition and recon cost as exported."})
        if inv.get("no_cost"):
            factors.append({"label": "Units with no cost in the export",
                            "value": f"{inv['no_cost']} of {active}",
                            "detail": "Money figures for this lot are a floor, not a total."})
        out["inventory"] = {"score": score, "factors": factors}

    # --- digital presence, from the website scan
    if website_result and website_result.get("issues") is not None:
        issues = website_result["issues"]
        crit = len([i for i in issues if i.get("severity") == "critical"])
        warn = len([i for i in issues if i.get("severity") == "warn"])
        out["digital"] = {
            "score": _shape(min(1.0, (crit * 0.22 + warn * 0.07))),
            "factors": [
                {"label": "Critical website issues", "value": str(crit), "detail": None},
                {"label": "Website warnings", "value": str(warn), "detail": None},
            ]}
    return out


def _factor(label, n, d, pct):
    return {"label": label, "value": f"{n} of {d}" + (f" ({pct})" if pct else ""),
            "detail": None}


def compute(org_id, now_iso=None, website_result=None, extra_capabilities=None):
    """The score, its dimensions, and an explicit coverage statement."""
    m = measure(org_id, now_iso)
    caps = capabilities(org_id, extra_capabilities)
    if website_result:
        caps.add("website")
    scored = _dimension_scores(m, website_result)

    dimensions, analyzed, unavailable = {}, [], []
    total_w = total_v = 0.0
    for key, spec in DIMENSIONS.items():
        have = all(n in caps for n in spec["needs"])
        entry = {"label": spec["label"], "weight": spec["weight"],
                 "needs": spec["needs"], "analyzed": False, "score": None,
                 "factors": []}
        if have and key in scored:
            entry.update(analyzed=True, score=scored[key]["score"],
                         factors=scored[key]["factors"])
            total_w += spec["weight"]
            total_v += spec["weight"] * scored[key]["score"]
            analyzed.append(key)
        else:
            entry["reason"] = ("not enough data yet" if have
                               else "connect " + " or ".join(spec["needs"]))
            unavailable.append(key)
        dimensions[key] = entry

    score = int(round(total_v / total_w)) if total_w else 0
    key, label = band(score)
    # With only one dimension visible we have seen a fraction of the business, and
    # calling that "Critical chaos" is a claim about the whole company we cannot
    # support. Below the floor the number is reported as provisional and the band
    # is withheld — the dimension score is still shown, because that part is real.
    provisional = len(analyzed) < MIN_DIMENSIONS_FOR_SCORE
    if provisional:
        label = f"Provisional — {len(analyzed)} of {len(DIMENSIONS)} dimensions seen"
    coverage = {
        "provisional": provisional,
        "analyzed": analyzed,
        "unavailable": unavailable,
        "analyzed_count": len(analyzed),
        "total_count": len(DIMENSIONS),
        "statement": f"{len(analyzed)} of {len(DIMENSIONS)} dimensions analyzed "
                     f"from the systems you have connected.",
        "capabilities": sorted(caps),
    }
    return {"score": score, "band": key, "band_label": label,
            "provisional": provisional,
            "methodology": METHODOLOGY, "dimensions": dimensions,
            "coverage": coverage, "measurements": m}


def save(org_id, result):
    return db.save_score(org_id, result["score"], result["band"],
                         result["methodology"], result["dimensions"],
                         result["coverage"])
