"""
Public website scan — the free wedge, and the only part of the product that
works before anyone connects anything.

Two hard constraints shape this module.

**SSRF.** Every URL here comes from an anonymous form. Fetching a user-supplied
URL from inside our network is the classic way to hand an attacker our cloud
metadata service. So every hostname is resolved *before* connecting, every
resolved address is checked against private/loopback/link-local/metadata ranges,
and redirects are followed manually so each hop is re-validated. A redirect to
169.254.169.254 must fail on the second hop as surely as on the first.

**Owner language.** "CLS increased to 0.31" means nothing to someone running a
roofing company. Every issue is phrased as a business consequence, with the
technical detail kept underneath for whoever wants it.
"""
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from chaos.brand import BRAND

TIMEOUT = 12
MAX_BYTES = 900_000
MAX_REDIRECTS = 4

_BLOCKED_PORTS = {22, 23, 25, 3306, 5432, 6379, 9200, 11211, 27017}


class UnsafeTarget(ValueError):
    """The requested URL resolves somewhere we must never fetch."""


# ---------------------------------------------------------------- safety
def normalize_url(url):
    url = (url or "").strip()
    if not url:
        raise UnsafeTarget("Enter a website address.")
    scheme = re.match(r"^([a-z][a-z0-9+.-]*):", url, re.I)
    if scheme and scheme.group(1).lower() not in ("http", "https"):
        # file:, gopher:, ftp:, data: — never prefix these into something fetchable.
        raise UnsafeTarget("Only http and https addresses can be scanned.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeTarget("Only http and https addresses can be scanned.")
    if not parts.hostname:
        raise UnsafeTarget("That doesn't look like a website address.")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/",
                                    parts.query, ""))


def _ip_is_public(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if (addr.is_private or addr.is_loopback or addr.is_link_local or
            addr.is_multicast or addr.is_reserved or addr.is_unspecified):
        return False
    # AWS/GCP/Azure instance metadata, reachable even from some "public" ranges.
    if str(addr) in ("169.254.169.254", "100.100.100.200", "fd00:ec2::254"):
        return False
    return True


def assert_safe(url):
    """Resolve and validate a URL. Returns (url, resolved_ips).

    Caveat worth knowing before deploying: this resolves DNS itself and checks
    the addresses. If the process is ever put behind an HTTP proxy that does its
    own name resolution, the proxy — not this check — decides what gets
    connected to, and a DNS-rebinding window opens between our lookup and its.
    Egress from the scanner should therefore be either direct, or through a proxy
    with its own allowlist. Do not assume this function alone is sufficient once
    a proxy is in the path.
    """
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname
    if not host:
        raise UnsafeTarget("That doesn't look like a website address.")
    if parts.port and parts.port in _BLOCKED_PORTS:
        raise UnsafeTarget("That port cannot be scanned.")
    if host.lower() in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        raise UnsafeTarget("Local addresses cannot be scanned.")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeTarget(f"We couldn't find a site at {host}.")
    ips = sorted({i[4][0] for i in infos})
    if not ips:
        raise UnsafeTarget(f"We couldn't find a site at {host}.")
    for ip in ips:
        if not _ip_is_public(ip):
            raise UnsafeTarget("That address points to a private network and "
                               "cannot be scanned.")
    return url, ips


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def fetch(url, method="GET"):
    """Fetch a URL, re-validating every redirect hop against the SSRF rules."""
    hops, current = [], normalize_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        assert_safe(current)
        req = urllib.request.Request(current, method=method,
                                     headers={"User-Agent": BRAND.user_agent,
                                              "Accept": "text/html,*/*"})
        try:
            with _opener.open(req, timeout=TIMEOUT) as r:
                status = getattr(r, "status", 200)
                body = r.read(MAX_BYTES).decode("utf-8", errors="replace")
                return {"url": current, "status": status, "body": body,
                        "headers": dict(r.headers), "hops": hops, "error": None}
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and loc:
                nxt = urllib.parse.urljoin(current, loc)
                hops.append({"from": current, "to": nxt, "status": e.code})
                current = normalize_url(nxt)
                continue
            return {"url": current, "status": e.code, "body": "", "headers": {},
                    "hops": hops, "error": f"HTTP {e.code}"}
        except UnsafeTarget:
            raise
        except Exception as e:
            return {"url": current, "status": 0, "body": "", "headers": {},
                    "hops": hops, "error": str(e)[:160]}
    return {"url": current, "status": 0, "body": "", "headers": {}, "hops": hops,
            "error": "too many redirects"}


# ---------------------------------------------------------------- checks
def _issue(code, severity, headline, detail, action, technical=None):
    """Business consequence first; the technical reason underneath."""
    return {"code": code, "severity": severity, "headline": headline,
            "detail": detail, "action": action, "technical": technical}


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META_DESC = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
                        re.I | re.S)
