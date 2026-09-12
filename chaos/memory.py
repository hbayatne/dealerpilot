"""
Business Memory — the entity graph, and the entity resolution that builds it.

The same human shows up as `john@gmail.com`, "John Smith", "J. Smith",
`+1 214 555 1234`, CRM customer 18491 and QuickBooks customer 662. Until those
are one node, nothing else in the product can reason about a business situation
— it just sees six unrelated records.

Resolution here is deliberately two-speed:

* **Deterministic merges** on identifiers that genuinely identify a person — an
  email address, a normalized phone number, an external system's customer id.
  These we apply automatically at high confidence.
* **Probabilistic candidates** on weaker evidence, chiefly name similarity plus
  a shared company. These are *never* merged silently. They surface as a
  suggestion a human confirms, because a wrong merge fuses two customers'
  histories and is close to unrecoverable from a user's point of view.

A human's `not_same` decision is durable: it is recorded and suppresses the
suggestion forever, so we never nag about a pair we were already corrected on.
"""
import re

from chaos import db

# Consumer mailbox providers. An address here tells us nothing about a company,
# so we must never manufacture a "Gmail" company entity from one.
FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "aol.com", "icloud.com", "me.com",
    "mac.com", "protonmail.com", "proton.me", "gmx.com", "mail.com", "zoho.com",
    "yandex.com", "att.net", "comcast.net", "verizon.net", "sbcglobal.net",
    "bellsouth.net", "cox.net", "charter.net", "earthlink.net", "hotmail.co.uk",
    "yahoo.co.uk", "163.com", "qq.com", "naver.com", "web.de", "free.fr",
}

_NAME_NOISE = re.compile(r"[^a-z\s'-]")
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "jr", "sr", "ii", "iii", "iv"}


# ------------------------------------------------------------------ helpers
def normalize_phone(raw):
    """US-centric E.164-ish digits. Returns None when it isn't a plausible number."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return digits
    if 7 <= len(digits) <= 15:
        return digits
    return None


def normalize_name(raw):
    """Lowercased given-name-first tokens, titles dropped.

    "Smith, John" is rewritten to "john smith": directory exports and CRMs use
    surname-first constantly, and every comparison below assumes a consistent
    ordering.
    """
    raw = (raw or "").strip()
    if raw.count(",") == 1:
        last, first = (part.strip() for part in raw.split(","))
        if last and first and not any(ch.isdigit() for ch in raw):
            raw = f"{first} {last}"
    n = _NAME_NOISE.sub(" ", raw.lower())
    parts = [p for p in n.split() if p and p.strip(".\'-") not in _TITLES]
    return " ".join(parts)


def name_from_email(addr):
    """A readable name guessed from the local part — 'john.smith' → 'John Smith'.
    Only used as a display fallback; never treated as identifying evidence."""
    local = (addr or "").split("@", 1)[0]
    local = re.sub(r"[+._-]+", " ", local)
    local = re.sub(r"\d+", "", local).strip()
    if not local or len(local) < 2:
        return addr or ""
    return " ".join(w.capitalize() for w in local.split())


def name_similarity(a, b):
    """0..1 similarity between two personal names, token-based.

    Token overlap beats edit distance here: "John Smith" and "Smith, John" are
    the same person, while "John Smith" and "John Baker" are usually not — so a
    shared surname counts for much more than a shared first name. Initials are
    matched too ("J. Smith" ~ "John Smith"), but at a discount, because an
    initial is genuinely weaker evidence than a full given name.
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    ta, tb = na.split(), nb.split()
    sa, sb = set(ta), set(tb)
    if sa == sb:
        return 1.0

    exact = sa & sb
    # Initial matches: a single letter standing in for a full token.
    initial_hits = 0
    for x in sa - exact:
        if len(x) == 1 and any(y.startswith(x) for y in sb - exact):
            initial_hits += 1
    for y in sb - exact:
        if len(y) == 1 and any(x.startswith(y) for x in sa - exact):
            initial_hits += 1
    matched = len(exact) + 0.75 * min(initial_hits, min(len(ta), len(tb)))
    if not matched:
        return 0.0

    base = matched / max(len(ta), len(tb))
    la, lb = ta[-1], tb[-1]
    ceiling = 0.95 if initial_hits else 1.0   # an initial is never certainty
    if la == lb:
        base = min(1.0, base + 0.15)          # shared surname: strong signal
    elif not (len(la) == 1 and lb.startswith(la)) and not (
            len(lb) == 1 and la.startswith(lb)):
        base *= 0.55                          # different surnames: weak
    return round(min(ceiling, base), 3)


