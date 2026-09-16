"""
Email normalization — the layer every source adapter feeds into.

This module decides four things that determine whether findings are any good:

1. **Direction.** Is this message from the outside world, from us, or internal?
   Decided from the org's own email domains, never from a header we can spoof.
2. **Threading.** Which messages form one conversation? `References` /
   `In-Reply-To` first, normalized subject as the fallback.
3. **Quoted text.** Reply chains repeat their history. If we don't strip it, a
   promise made once is re-detected in every later reply and one slip turns into
   nine findings. Stripping is not cosmetic — it is correctness.
4. **Automation.** Newsletters, receipts, calendar invites and no-reply blasts
   look exactly like unanswered customer email to a naive detector. Everything
   that smells automated is flagged here and excluded from "nobody replied"
   style findings. This is the single largest source of false positives.

Pure stdlib, no network, no database — so it is trivially testable offline.
"""
import datetime
import email.utils
import hashlib
import re

# ---------------------------------------------------------------- addresses
_ADDR_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def parse_addr(raw):
    """('Display Name', 'user@example.com') from any To/From header form."""
    name, addr = email.utils.parseaddr(raw or "")
    addr = (addr or "").strip().lower()
    if not addr:
        m = _ADDR_RE.search(raw or "")
        addr = m.group(0).lower() if m else ""
    return (name or "").strip().strip('"'), addr


def parse_addr_list(raw):
    if not raw:
        return []
    out = []
    for nm, ad in email.utils.getaddresses([raw] if isinstance(raw, str) else list(raw)):
        ad = (ad or "").strip().lower()
        if ad and "@" in ad:
            out.append({"name": (nm or "").strip().strip('"'), "addr": ad})
    return out


def domain_of(addr):
    return (addr or "").rsplit("@", 1)[-1].lower() if "@" in (addr or "") else ""


# ---------------------------------------------------------------- dates
def parse_date(raw):
    """RFC-2822 date header → naive UTC ISO string (the format the DB stores)."""
    if not raw:
        return None
    if isinstance(raw, datetime.datetime):
        dt = raw
    else:
        try:
            dt = email.utils.parsedate_to_datetime(raw)
        except Exception:
            return None
    if dt is None:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds")


# ---------------------------------------------------------------- threading
_SUBJ_PREFIX = re.compile(
    r"^\s*(?:(?:re|fw|fwd|aw|sv|vs|antw|rif|res|enc)\s*(?:\[\d+\])?\s*:\s*)+", re.I)


def normalize_subject(subject):
    s = _SUBJ_PREFIX.sub("", subject or "").strip()
    return re.sub(r"\s+", " ", s)


def thread_keys(headers, subject, participants):
    """Every key this message could be threaded under, primary first.

    A root message and the replies to it must land on the same conversation. The
    replies name the root in `References`/`In-Reply-To`; the root names only
    itself in `Message-ID` — so the root's *own* id has to be a key, or the first
    reply opens a second thread and no detector can ever see the exchange.

    The subject/participant hash is carried as an alias for the clients that send
    no reference headers at all. Callers resolve an existing conversation by any
    key and create under the primary one.
    """
    keys = []
    refs = (headers.get("references") or "").split()
    if refs:
        keys.append("ref:" + refs[0].strip("<>"))
    irt = (headers.get("in-reply-to") or "").strip().strip("<>")
    if irt and f"ref:{irt}" not in keys:
        keys.append("ref:" + irt)
    mid = (headers.get("message-id") or "").strip().strip("<>")
    if mid and f"ref:{mid}" not in keys:
        keys.append("ref:" + mid)

    subj = normalize_subject(subject)
    who = ",".join(sorted(set(participants or [])))
    if subj or who:
        keys.append("subj:" + hashlib.sha1(f"{subj.lower()}|{who}".encode()).hexdigest()[:24])
    return keys or ["mid:unknown"]


def thread_key(headers, subject, participants):
    """The single primary key for this message (see `thread_keys`)."""
    return thread_keys(headers, subject, participants)[0]


# ---------------------------------------------------------------- automation
_NOREPLY_LOCAL = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|donotreply|notifications?|alerts?|"
    r"mailer[-_.]?daemon|postmaster|bounce|auto(mated)?|system|noreply|news|"
    r"updates?|info[-_.]?bot|support[-_.]?bot|robot|daemon)(\+.*)?$", re.I)

_BULK_DOMAINS = (
    "mailchimp", "sendgrid", "mailgun", "constantcontact", "hubspotemail",
    "salesforce", "intercom", "zendesk", "mandrillapp", "sparkpostmail",
    "amazonses", "klaviyomail", "sendinblue", "campaign-archive",
)

