"""
Plans and entitlements — kept separate from pricing on purpose.

What a plan *allows* and what a plan *costs* change on completely different
schedules. Pricing will be rewritten several times before the feature set is;
wiring dollar amounts into permission checks guarantees a refactor every time
marketing changes its mind. So plans name capabilities, and money lives with the
billing provider.

Server-side only. A client that says it is on the Autopilot plan is making a
claim, not a statement of fact.
"""
PLANS = {
    "scan": {
        "label": "Scan", "price_hint": "free",
        "blurb": "See what you're missing.",
        "features": ["website_scan", "email_connect", "findings_sample", "chaos_score"],
        "limits": {"findings_visible": 5, "messages_scanned": 2000,
                   "integrations": 1, "history_days": 30, "seats": 1},
    },
    "control": {
        "label": "Control", "price_hint": "monthly",
        "blurb": "Continuous monitoring of your email and calendar.",
        "features": ["website_scan", "email_connect", "calendar_connect", "findings_all",
                     "chaos_score", "daily_brief", "evidence", "entity_graph",
                     "commitments", "ai_drafts"],
        "limits": {"findings_visible": None, "messages_scanned": 50000,
                   "integrations": 3, "history_days": 365, "seats": 5},
    },
    "autopilot": {
        "label": "Autopilot", "price_hint": "monthly",
        "blurb": "Connect your CRM, accounting and phone. Approved actions run themselves.",
        "features": ["website_scan", "email_connect", "calendar_connect", "crm_connect",
                     "accounting_connect", "phone_connect", "findings_all", "chaos_score",
                     "daily_brief", "weekly_review", "evidence", "entity_graph",
                     "commitments", "ai_drafts", "actions", "cross_system",
                     "benchmarks"],
        "limits": {"findings_visible": None, "messages_scanned": 250000,
                   "integrations": 10, "history_days": 1095, "seats": 25},
    },
    "business_pro": {
        "label": "Business Pro", "price_hint": "monthly",
        "blurb": "Multi-location, marketing, SEO and reputation intelligence.",
        "features": ["*"],
        "limits": {"findings_visible": None, "messages_scanned": 1000000,
                   "integrations": 25, "history_days": 1825, "seats": 100},
    },
    "enterprise": {
        "label": "Enterprise", "price_hint": "custom",
        "blurb": "SSO, API access, custom integrations and audit controls.",
        "features": ["*"],
        "limits": {"findings_visible": None, "messages_scanned": None,
                   "integrations": None, "history_days": None, "seats": None},
    },
}

DEFAULT_PLAN = "scan"


def plan_of(org):
    key = (org or {}).get("plan") or DEFAULT_PLAN
    return key if key in PLANS else DEFAULT_PLAN


def has(org, feature):
    p = PLANS[plan_of(org)]
    return "*" in p["features"] or feature in p["features"]


def limit(org, name):
    return PLANS[plan_of(org)]["limits"].get(name)


def within(org, name, current):
    """Is `current` inside this plan's limit for `name`? None means unlimited."""
    cap = limit(org, name)
    return True if cap is None else current < cap


def describe(org):
    key = plan_of(org)
    p = PLANS[key]
    return {"plan": key, "label": p["label"], "blurb": p["blurb"],
            "price_hint": p["price_hint"], "limits": p["limits"],
            "features": p["features"]}


def public_plans():
    return [{"key": k, **{f: v for f, v in p.items() if f != "features"},
             "features": p["features"]} for k, p in PLANS.items()]