def is_internal(org, addr):
    """True when this address belongs to the business itself."""
    dom = (addr or "").rsplit("@", 1)[-1].lower()
    return bool(dom) and dom in {d.lower().lstrip("@") for d in (org.get("domains") or [])}


# ------------------------------------------------------------------ resolution
def resolve_person(org_id, addr, name=None, seen_at=None, role=None, source="email",
                   own_domains=None):
    """Find or create the person behind an email address.

    The address is the deterministic key: same address, same person. A better
    display name upgrades the record, and a first/last-seen window is widened on
    every sighting so the graph knows how long a relationship has run.
    """
    addr = (addr or "").strip().lower()
    if not addr or "@" not in addr:
        return None
    found = db.find_by_identity(org_id, "email", addr)
    if found:
        if seen_at:
            db.touch_entity(org_id, found["id"], seen_at)
        # A real display name beats one we guessed from the local part.
        if name and _better_name(name, found.get("display_name"), addr):
            db.update_entity(org_id, found["id"], display_name=name.strip())
        if role and (found.get("role") in (None, "", "unknown")) and role != "unknown":
            db.update_entity(org_id, found["id"], role=role)
        return db.get_entity(org_id, found["id"])

    display = (name or "").strip() or name_from_email(addr)
    eid = db.create_entity(org_id, "person", display, role=role or "unknown",
                           confidence=1.0, seen_at=seen_at,
                           meta={"first_source": source})
    db.add_identity(org_id, eid, "email", addr, confidence=1.0, source=source)
    if name and normalize_name(name):
        db.add_identity(org_id, eid, "name", normalize_name(name), confidence=0.4,
                        source=source)
    company = resolve_company_for(org_id, addr, seen_at=seen_at, own_domains=own_domains)
    if company:
        db.link_entities(org_id, eid, company["id"], "works_at", confidence=0.8)
    return db.get_entity(org_id, eid)


def _better_name(new, current, addr):
    """Is `new` a better display name than what we already stored?"""
    new = (new or "").strip()
    if not new or "@" in new:
        return False
    if not current:
        return True
    # Anything beats the name we synthesized from the address.
    if current.strip().lower() == name_from_email(addr).strip().lower():
        return True
    return len(normalize_name(new).split()) > len(normalize_name(current).split())


# Email service providers. Mail arrives *through* these; they are not companies
# the business has a relationship with, and minting an entity for one is noise.
ESP_DOMAINS = {
    "mailchimp.com", "mailchimpapp.net", "sendgrid.net", "sendgrid.com",
    "mailgun.org", "mandrillapp.com", "sparkpostmail.com", "amazonses.com",
    "constantcontact.com", "klaviyomail.com", "sendinblue.com", "hubspotemail.net",
    "salesforce.com", "intercom-mail.com", "zendesk.com", "campaign-archive.com",
    "bounces.google.com", "email.mailgun.org",
}