_MARKETING_SUBJECT = re.compile(
    r"(unsubscribe|newsletter|% off|sale ends|flash sale|webinar|"
    r"you'?re invited|limited time|black friday|cyber monday|"
    r"weekly digest|daily digest|your receipt|invoice from|order confirmation|"
    r"shipping confirmation|password reset|verify your|security alert|"
    r"out of office|automatic reply|undeliverable|delivery status notification)", re.I)


_BOUNCE_PREFIX = re.compile(
    r"^\s*(?:undeliverable|undelivered mail returned to sender|returned mail|"
    r"delivery status notification(?:\s*\([^)]*\))?|mail delivery failed|"
    r"failure notice|message not delivered|delivery failure)\s*[:\-]?\s*", re.I)


def bounced_subject(subject):
    """The original subject a bounce is reporting on, or None.

    Bounce notices are almost always "Undeliverable: <original subject>". When
    the failed address isn't quotable from the body, this is what lets us match
    the bounce back to the message it concerns.
    """
    s = (subject or "").strip()
    stripped = _BOUNCE_PREFIX.sub("", s)
    if stripped and stripped != s:
        return normalize_subject(stripped)
    return None


_BOUNCE_SUBJECT = re.compile(
    r"(undeliverable|delivery (?:status notification|failure|has failed)|"
    r"returned mail|mail delivery (?:failed|subsystem)|message not delivered|"
    r"failure notice|address not found)", re.I)

_OOO_SUBJECT = re.compile(
    r"(out of (?:the )?office|automatic reply|auto(?:matic)?[- ]?response|"
    r"away from (?:my |the )?(?:desk|office)|on (?:vacation|leave|holiday)|"
    r"maternity leave|parental leave)", re.I)


def bounce_reason(headers, from_addr, subject, body=""):
    """Why this looks like a delivery failure, or None.

    A bounce matters far beyond tidiness: it means a message the business
    believes it sent was never received. Mistaking one for a customer's silence
    produces a finding that blames the wrong party for the wrong thing.
    """
    h = {k.lower(): (v or "") for k, v in (headers or {}).items()}
    local = (from_addr or "").split("@", 1)[0].lower()
    if local in ("mailer-daemon", "postmaster", "mail-daemon"):
        return f"delivery failure reported by {from_addr}"
    if h.get("content-type", "").lower().startswith("multipart/report") or \
            "delivery-status" in h.get("content-type", "").lower():
        return "delivery status notification"
    if _BOUNCE_SUBJECT.search(subject or ""):
        return f"delivery failure ({(subject or '').strip()[:60]})"
    if re.search(r"\b(550|551|552|553|554)\b.{0,40}(user unknown|no such user|"
                 r"does not exist|mailbox unavailable|recipient rejected)", body or "", re.I):
        return "SMTP permanent failure in the message body"
    return None


def failed_recipients(headers, body, exclude=()):
    """Which addresses a bounce says could not be reached.

    A bounce almost never threads with the message it is about — different
    subject, no References — so without pulling the failed address out of it,
    the original conversation never learns its mail didn't land. The address is
    in `X-Failed-Recipients` when the server is well behaved, and in the body
    otherwise.
    """
    h = {k.lower(): (v or "") for k, v in (headers or {}).items()}
    out, seen = [], set()
    for raw in (h.get("x-failed-recipients", ""), h.get("original-recipient", ""),
                h.get("final-recipient", "")):
        for m in _ADDR_RE.finditer(raw):
            a = m.group(0).lower()
            if a not in seen:
                seen.add(a)
                out.append(a)
    if out:
        return out
    skip = {s.lower() for s in exclude}
    for m in _ADDR_RE.finditer(body or ""):
        a = m.group(0).lower()
        local = a.split("@", 1)[0]
        if a in seen or a in skip or _NOREPLY_LOCAL.match(local):
            continue
        seen.add(a)
        out.append(a)
    return out[:3]


def out_of_office_reason(headers, subject):
    """Why this looks like an out-of-office auto-reply, or None.

    The counterparty answered — they just aren't there. Reporting "they never
    replied" in that situation is simply false, and an owner who spots one such
    claim reasonably distrusts the next hundred.
    """
    h = {k.lower(): (v or "") for k, v in (headers or {}).items()}
    if h.get("x-autoreply") or h.get("x-autorespond"):
        return "automatic out-of-office reply"
    if h.get("auto-submitted", "").lower().startswith("auto-replied"):
        return "automatic out-of-office reply"
    if _OOO_SUBJECT.search(subject or ""):
        return f"auto-reply ({(subject or '').strip()[:60]})"
    return None


