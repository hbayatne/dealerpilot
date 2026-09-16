#!/usr/bin/env python3
"""
Create (or reuse) the Render service for this app and deploy it.

Run from GitHub Actions, not from a laptop: it needs RENDER_API_KEY, and the
key should live in repository secrets rather than anyone's shell history.

Idempotent on name. First run creates the Postgres instance and the web
service and generates the two secrets; later runs find what exists and just
trigger a deploy, so the invite code and the encryption key survive — a new
CHAOS_SECRET_KEY would make every stored mailbox credential unreadable.

Secrets are never printed. The generated invite code is readable in the Render
dashboard under the service's Environment tab; Actions logs are not the place
for it.
"""
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request

API = "https://api.render.com/v1"
KEY = os.environ.get("RENDER_API_KEY", "").strip()
SERVICE = os.environ.get("RENDER_SERVICE_NAME", "chaos-control").strip()
DB_NAME = os.environ.get("RENDER_DB_NAME", "chaos-db").strip()
REGION = os.environ.get("RENDER_REGION", "oregon").strip()
PLAN = os.environ.get("RENDER_PLAN", "starter").strip()
DB_PLAN = os.environ.get("RENDER_DB_PLAN", "basic_256mb").strip()
REPO = os.environ.get("RENDER_REPO", "").strip()
BRANCH = os.environ.get("RENDER_BRANCH", "main").strip()
WANT_DB = os.environ.get("RENDER_WITH_DATABASE", "1").strip() != "0"
WAIT_SECONDS = int(os.environ.get("RENDER_WAIT_SECONDS", "900"))


def call(method, path, body=None):
    """One Render API call. Failures print what Render actually said — an
    opaque 400 during a deploy is worse than no automation at all."""
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode() or "null"
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = (e.read().decode() or "")[:600]
        die(f"{method} {url} → HTTP {e.code}\n{detail}")
    except Exception as e:                                   # network, DNS, TLS
        die(f"{method} {url} → {type(e).__name__}: {e}")


def die(msg, hint=None):
    print(f"\n✗ {msg}", file=sys.stderr)
    if hint:
        print(f"\n  {hint}", file=sys.stderr)
    sys.exit(1)


def unwrap(rows, key):
    """Render list endpoints return [{"service": {...}}, …]; detail endpoints
    return the bare object. Accept both rather than guessing per endpoint."""
    out = []
    for row in rows or []:
        out.append(row.get(key, row) if isinstance(row, dict) else row)
    return out


def owner_id():
    owners = unwrap(call("GET", "/owners?limit=20"), "owner")
    if not owners:
        die("That API key can't see any Render owner.",
            "Check the key is a Render API key (Account Settings → API Keys).")
    wanted = os.environ.get("RENDER_OWNER", "").strip()
    if wanted:
        for o in owners:
            if wanted in (o.get("id"), o.get("name"), o.get("email")):
                return o["id"]
        die(f"No Render owner matching {wanted!r}.",
            "Owners visible: " + ", ".join(str(o.get("name")) for o in owners))
    if len(owners) > 1:
        die("This key can see several Render owners, so the target is ambiguous.",
            "Set RENDER_OWNER to one of: "
            + ", ".join(str(o.get("name")) for o in owners))
    return owners[0]["id"]


def find(kind, name):
    rows = unwrap(call("GET", f"/{kind}?name={name}&limit=50"),
                  "service" if kind == "services" else "postgres")
    return next((r for r in rows if r.get("name") == name), None)


def ensure_database(oid):
    """The Postgres instance, and the connection string to point the app at."""
    db = find("postgres", DB_NAME)
    if db:
        print(f"· database {DB_NAME} already exists ({db['id']})")
    else:
        print(f"· creating database {DB_NAME} ({DB_PLAN}, {REGION})")
        db = call("POST", "/postgres", {"name": DB_NAME, "ownerId": oid,
                                        "plan": DB_PLAN, "region": REGION,
                                        "version": "16"})
        db = db.get("postgres", db)
    info = call("GET", f"/postgres/{db['id']}/connection-info")
    url = info.get("internalConnectionString") or info.get("externalConnectionString")
    if not url:
        die("Render gave no connection string for the database.",
            "It may still be provisioning — re-run this job in a minute.")
    return url