_VIEWPORT = re.compile(r'<meta[^>]+name=["\']viewport["\']', re.I)
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_TEL_LINK = re.compile(r'href=["\']tel:', re.I)
_FORM = re.compile(r"<form\b", re.I)
_SCHEMA = re.compile(r'application/ld\+json|itemtype=["\']https?://schema\.org', re.I)
_ANALYTICS = re.compile(
    r"(gtag\(|googletagmanager|google-analytics|analytics\.js|"
    r"fbq\(|clarity\.ms|plausible|matomo|posthog)", re.I)
_CONTACT_LINK = re.compile(r'href=["\'][^"\']*(contact|quote|estimate|appointment|'
                           r'schedule|book)[^"\']*["\']', re.I)
_IMG = re.compile(r"<img\b[^>]*>", re.I)


def analyze(url, fetcher=None):
    """Scan a public website. `fetcher` is injectable so tests run offline."""
    do_fetch = fetcher or fetch
    target = normalize_url(url)
    issues, facts = [], {}

    home = do_fetch(target)
    facts["final_url"] = home.get("url")
    facts["status"] = home.get("status")
    facts["redirects"] = len(home.get("hops") or [])

    if home.get("error") or not home.get("body"):
        issues.append(_issue(
            "unreachable", "critical",
            "We could not load your website",
            f"A visitor going to {target} would have seen the same failure we did"
            f"{': ' + home['error'] if home.get('error') else ''}. Every hour this is "
            "down is a customer who called someone else.",
            "Check with whoever hosts the site today.",
            technical=f"status={home.get('status')} error={home.get('error')}"))
        return {"url": target, "reachable": False, "issues": issues, "facts": facts,
                "checks_run": 1}

    body = home["body"]
    low = body.lower()
    headers = {k.lower(): v for k, v in (home.get("headers") or {}).items()}
    final = home["url"]

    # --- security / trust
    if not final.startswith("https://"):
        issues.append(_issue(
            "no_https", "critical",
            "Your site is not secure (no HTTPS)",
            "Browsers show visitors a “Not secure” warning on sites without HTTPS, "
            "and search engines rank them lower. People abandon forms when they see it.",
            "Ask your host to enable a free SSL certificate and redirect http to https.",
            technical=f"final URL is {final}"))

    # --- can a customer actually contact you?
    has_tel = bool(_TEL_LINK.search(body))
    has_phone = bool(_PHONE.search(re.sub(r"<[^>]+>", " ", body)))
    has_form = bool(_FORM.search(body))
    has_contact_link = bool(_CONTACT_LINK.search(body))
    facts.update(phone_visible=has_phone, tap_to_call=has_tel,
                 has_form=has_form, contact_path=has_contact_link)

    if not has_phone and not has_form:
        issues.append(_issue(
            "no_contact", "critical",
            "There is no obvious way to contact you from your home page",
            "We found no phone number and no enquiry form on the page a visitor "
            "lands on. Every visitor who wanted to reach you had to work for it — "
            "most won't.",
            "Put a phone number and a short enquiry form above the fold.",
            technical="no tel: link, no visible phone pattern, no <form>"))
    elif has_phone and not has_tel:
        issues.append(_issue(
            "phone_not_tappable", "warn",
            "Your phone number can't be tapped on a phone",
            "The number is on the page as text, so mobile visitors have to memorise "
            "it and switch apps. Most of your traffic is mobile.",
            "Wrap the number in a tel: link so tapping it dials.",
            technical="phone text present but no href=\"tel:\""))
    if not has_form:
        issues.append(_issue(
            "no_form", "warn",
            "No enquiry form on the home page",
            "Visitors who don't want to call have no way to leave their details, "
            "and you have no record that they were interested.",
            "Add a short form — name, phone, and what they need.",
            technical="no <form> element found"))

    # --- mobile
    if not _VIEWPORT.search(body):
        issues.append(_issue(
            "no_viewport", "critical",
            "Your site isn't set up for mobile phones",
            "Without a mobile viewport the page renders desktop-width on a phone, "
            "so visitors have to pinch and zoom. Most people leave instead.",
            "Add a mobile viewport tag, or ask your web person to make the site responsive.",
            technical="missing <meta name=\"viewport\">"))

    # --- findability
    title = _TITLE.search(body)
    title_text = re.sub(r"\s+", " ", title.group(1)).strip() if title else ""
    facts["title"] = title_text
    if not title_text:
        issues.append(_issue(
            "no_title", "critical",
            "Your home page has no title",
            "The title is the blue line people click in Google results. Without it "
            "your listing looks broken.",
            "Set a page title with your business name and what you do.",
            technical="empty or missing <title>"))
    elif len(title_text) < 15:
        issues.append(_issue(
            "thin_title", "warn",
            "Your page title is very short",
            f"“{title_text}” tells a searcher almost nothing about what you do "
            "or where you are.",
            "Use something like “<what you do> in <your city> | <business name>”.",
            technical=f"title is {len(title_text)} characters"))

    desc = _META_DESC.search(body)
    if not desc:
        issues.append(_issue(
            "no_description", "warn",
            "No description for search results",
            "Google is writing your search listing for you, picking whatever text it "
            "finds. That's the first impression most new customers get.",
            "Add a one-sentence meta description that says what you do and your area.",
            technical="missing <meta name=\"description\">"))

    if not _SCHEMA.search(body):
        issues.append(_issue(
            "no_schema", "info",
            "Search engines can't read your business details directly",
            "Structured data is how Google picks up your address, hours and reviews "
            "for the panel beside search results.",
            "Add LocalBusiness structured data with your address, phone and hours.",
            technical="no schema.org / JSON-LD markup found"))

    # --- measurement
    if not _ANALYTICS.search(body):
        issues.append(_issue(
            "no_analytics", "warn",
            "You have no way of knowing where your customers come from",
            "No analytics tag is installed, so nobody can tell you whether your "
            "advertising is producing visitors or the money is going nowhere.",
            "Install Google Analytics (free) before spending more on advertising.",
            technical="no analytics or tag-manager script detected"))

    # --- crawlability
    robots = do_fetch(urllib.parse.urljoin(final, "/robots.txt"))
    rb = (robots.get("body") or "")
    facts["robots_found"] = robots.get("status") == 200
    if robots.get("status") == 200 and re.search(
            r"user-agent:\s*\*\s*(?:\n#[^\n]*)*\s*\n\s*disallow:\s*/\s*$",
            rb.lower(), re.M):
        issues.append(_issue(
            "robots_blocks_site", "critical",
            "Your website is telling Google not to list it",
            "The robots.txt file blocks search engines from the entire site. If your "
            "site has vanished from search results, this is very likely why.",
            "Remove the site-wide Disallow rule from robots.txt.",
            technical="robots.txt contains 'User-agent: *' with 'Disallow: /'"))

    sitemap_urls = re.findall(r"(?i)^sitemap:\s*(\S+)", rb, re.M)
    facts["sitemap_declared"] = bool(sitemap_urls)
    if not sitemap_urls:
        sm = do_fetch(urllib.parse.urljoin(final, "/sitemap.xml"))
        facts["sitemap_found"] = sm.get("status") == 200
        if sm.get("status") != 200:
            issues.append(_issue(
                "no_sitemap", "info",
                "No sitemap for search engines",
                "A sitemap tells Google which pages you have. Without one, newer "
                "pages can take much longer to appear in search.",
                "Publish a sitemap.xml and reference it from robots.txt.",
                technical=f"/sitemap.xml returned {sm.get('status')}"))
    else:
        facts["sitemap_found"] = True

    # --- weight, as a stand-in for speed without a paid API
    size_kb = len(body.encode("utf-8", errors="ignore")) / 1024.0
    images = len(_IMG.findall(body))
    facts["html_kb"] = round(size_kb, 1)
    facts["images"] = images
    if size_kb > 500:
        issues.append(_issue(
            "heavy_page", "warn",
            "Your home page is heavy and will feel slow on a phone",
            f"The page is {size_kb:.0f}KB of HTML before images load. On a phone "
            "signal that's several seconds of blank screen, and visitors leave.",
            "Ask your web person to reduce page size and compress images.",
            technical=f"{size_kb:.0f}KB HTML, {images} image tags"))

    facts["checks_run"] = 12
    return {"url": target, "reachable": True, "final_url": final,
            "issues": _ordered(issues), "facts": facts, "checks_run": 12}


_SEV_ORDER = {"critical": 0, "warn": 1, "info": 2}


def _ordered(issues):
    return sorted(issues, key=lambda i: _SEV_ORDER.get(i["severity"], 3))
