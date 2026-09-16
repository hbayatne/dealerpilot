"""
HTTP API + the Control Center.

Authorization shape, which is the part worth reading: there is no implicit
"current organization". Every org-scoped route resolves (user, org_id) into a
role through `require_org`, and a user with no membership gets a 404 — not a 403,
which would confirm the org exists. There is no query in db.py that returns
business data without an org filter, so a missing scope is a crash, not a leak.
"""
import asyncio
import os
import secrets

from fastapi import (BackgroundTasks, Cookie, Depends, FastAPI, HTTPException,
                     Request, Response)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional

from chaos import (ai, attention, auth, brief as brief_mod, crypto, db, demo,
                   entitlements, memory, pipeline, ratelimit, scan as scan_mod,
                   scheduler, score as score_mod, website)
from chaos.brand import BRAND
from chaos.detect import inventory as inventory_rules, rules
from chaos.ingest import dealercenter, imap_source

app = FastAPI(title=BRAND.name, docs_url="/api/docs", openapi_url="/api/openapi.json")
db.init()


@app.on_event("startup")
async def _start_scheduler():
    """Continuous monitoring. Disabled when CHAOS_SCAN_INTERVAL_HOURS=0, and in
    tests — importing the app must never start background work."""
    if scheduler.enabled():
        asyncio.create_task(scheduler.loop())

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
COOKIE = "chaos_session"
SECURE_COOKIES = os.environ.get("CHAOS_SECURE_COOKIES", "1") != "0"


# ---------------------------------------------------------------- models
class Creds(BaseModel):
    email: str
    password: str
    name: Optional[str] = None
    # Only consulted on sign-up, and only when CHAOS_SIGNUP_CODE is set.
    code: Optional[str] = None


class OrgIn(BaseModel):
    name: str
    website: Optional[str] = ""
    industry: Optional[str] = ""
    timezone: Optional[str] = "UTC"
    domains: Optional[List[str]] = None


class ScanIn(BaseModel):
    url: str


class MailboxIn(BaseModel):
    email: str
    password: str
    host: Optional[str] = None
    port: Optional[int] = None
    folders: Optional[List[str]] = None


class InventoryIn(BaseModel):
    # The export arrives as text rather than a multipart upload: the browser reads
    # the file locally and posts its contents, which keeps the dependency list at
    # four packages. A DealerCenter export is a few hundred KB of CSV.
    content: str
    filename: Optional[str] = None
    # Whether recon cost is added on top of the cost column. None means "decide
    # from the column name" (see dealercenter._should_add_recon); a dealer whose
    # export disagrees sets it explicitly at import time.
    add_recon: Optional[bool] = None


class FeedbackIn(BaseModel):
    verdict: str
    note: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    resolution: Optional[str] = None


class AssignIn(BaseModel):
    user_id: Optional[int] = None


class MergeIn(BaseModel):
    keep_id: int
    drop_id: int


class RejectIn(BaseModel):
    a_id: int
    b_id: int


class DomainsIn(BaseModel):
    domains: List[str]


# ---------------------------------------------------------------- auth deps
def current_user(chaos_session: Optional[str] = Cookie(None)):
    user = db.user_for_session(chaos_session)
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    return user


def client_key(request: Request):
    """Who to rate-limit. Honours X-Forwarded-For only when explicitly told to
    trust a proxy — otherwise any client could spoof the header and get a fresh
    bucket for every attempt, which is worse than no limit at all."""
    if os.environ.get("CHAOS_TRUST_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "-"


def guard(request: Request, action: str, identifier=None):
    ok, retry = ratelimit.check(action, identifier or client_key(request))
    if not ok:
        raise HTTPException(429, f"Too many attempts. Try again in {retry} seconds.",
                            headers={"Retry-After": str(retry)})


def _set_cookie(response, token):
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        secure=SECURE_COOKIES, max_age=60 * 60 * 24 * 30, path="/")