def env_vars(existing, database_url):
    """Merge: keep every value the service already has — regenerating
    CHAOS_SECRET_KEY would orphan every stored credential — and fill in only
    what is missing."""
    have = {e.get("key"): e.get("value") for e in existing}
    out = dict(have)
    out.setdefault("CHAOS_SECRET_KEY", secrets.token_urlsafe(32))
    out.setdefault("CHAOS_SIGNUP_CODE", secrets.token_urlsafe(9))
    out["CHAOS_TRUST_PROXY"] = "1"      # Render terminates TLS ahead of the app
    if database_url:
        out["DATABASE_URL"] = database_url
    fresh = sorted(k for k in out if k not in have)
    if fresh:
        print("· generated: " + ", ".join(fresh) + " (read them in the dashboard)")
    return [{"key": k, "value": v} for k, v in sorted(out.items())]


def ensure_service(oid, database_url):
    svc = find("services", SERVICE)
    if svc:
        print(f"· service {SERVICE} already exists ({svc['id']})")
        current = unwrap(call("GET", f"/services/{svc['id']}/env-vars?limit=100"), "envVar")
        call("PUT", f"/services/{svc['id']}/env-vars", env_vars(current, database_url))
        return svc["id"]
    if not REPO:
        die("No repository URL to build from.", "Set RENDER_REPO, e.g. "
            "https://github.com/hbayatne/dealerpilot")
    print(f"· creating web service {SERVICE} ({PLAN}, {REGION}) from {REPO}@{BRANCH}")
    created = call("POST", "/services", {
        "type": "web_service", "name": SERVICE, "ownerId": oid,
        "repo": REPO, "branch": BRANCH, "autoDeploy": "yes",
        "envVars": env_vars([], database_url),
        "serviceDetails": {
            "env": "docker", "region": REGION, "plan": PLAN,
            "healthCheckPath": "/api/health",
            "envSpecificDetails": {"dockerfilePath": "./Dockerfile",
                                   "dockerContext": "."},
        },
    })
    svc = created.get("service", created)
    return svc["id"]


def deploy(sid):
    dep = call("POST", f"/services/{sid}/deploys", {"clearCache": "do_not_clear"})
    dep_id = dep.get("id") or dep.get("deploy", {}).get("id")
    print(f"· deploy {dep_id} started; waiting up to {WAIT_SECONDS // 60} minutes")
    deadline = time.time() + WAIT_SECONDS
    last = None
    while time.time() < deadline:
        time.sleep(15)
        status = call("GET", f"/services/{sid}/deploys/{dep_id}").get("status")
        if status != last:
            print(f"  {status}")
            last = status
        if status == "live":
            return True
        if status in ("build_failed", "update_failed", "canceled", "deactivated",
                      "pre_deploy_failed"):
            die(f"Deploy finished as {status}.",
                "Open the service's Logs tab in Render for the build output.")
    print("· still deploying when this job's patience ran out — "
          "check the Render dashboard", file=sys.stderr)
    return False


def main():
    if not KEY:
        die("RENDER_API_KEY is not set.",
            "Add it under the repository's Settings → Secrets and variables → Actions.")
    oid = owner_id()
    database_url = ensure_database(oid) if WANT_DB else None
    if not WANT_DB:
        print("· no database requested: the app will use SQLite, which on Render "
              "resets whenever the service is redeployed")
    sid = ensure_service(oid, database_url)
    live = deploy(sid)
    svc = call("GET", f"/services/{sid}")
    url = (svc.get("service", svc).get("serviceDetails") or {}).get("url")
    print("\n" + ("✓ live at " if live else "· service at ") + (url or "(no URL yet)"))
    print("  Sign-up needs the invite code: Render dashboard → the service → "
          "Environment → CHAOS_SIGNUP_CODE.")


if __name__ == "__main__":
    main()
