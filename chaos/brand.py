"""
Brand configuration — single source of truth for product naming.

"Chaos Control AI" is a WORKING name. Everything user-visible pulls from here so
a rename is a config change, not a refactor. Never hard-code the product name
anywhere else; import `BRAND` instead.

Override any field at deploy time with env vars (BRAND_NAME, BRAND_SHORT, ...)
so a rename ships without a code change at all.
"""
import os


def _env(key, default):
    return os.environ.get(key) or default


class _Brand:
    name = _env("BRAND_NAME", "Chaos Control AI")
    short = _env("BRAND_SHORT", "Chaos Control")
    # The unit of measurement. Renaming the product renames these too.
    score_name = _env("BRAND_SCORE_NAME", "Chaos Score")
    scan_name = _env("BRAND_SCAN_NAME", "Chaos Scan")
    feed_name = _env("BRAND_FEED_NAME", "Chaos Feed")
    console_name = _env("BRAND_CONSOLE_NAME", "Control Center")
    brief_name = _env("BRAND_BRIEF_NAME", "Morning Brief")
    tagline = _env("BRAND_TAGLINE", "Run the business. We'll find the chaos.")
    subline = _env(
        "BRAND_SUBLINE",
        "Your clients, money, leads, calls and appointments live in different "
        "systems. We connect them, find what is falling through the cracks, "
        "and help you fix it.")
    cta = _env("BRAND_CTA", "Run a free scan")
    support_email = _env("BRAND_SUPPORT_EMAIL", "support@example.com")
    user_agent = _env(
        "BRAND_USER_AGENT",
        "Mozilla/5.0 (compatible; ChaosControlBot/1.0; +https://example.com/bot)")

    def public(self):
        """Everything the front end needs to render itself unbranded-in-code."""
        return {k: getattr(self, k) for k in
                ("name", "short", "score_name", "scan_name", "feed_name",
                 "console_name", "brief_name", "tagline", "subline", "cta",
                 "support_email")}


BRAND = _Brand()