def require_org(org_id: int, user=Depends(current_user), minimum="readonly"):
    """Resolve (user, org) to a role, or 404.

    404 rather than 403 on purpose: a 403 tells an attacker the organization
    exists, which is itself information they should not have.
    """
    role = db.membership(user["id"], org_id)
    if not role:
        raise HTTPException(404, "Not found.")
    if not auth.role_at_least(role, minimum):
        raise HTTPException(403, "Your role doesn't allow that.")
    org = db.get_org(org_id)
    if not org:
        raise HTTPException(404, "Not found.")
    return {"user": user, "org": org, "role": role}


def _need(ctx, minimum):
    if not auth.role_at_least(ctx["role"], minimum):
        raise HTTPException(403, "Your role doesn't allow that.")


# ---------------------------------------------------------------- public
@app.get("/api/health")
def health():
    return {"ok": True, "brand": BRAND.public(), "ai": ai.status(),
            "secrets": crypto.status(),
            "signup_code_required": auth.signup_code_required(),
            "database": "postgres" if db.IS_PG else "sqlite"}


@app.get("/api/brand")
def brand():
    return BRAND.public()


@app.get("/api/plans")
def plans():
    return {"plans": entitlements.public_plans()}


@app.post("/api/scan/website")
def public_website_scan(body: ScanIn, request: Request):
    """The free scan. No account required — this is the front door."""
    guard(request, "website_scan")
    db.track("website_scan_started", url=body.url)
    try:
        website.normalize_url(body.url)
    except website.UnsafeTarget as e:
        raise HTTPException(400, str(e))
    scan_id, result = scan_mod.website_scan(body.url, share=True)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return {"scan_id": scan_id, "result": result}


@app.get("/api/scan/shared/{token}")
def shared_scan(token: str):
    """A scan the owner explicitly chose to share. Never exposes findings from
    a connected mailbox — only the public website scan can be shared."""
    s = db.scan_by_token(token)
    if not s or s.get("kind") != "website":
        raise HTTPException(404, "Not found.")
    return {"scan": {"target": s["target"], "created_at": s["created_at"],
                     "result": s["result"]}}


# ---------------------------------------------------------------- accounts
@app.post("/api/signup")
def signup(body: Creds, response: Response, request: Request):
    guard(request, "signup")
    token, uid, err = auth.signup(body.email, body.password, body.name, body.code)
    if err:
        raise HTTPException(400, err)
    _set_cookie(response, token)
    db.track("signup", user_id=uid)
    return {"ok": True}


@app.post("/api/login")
def login(body: Creds, response: Response, request: Request):
    # Limited per source and per account: per-source alone lets a botnet spread
    # attempts across addresses, per-account alone lets one source walk a user list.
    guard(request, "login")
    guard(request, "login", f"acct:{(body.email or '').strip().lower()}")
    token, uid, err = auth.login(body.email, body.password)
    if err:
        raise HTTPException(401, err)
    _set_cookie(response, token)
    db.track("login", user_id=uid)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, chaos_session: Optional[str] = Cookie(None)):
    if chaos_session:
        db.delete_session(chaos_session)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    orgs = db.orgs_for_user(user["id"])
    return {"user": {"id": user["id"], "email": user["email"], "name": user.get("name")},
            "orgs": orgs}


# ---------------------------------------------------------------- orgs
@app.post("/api/orgs")
def create_org(body: OrgIn, user=Depends(current_user)):
    oid = db.create_org(body.name, body.website, body.industry, user_id=user["id"],
                        timezone=body.timezone, domains=body.domains or [])
    db.track("org_created", org_id=oid, user_id=user["id"], industry=body.industry)
    db.audit(oid, user["id"], "org.create", f"org:{oid}")
    return {"org": db.get_org(oid)}