def classify_automation(headers, from_addr, subject):
    """Why we believe a message is machine-generated, or None when it looks human.

    Returned as a reason string so a finding can always explain itself and a
    human can tell us we got it wrong.
    """
    h = {k.lower(): (v or "") for k, v in (headers or {}).items()}
    if h.get("list-unsubscribe") or h.get("list-id"):
        return "bulk mailing list (List-Unsubscribe header)"
    if h.get("auto-submitted", "").lower() not in ("", "no"):
        return "auto-generated (Auto-Submitted header)"
    if h.get("precedence", "").lower() in ("bulk", "list", "junk"):
        return f"bulk mail (Precedence: {h['precedence']})"
    if h.get("x-autoreply") or h.get("x-autorespond") or h.get("x-auto-response-suppress"):
        return "automatic reply"
    if h.get("x-mailer", "").lower().startswith(("mailchimp", "sendgrid", "hubspot")):
        return f"marketing platform ({h['x-mailer'].split()[0]})"
    if h.get("content-type", "").lower().startswith("text/calendar") or h.get("x-ms-scheduling"):
        return "calendar invite"
    local = (from_addr or "").split("@", 1)[0]
    if _NOREPLY_LOCAL.match(local or ""):
        return f"no-reply sender ({from_addr})"
    dom = domain_of(from_addr)
    for b in _BULK_DOMAINS:
        if b in dom:
            return f"sent through a bulk email provider ({dom})"
    if _MARKETING_SUBJECT.search(subject or ""):
        return "transactional or marketing subject line"
    return None


# ---------------------------------------------------------------- body text
_QUOTE_MARKERS = [
    re.compile(r"^\s*On .{5,120}\bwrote:\s*$", re.I | re.M),
    re.compile(r"^\s*On .{5,80},? at .{3,40},? .{1,80}\bwrote:\s*$", re.I | re.M),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.I | re.M),
    re.compile(r"^\s*_{5,}\s*$", re.M),
    re.compile(r"^\s*From:\s*.+\n\s*(Sent|Date):\s*.+$", re.I | re.M),
    re.compile(r"^\s*\*?From:\*?\s*.{3,120}$\n^\s*\*?(Sent|Date):\*?", re.I | re.M),
    re.compile(r"^\s*El .{5,80} escribió:\s*$", re.I | re.M),
]

_SIG_MARKERS = [
    re.compile(r"^\s*(Sent from my (iPhone|iPad|Android|Samsung|mobile device))\s*$", re.I | re.M),
    re.compile(r"^\s*(Best regards|Kind regards|Warm regards|Regards|Thanks|Thank you|"
               r"Sincerely|Cheers|Best),?\s*$", re.I | re.M),
]


def strip_quoted(body):
    """Everything the author actually typed, with the quoted history removed.

    Returns (new_text, quoted_text). Conservative on purpose: if stripping would
    leave almost nothing, we keep the original — losing the real content is a
    worse error than carrying some quoted text.
    """
    if not body:
        return "", ""
    text = body.replace("\r\n", "\n")
    cut = len(text)
    for rx in _QUOTE_MARKERS:
        m = rx.search(text)
        if m and m.start() < cut:
            cut = m.start()
    # ">"-quoted blocks: cut at the first run of quoted lines near the end.
    lines = text.split("\n")
    run = None
    for i, ln in enumerate(lines):
        if ln.startswith(">"):
            run = i if run is None else run
        elif ln.strip() and run is not None:
            run = None
    if run is not None:
        off = len("\n".join(lines[:run]))
        cut = min(cut, off)
    head = text[:cut].strip()
    if len(head) < 12 and len(text.strip()) > len(head):
        return text.strip(), ""
    return head, text[cut:].strip()


_SIG_DELIM = re.compile(r"^-- ?$", re.M)


def strip_signature(text):
    """Drop a trailing signature block so contact-detail boilerplate doesn't get
    mistaken for message content.

    A line containing exactly "--" is the RFC 3676 signature delimiter and means
    *everything after this is a signature*, wherever it appears. It gets cut
    unconditionally: a one-word reply followed by a six-line footer is extremely
    common, and treating the footer as content turns "Thanks!" into an unanswered
    question. The softer markers ("Best regards", "Sent from my iPhone") are only
    honoured near the end, because they also occur mid-message.
    """
    if not text:
        return ""
    best = len(text)
    m = _SIG_DELIM.search(text)
    if m and m.start() > 0:
        best = m.start()
    for rx in _SIG_MARKERS:
        for m in rx.finditer(text):
            if m.start() > len(text) * 0.55:
                best = min(best, m.start())
    out = text[:best].strip()
    return out if out else text.strip()


def clean_body(raw):
    """Author-written text only: quoted history and signature removed."""
    body, _quoted = strip_quoted(raw)
    return strip_signature(body)


def snippet_of(text, limit=280):
    s = re.sub(r"\s+", " ", (text or "")).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def html_to_text(html):
    """Good-enough HTML → text. Keeps block boundaries as newlines so the
    quote/signature heuristics above still see line structure."""
    if not html:
        return ""
    s = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|blockquote)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", s).strip()