def resolve_company_for(org_id, addr, seen_at=None, own_domains=None):
    """The company behind an email domain, for business domains only.

    Skips consumer mailboxes, email-service-provider domains, and the org's own
    domains — a business is not its own customer, and "Mailchimp" is not a
    company anyone here does business with.
    """
    dom = (addr or "").rsplit("@", 1)[-1].lower()
    if not dom or dom in FREEMAIL or dom in ESP_DOMAINS or "." not in dom:
        return None
    if dom in {d.lower().lstrip("@") for d in (own_domains or [])}:
        return None
    if any(dom.endswith("." + esp) for esp in ESP_DOMAINS):
        return None
    found = db.find_by_identity(org_id, "domain", dom)
    if found:
        if seen_at:
            db.touch_entity(org_id, found["id"], seen_at)
        return found
    label = dom.rsplit(".", 2)[0] if dom.count(".") > 1 else dom.split(".")[0]
    cid = db.create_entity(org_id, "company", label.replace("-", " ").title(),
                           role="unknown", confidence=0.7, seen_at=seen_at,
                           meta={"domain": dom})
    db.add_identity(org_id, cid, "domain", dom, confidence=1.0, source="email")
    return db.get_entity(org_id, cid)


def attach_phone(org_id, entity_id, raw_phone, source="email-signature"):
    """Record a phone number as an alternate identity. Deterministic: the same
    normalized number later resolves to this same person."""
    p = normalize_phone(raw_phone)
    if not p or len(p) < 10:
        return None
    return db.add_identity(org_id, entity_id, "phone", p, confidence=0.8, source=source)


# ------------------------------------------------------------------ suggestions
def merge_candidates(org_id, min_score=0.72, limit=25):
    """Pairs that are probably the same person, for a human to confirm.

    Evidence combined here: name similarity, a shared phone number, and a shared
    company. Nothing in this function writes — it only proposes. A pair already
    judged (either way) never comes back.
    """
    people = db.entities(org_id, kind="person", limit=800)
    by_id = {p["id"]: p for p in people}
    idents = {}
    for p in people:
        for i in db.identities_for(org_id, p["id"]):
            idents.setdefault(p["id"], []).append(i)

    def _vals(pid, kind):
        return {i["value"] for i in idents.get(pid, []) if i["kind"] == kind}

    companies = {}
    for p in people:
        companies[p["id"]] = {l["to_id"] for l in db.links_for(org_id, p["id"])
                              if l["relation"] == "works_at"}

    out = []
    ids = sorted(by_id)
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            if db.merge_decision(org_id, a, b):
                continue
            reasons, score = [], 0.0
            shared_phone = _vals(a, "phone") & _vals(b, "phone")
            if shared_phone:
                score += 0.6
                reasons.append(f"same phone number ({next(iter(shared_phone))})")
            sim = name_similarity(by_id[a]["display_name"], by_id[b]["display_name"])
            if sim >= 0.5:
                score += sim * 0.55
                reasons.append(
                    f"names match ({by_id[a]['display_name']} / {by_id[b]['display_name']})")
            shared_co = companies.get(a, set()) & companies.get(b, set())
            if shared_co and sim >= 0.5:
                score += 0.15
                reasons.append("same company")
            if score >= min_score and reasons:
                out.append({
                    "a": {"id": a, "name": by_id[a]["display_name"],
                          "emails": sorted(_vals(a, "email"))},
                    "b": {"id": b, "name": by_id[b]["display_name"],
                          "emails": sorted(_vals(b, "email"))},
                    "confidence": round(min(0.97, score), 3),
                    "reasons": reasons,
                })
    out.sort(key=lambda d: -d["confidence"])
    return out[:limit]


def confirm_merge(org_id, keep_id, drop_id, user_id=None):
    db.merge_entities(org_id, keep_id, drop_id)
    db.audit(org_id, user_id, "entity.merge", f"entity:{keep_id}", f"absorbed {drop_id}")


def reject_merge(org_id, a_id, b_id, user_id=None):
    db.record_merge_decision(org_id, a_id, b_id, "not_same", user_id)
    db.audit(org_id, user_id, "entity.not_same", f"entity:{a_id}", f"vs {b_id}")


def profile(org_id, entity_id):
    """Everything memory knows about one entity — the 'show me the person' view."""
    e = db.get_entity(org_id, entity_id)
    if not e:
        return None
    return {
        "entity": e,
        "identities": db.identities_for(org_id, entity_id),
        "links": db.links_for(org_id, entity_id),
    }