@app.get("/api/orgs/{org_id}")
def get_org(org_id: int, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    return {"org": ctx["org"], "role": ctx["role"], "plan": entitlements.describe(ctx["org"])}


@app.put("/api/orgs/{org_id}")
def update_org(org_id: int, body: OrgIn, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "admin")
    db.update_org(org_id, name=body.name, website=body.website, industry=body.industry,
                  timezone=body.timezone,
                  **({"domains": body.domains} if body.domains is not None else {}))
    db.audit(org_id, user["id"], "org.update", f"org:{org_id}")
    return {"org": db.get_org(org_id)}


@app.put("/api/orgs/{org_id}/domains")
def set_domains(org_id: int, body: DomainsIn, user=Depends(current_user)):
    """Confirm which email domains are the business's own.

    This one setting decides what counts as inbound, so onboarding proposes it
    from the mailbox and asks the user to confirm rather than making them type it.
    """
    ctx = require_org(org_id, user)
    _need(ctx, "admin")
    cleaned = [d.strip().lower().lstrip("@") for d in body.domains if d.strip()]
    db.update_org(org_id, domains=cleaned)
    db.audit(org_id, user["id"], "org.domains", f"org:{org_id}", ",".join(cleaned))
    return {"org": db.get_org(org_id)}


@app.get("/api/orgs/{org_id}/members")
def members(org_id: int, user=Depends(current_user)):
    require_org(org_id, user)
    return {"members": db.members(org_id)}


# ---------------------------------------------------------------- integrations
@app.get("/api/orgs/{org_id}/jobs")
def jobs(org_id: int, user=Depends(current_user)):
    """Sync health. A business that believes it is being watched while the sync
    broke three weeks ago is worse off than one that knows it isn't."""
    require_org(org_id, user)
    return {"jobs": db.job_history(org_id, limit=25),
            "scheduler": {"enabled": scheduler.enabled(),
                          "interval_hours": scheduler.INTERVAL_HOURS}}


@app.get("/api/orgs/{org_id}/integrations")
def list_integrations(org_id: int, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    return {"integrations": db.integrations(org_id),
            "jobs": db.job_history(org_id, limit=5),
            "scheduler": {"enabled": scheduler.enabled(),
                          "interval_hours": scheduler.INTERVAL_HOURS},
            "secrets_ready": crypto.available(),
            "secrets_status": crypto.status(),
            "capabilities": sorted(score_mod.capabilities(org_id)),
            "available": _catalog(ctx["org"])}


def _catalog(org):
    """What can be connected, and what each unlocks. The upsell is the honesty:
    every uncconnected system is a named blind spot."""
    return [
        {"kind": "imap", "label": "Email (IMAP)", "status": "available",
         "unlocks": "Unanswered customers, broken promises, stale opportunities",
         "note": "Works today with a Gmail or Microsoft 365 app password."},
        {"kind": "gmail", "label": "Gmail (OAuth)", "status": "planned",
         "unlocks": "Same as IMAP, without an app password",
         "note": "Needs Google OAuth app verification."},
        {"kind": "google_calendar", "label": "Google Calendar", "status": "planned",
         "unlocks": "Missed appointments, promised meetings, scheduling conflicts"},
        {"kind": "dealercenter", "label": "DealerCenter inventory", "status": "available",
         "unlocks": "Capital tied up in aged units, margin, and which aged cars "
                    "people are still asking about",
         "note": "Upload your Active Inventory export. Include the cost column."},
        {"kind": "quickbooks", "label": "QuickBooks Online", "status": "planned",
         "unlocks": "Aging receivables, duplicate charges, vendor price creep"},
        {"kind": "hubspot", "label": "HubSpot CRM", "status": "planned",
         "unlocks": "Pipeline reconciliation — where the CRM and reality disagree"},
        {"kind": "google_business", "label": "Google Business Profile", "status": "planned",
         "unlocks": "Unanswered reviews and recurring complaint themes"},
    ]


@app.post("/api/orgs/{org_id}/integrations/imap/check")
def check_mailbox(org_id: int, body: MailboxIn, request: Request,
                  user=Depends(current_user)):
    """Verify mailbox credentials before storing anything."""
    ctx = require_org(org_id, user)
    _need(ctx, "admin")
    guard(request, "imap_check", f"org:{org_id}")
    host, port = (body.host, body.port) if body.host else imap_source.guess_host(body.email)
    ok, detail = imap_source.check(host, port, body.email, body.password)
    return {"ok": ok, "detail": detail, "host": host, "port": port}


@app.post("/api/orgs/{org_id}/integrations/imap")
def connect_mailbox(org_id: int, body: MailboxIn, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "admin")
    if not crypto.available():
        raise HTTPException(503, f"Credentials cannot be stored: {crypto.status()}")
    host, port = (body.host, body.port) if body.host else imap_source.guess_host(body.email)
    ok, detail = imap_source.check(host, port, body.email, body.password)
    if not ok:
        raise HTTPException(400, detail)
    db.upsert_integration(
        org_id, "imap", label=body.email,
        config={"host": host, "port": port, "user": body.email,
                "folders": body.folders},
        secret=crypto.encrypt(body.password))
    db.track("integration_connected", org_id=org_id, user_id=user["id"], kind="imap")
    db.audit(org_id, user["id"], "integration.connect", "imap", body.email)
    return {"ok": True, "detail": detail}


def _recon_pref(org_id, body):
    """The recon choice for this upload: what was asked for, else what was used
    last time. Two exports of the same lot costed differently would move every
    margin in the product without a word of explanation."""
    if body.add_recon is not None:
        return bool(body.add_recon)
    saved = (db.integration(org_id, "dealercenter") or {}).get("config") or {}
    v = saved.get("add_recon")
    return None if v is None else bool(v)


@app.post("/api/orgs/{org_id}/inventory/preview")
def preview_inventory(org_id: int, body: InventoryIn, user=Depends(current_user)):
    """Show what we understood in this export — before importing anything.

    The point of this step is the cost column. A dealer should find out here that
    we couldn't see their cost, not after a dashboard has quietly under-reported
    their capital by half.
    """
    ctx = require_org(org_id, user)
    _need(ctx, "manager")
    try:
        return {"preview": dealercenter.describe(body.content or "",
                                                 add_recon=_recon_pref(org_id, body))}
    except Exception as e:
        raise HTTPException(400, f"That file couldn't be read: {str(e)[:160]}")


@app.post("/api/orgs/{org_id}/inventory/import")
def import_inventory(org_id: int, body: InventoryIn, user=Depends(current_user)):
    """Import a DealerCenter export. Idempotent on VIN — re-uploading updates."""
    ctx = require_org(org_id, user)
    _need(ctx, "manager")
    add_recon = _recon_pref(org_id, body)
    try:
        rows = dealercenter.parse(body.content or "", add_recon=add_recon)
    except Exception as e:
        raise HTTPException(400, f"That file couldn't be read: {str(e)[:160]}")
    if not rows:
        raise HTTPException(400, "No vehicles were found in that file.")
    created = updated = 0
    for v in rows:
        _vid, is_new = db.upsert_vehicle(org_id, v)
        created += 1 if is_new else 0
        updated += 0 if is_new else 1
    basis = dealercenter.describe(body.content or "", add_recon=add_recon)
    db.upsert_integration(org_id, "dealercenter", label=body.filename or "inventory export",
                          config={"last_file": body.filename,
                                  "last_rows": len(rows),
                                  # Remembered so the next export is costed the
                                  # same way, rather than silently switching
                                  # basis and moving every margin figure.
                                  "add_recon": add_recon})
    db.audit(org_id, user["id"], "inventory.import", f"org:{org_id}",
             f"{created} new, {updated} updated from {body.filename or 'upload'} — "
             f"{basis['cost_basis']['sentence']}")
    db.track("inventory_imported", org_id=org_id, user_id=user["id"], rows=len(rows))
    return {"imported": len(rows), "created": created, "updated": updated,
            "cost_basis": basis["cost_basis"], "coverage": basis["coverage"]}


@app.get("/api/orgs/{org_id}/inventory")
def inventory(org_id: int, status: Optional[str] = None, user=Depends(current_user)):
    require_org(org_id, user)
    rows = db.vehicles(org_id, status=status)
    import datetime
    today = datetime.date.today()
    for v in rows:
        v["days_in_stock"] = inventory_rules._days_in_stock(v, today)
        v["margin_pct"] = inventory_rules.margin_pct(v)
    return {"vehicles": rows,
            "stats": score_mod._inventory_measurements(org_id, db.now())}


@app.delete("/api/orgs/{org_id}/integrations/{kind}")
def disconnect(org_id: int, kind: str, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "admin")
    db.delete_integration(org_id, kind)
    db.audit(org_id, user["id"], "integration.disconnect", kind)
    return {"ok": True}


# ---------------------------------------------------------------- scanning
_RUNNING = {}


@app.post("/api/orgs/{org_id}/scan")
def start_scan(org_id: int, background: BackgroundTasks, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "employee")
    if _RUNNING.get(org_id):
        return {"scan_id": _RUNNING[org_id], "already_running": True}
    scan_id = db.create_scan(org_id, "full", ctx["org"].get("website") or "")
    _RUNNING[org_id] = scan_id
    db.track("scan_started", org_id=org_id, user_id=user["id"])

    def _work():
        try:
            scan_mod.full_scan(ctx["org"], scan_id=scan_id)
        finally:
            _RUNNING.pop(org_id, None)

    background.add_task(_work)
    return {"scan_id": scan_id, "already_running": False}


@app.get("/api/orgs/{org_id}/scan/{scan_id}")
def scan_status(org_id: int, scan_id: int, user=Depends(current_user)):
    require_org(org_id, user)
    s = db.get_scan(scan_id, org_id)
    if not s:
        raise HTTPException(404, "Not found.")
    return {"scan": s}


@app.get("/api/orgs/{org_id}/scans")
def scan_history(org_id: int, user=Depends(current_user)):
    require_org(org_id, user)
    return {"scans": db.scans(org_id)}


# ---------------------------------------------------------------- the report
@app.get("/api/orgs/{org_id}/report")
def report(org_id: int, user=Depends(current_user)):
    require_org(org_id, user)
    return scan_mod.report(org_id)


@app.get("/api/orgs/{org_id}/score")
def score(org_id: int, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    latest = db.latest_score(org_id)
    return {"score": latest, "history": db.score_history(org_id),
            "methodology": score_mod.METHODOLOGY,
            "live": score_mod.compute(org_id,
                                      website_result=scan_mod._latest_website_result(org_id))}


@app.get("/api/orgs/{org_id}/brief")
def morning_brief(org_id: int, format: str = "json", user=Depends(current_user)):
    """The Morning Brief — assembled from counted facts, not written by a model."""
    require_org(org_id, user)
    b = brief_mod.build(org_id)
    db.track("brief_viewed", org_id=org_id, user_id=user["id"])
    if format == "text":
        return Response(brief_mod.render_text(b), media_type="text/plain")
    return {"brief": b, "text": brief_mod.render_text(b)}


# ---------------------------------------------------------------- findings
@app.get("/api/orgs/{org_id}/findings")
def findings(org_id: int, status: Optional[str] = None, category: Optional[str] = None,
             assigned_to: Optional[int] = None, mine: bool = False,
             limit: int = 100, offset: int = 0, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    if mine:
        assigned_to = user["id"]
    rows = db.findings(org_id, status=status, category=category, limit=limit,
                       offset=offset, assigned_to=assigned_to)
    ranked = attention.rank(org_id, rows)
    cap = entitlements.limit(ctx["org"], "findings_visible")
    shown = ranked[:cap] if cap else ranked
    return {"findings": shown, "withheld": max(0, len(ranked) - len(shown)),
            "counts": db.finding_counts(org_id)}


@app.get("/api/orgs/{org_id}/findings/{fid}")
def finding_detail(org_id: int, fid: int, user=Depends(current_user)):
    require_org(org_id, user)
    f = db.get_finding(org_id, fid)
    if not f:
        raise HTTPException(404, "Not found.")
    attention_score, terms = attention.score_finding(f)
    f["attention"] = attention_score
    entity = db.get_entity(org_id, f["entity_id"]) if f.get("entity_id") else None
    db.track("finding_viewed", org_id=org_id, user_id=user["id"], detector=f["detector"])
    return {"finding": f, "evidence": db.evidence_for(org_id, fid),
            "attention_terms": terms, "entity": entity,
            "profile": memory.profile(org_id, f["entity_id"]) if f.get("entity_id") else None}


@app.post("/api/orgs/{org_id}/findings/{fid}/status")
def set_status(org_id: int, fid: int, body: StatusIn, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "employee")
    allowed = {"new", "reviewing", "approved", "assigned", "waiting_external",
               "resolved", "dismissed", "false_positive"}
    if body.status not in allowed:
        raise HTTPException(400, "Unknown status.")
    if not db.get_finding(org_id, fid):
        raise HTTPException(404, "Not found.")
    db.set_finding_status(org_id, fid, body.status, body.resolution)
    db.audit(org_id, user["id"], f"finding.{body.status}", f"finding:{fid}")
    db.track("finding_status", org_id=org_id, user_id=user["id"], status=body.status)
    return {"ok": True}


@app.post("/api/orgs/{org_id}/findings/{fid}/feedback")
def feedback(org_id: int, fid: int, body: FeedbackIn, user=Depends(current_user)):
    """'That's not right' — the signal that makes the detectors better."""
    ctx = require_org(org_id, user)
    _need(ctx, "employee")
    if body.verdict not in ("useful", "false_positive", "not_now"):
        raise HTTPException(400, "Unknown verdict.")
    if not db.get_finding(org_id, fid):
        raise HTTPException(404, "Not found.")
    db.add_feedback(org_id, fid, user["id"], body.verdict, body.note)
    if body.verdict == "false_positive":
        db.set_finding_status(org_id, fid, "false_positive", body.note)
    db.track("finding_feedback", org_id=org_id, user_id=user["id"], verdict=body.verdict)
    return {"ok": True}


@app.post("/api/orgs/{org_id}/findings/{fid}/assign")
def assign(org_id: int, fid: int, body: AssignIn, user=Depends(current_user)):
    """Hand a finding to someone. `user_id: null` puts it back in the pool."""
    ctx = require_org(org_id, user)
    _need(ctx, "manager")
    if not db.get_finding(org_id, fid):
        raise HTTPException(404, "Not found.")
    if body.user_id is not None and not db.membership(body.user_id, org_id):
        # Never assign work to someone outside the organization.
        raise HTTPException(400, "That person is not a member of this organization.")
    db.assign_finding(org_id, fid, body.user_id)
    db.audit(org_id, user["id"], "finding.assign", f"finding:{fid}",
             f"to user {body.user_id}" if body.user_id else "unassigned")
    db.track("finding_assigned", org_id=org_id, user_id=user["id"])
    return {"ok": True}


@app.get("/api/orgs/{org_id}/workload")
def workload(org_id: int, user=Depends(current_user)):
    """Open work per assignee.

    Framed around outcomes, never individuals: "twelve client commitments are
    unresolved" is management information; "Dana is bad at her job" is a
    surveillance product, and we are not building one.
    """
    require_org(org_id, user)
    return {"workload": db.workload(org_id), "members": db.members(org_id)}


@app.get("/api/orgs/{org_id}/quality")
def quality(org_id: int, user=Depends(current_user)):
    """False-positive rates per detector — visible to the customer on purpose."""
    require_org(org_id, user)
    return {"detectors": db.feedback_stats(org_id)}


@app.post("/api/orgs/{org_id}/findings/{fid}/draft")
def draft(org_id: int, fid: int, user=Depends(current_user)):
    """An AI-written draft reply. Returned for review — never sent from here."""
    ctx = require_org(org_id, user)
    _need(ctx, "employee")
    f = db.get_finding(org_id, fid)
    if not f:
        raise HTTPException(404, "Not found.")
    if not entitlements.has(ctx["org"], "ai_drafts"):
        raise HTTPException(402, "Drafting is available on the Control plan.")
    thread = ""
    if f.get("entity_id"):
        for conv in db.conversations(org_id, limit=200):
            if conv.get("entity_id") == f["entity_id"]:
                for m in db.messages_in(org_id, conv["id"])[-8:]:
                    who = "Customer" if m["direction"] == "in" else "Us"
                    thread += f"{who} ({m['sent_at']}): {m.get('body') or ''}\n\n"
                break
    res = ai.draft_reply(ctx["org"], f, thread)
    db.track("draft_generated", org_id=org_id, user_id=user["id"], status=res.get("status"))
    return {"draft": res, "sent": False,
            "note": "This is a draft for you to review. Nothing has been sent."}


# ---------------------------------------------------------------- memory
@app.get("/api/orgs/{org_id}/entities")
def entities(org_id: int, kind: Optional[str] = None, limit: int = 200,
             user=Depends(current_user)):
    require_org(org_id, user)
    return {"entities": db.entities(org_id, kind=kind, limit=limit)}


@app.get("/api/orgs/{org_id}/entities/{eid}")
def entity_detail(org_id: int, eid: int, user=Depends(current_user)):
    require_org(org_id, user)
    prof = memory.profile(org_id, eid)
    if not prof:
        raise HTTPException(404, "Not found.")
    convs = [c for c in db.conversations(org_id, limit=500) if c.get("entity_id") == eid]
    return {**prof, "conversations": convs,
            "findings": [f for f in db.findings(org_id, limit=200)
                         if f.get("entity_id") == eid]}


@app.get("/api/orgs/{org_id}/merge-candidates")
def merge_candidates(org_id: int, user=Depends(current_user)):
    """Probable duplicate people, for a human to confirm. We never merge these
    silently — a wrong merge fuses two customers' histories."""
    require_org(org_id, user)
    return {"candidates": memory.merge_candidates(org_id)}


@app.post("/api/orgs/{org_id}/merge")
def do_merge(org_id: int, body: MergeIn, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "manager")
    memory.confirm_merge(org_id, body.keep_id, body.drop_id, user["id"])
    return {"ok": True}


@app.post("/api/orgs/{org_id}/not-same")
def not_same(org_id: int, body: RejectIn, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "employee")
    memory.reject_merge(org_id, body.a_id, body.b_id, user["id"])
    return {"ok": True}


@app.get("/api/orgs/{org_id}/conversations/{cid}")
def conversation(org_id: int, cid: int, user=Depends(current_user)):
    require_org(org_id, user)
    conv = db.conversation(org_id, cid)
    if not conv:
        raise HTTPException(404, "Not found.")
    return {"conversation": conv, "messages": db.messages_in(org_id, cid)}


@app.get("/api/orgs/{org_id}/commitments")
def commitments(org_id: int, state: Optional[str] = None, user=Depends(current_user)):
    require_org(org_id, user)
    return {"commitments": db.commitments(org_id, state=state)}


# ---------------------------------------------------------------- privacy
@app.get("/api/orgs/{org_id}/audit")
def audit_trail(org_id: int, user=Depends(current_user)):
    ctx = require_org(org_id, user)
    _need(ctx, "admin")
    return {"entries": db.audit_trail(org_id)}


@app.get("/api/orgs/{org_id}/transparency")
def transparency(org_id: int, user=Depends(current_user)):
    """What we read, why, what we keep, and what we can do. Verbatim, per
    integration. Trust is the product's main constraint."""
    require_org(org_id, user)
    return {"integrations": [
        {"kind": "imap", "reads": "Message headers and text bodies from your Inbox "
                                  "and Sent folders.",
         "why": "Threads, response times, promises and complaints cannot be seen "
                "from headers alone.",
         "stores": "Sender, recipients, subject, timestamp, and the text of the "
                   "message with quoted history removed.",
         "does_not_store": "Attachment contents, images, your password (the app "
                           "password is encrypted with AES-256-GCM and never "
                           "returned by any endpoint).",
         "can_do": "Read only. This integration cannot send, delete or modify "
                   "anything in your mailbox.",
         "revoke": "Disconnect here, and revoke the app password with your email "
                   "provider."}]}


@app.delete("/api/orgs/{org_id}/data")
def delete_data(org_id: int, user=Depends(current_user)):
    """Delete every ingested business record for this org. Irreversible."""
    ctx = require_org(org_id, user)
    _need(ctx, "owner")
    tables = ["evidence", "finding_feedback", "findings", "commitments", "events",
              "messages", "conversation_keys", "conversations", "identities",
              "entity_links", "merge_decisions", "entities", "scores", "scans",
              "integrations"]
    with db._conn() as c:
        for t in tables:
            c.execute(f"DELETE FROM {t} WHERE org_id=?", (org_id,))
    db.audit(org_id, user["id"], "data.delete_all", f"org:{org_id}")
    return {"ok": True, "deleted": tables}


# ---------------------------------------------------------------- demo
@app.post("/api/demo/dealer")
def create_dealer_demo(user=Depends(current_user)):
    """A sample dealership: a DealerCenter export plus the mailbox that goes with
    it, so the cross-system findings have both halves to work from."""
    import datetime
    from chaos import demo_dealer
    oid = db.create_org(demo_dealer.ORG["name"], demo_dealer.ORG["website"],
                        demo_dealer.ORG["industry"], user_id=user["id"],
                        domains=demo_dealer.ORG["domains"])
    org = db.get_org(oid)
    db.upsert_integration(oid, "imap", label="demo mailbox (sample data)",
                          config={"sample_data": True})
    db.upsert_integration(oid, "dealercenter", label="DealerCenter export (sample data)",
                          config={"sample_data": True})
    now = datetime.datetime.utcnow().replace(microsecond=0)
    csv_text, msgs, _ = demo_dealer.build(now)
    for v in dealercenter.parse(csv_text):
        db.upsert_vehicle(oid, v)
    pipeline.ingest(org, msgs)
    scan_mod.analyze(org, now_iso=now.isoformat(timespec="seconds"))
    db.track("demo_dealer_created", org_id=oid, user_id=user["id"])
    return {"org": db.get_org(oid), "banner": demo_dealer.DEMO_BANNER}


@app.post("/api/demo")
def create_demo(user=Depends(current_user)):
    """A fully populated demo organization, clearly labelled as demo data."""
    import datetime
    oid = db.create_org(demo.ORG["name"], demo.ORG["website"], demo.ORG["industry"],
                        user_id=user["id"], domains=demo.ORG["domains"])
    org = db.get_org(oid)
    db.upsert_integration(oid, "imap", label="demo mailbox (sample data)",
                          config={"sample_data": True})
    now = datetime.datetime.utcnow().replace(microsecond=0)
    msgs, _ = demo.build(now)
    pipeline.ingest(org, msgs)
    scan_mod.analyze(org, now_iso=now.isoformat(timespec="seconds"))
    db.track("demo_created", org_id=oid, user_id=user["id"])
    return {"org": db.get_org(oid), "banner": demo.DEMO_BANNER}


# ---------------------------------------------------------------- analytics
@app.get("/api/admin/funnel")
def funnel(user=Depends(current_user)):
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",")
              if e.strip()}
    if user["email"].lower() not in admins:
        raise HTTPException(404, "Not found.")
    return {"funnel": db.funnel()}


# ---------------------------------------------------------------- static
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/report/{token}")
def shared_report_page(token: str):
    return FileResponse(os.path.join(STATIC, "index.html"))
