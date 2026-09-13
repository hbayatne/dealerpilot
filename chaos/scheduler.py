"""
The background scheduler — what makes monitoring continuous rather than
on-demand.

Without this the product only looks when someone asks it to, which means the
promise ("we find what you're missing") is only kept by customers who remember
to press a button. The ones who most need it are exactly the ones who won't.

Runs as an asyncio task inside the web process. That is the right trade at this
size — no broker to operate, no second deployment — but it has one real hazard:
with several workers, every worker runs its own scheduler and syncs the same
mailboxes. So each cycle is guarded by a lease in the shared database. One worker
wins, the rest skip, and the lease lapses on its own if that worker dies.

Nothing here fails silently. Every run records a `job_runs` row, and an
integration that errors carries the reason where the customer can read it — a
business believing it is being watched when the sync broke three weeks ago is
worse than not being watched at all.
"""
import asyncio
import os
import random
import socket
import time
import traceback

from chaos import db, scan as scan_mod

INTERVAL_HOURS = float(os.environ.get("CHAOS_SCAN_INTERVAL_HOURS", "6"))
# Space out orgs so a hundred tenants don't hit their mail providers together.
STAGGER_SECONDS = float(os.environ.get("CHAOS_SCAN_STAGGER_SECONDS", "20"))
LEASE_NAME = "scheduled_scan"

_HOLDER = f"{socket.gethostname()}:{os.getpid()}"


def enabled():
    """The scheduler is off when the interval is zero — and in tests, which must
    never start background work as a side effect of importing the app."""
    if os.environ.get("CHAOS_DISABLE_SCHEDULER") == "1":
        return False
    return INTERVAL_HOURS > 0


def due_orgs():
    """Orgs whose last successful scan is older than the interval."""
    out = []
    cutoff_seconds = INTERVAL_HOURS * 3600
    for org_id in db.orgs_with_integrations():
        last = None
        for run in db.job_history(org_id, limit=10):
            if run["job"] == "scheduled_scan" and run["status"] == "ok":
                last = run["finished_at"]
                break
        if last is None:
            out.append(org_id)
            continue
        age = _age_seconds(last)
        if age is None or age >= cutoff_seconds:
            out.append(org_id)
    return out


def _age_seconds(iso):
    import datetime
    try:
        then = datetime.datetime.fromisoformat(iso)
    except Exception:
        return None
    return (datetime.datetime.utcnow() - then).total_seconds()


def run_once_for(org_id):
    """One org's scheduled scan. Never raises — a failure is recorded, not fatal."""
    job_id = db.start_job(org_id, "scheduled_scan")
    try:
        org = db.get_org(org_id)
        if not org:
            db.finish_job(job_id, "error", "organization no longer exists")
            return {"org_id": org_id, "error": "missing org"}
        _scan_id, out = scan_mod.full_scan(org)
        if out.get("error"):
            db.finish_job(job_id, "error", out["error"])
            return {"org_id": org_id, "error": out["error"]}
        analysis = out.get("steps", {}).get("analysis", {})
        email = out.get("steps", {}).get("email") or {}
        if email.get("error") and not email.get("skipped"):
            # The scan still produced findings from stored mail; the sync is what
            # broke. Say so rather than reporting a clean run.
            db.finish_job(job_id, "error", f"mailbox sync failed: {email['error']}")
            return {"org_id": org_id, "error": email["error"]}
        db.finish_job(job_id, "ok",
                      f"{analysis.get('findings_new', 0)} new, "
                      f"{analysis.get('findings_total', 0)} open, "
                      f"score {analysis.get('score')}")
        return {"org_id": org_id, **analysis}
    except Exception as e:                                   # pragma: no cover
        db.finish_job(job_id, "error", f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return {"org_id": org_id, "error": str(e)[:200]}


def run_cycle():
    """One pass over every due org, if this worker wins the lease."""
    ttl = max(300, int(INTERVAL_HOURS * 3600))
    if not db.acquire_lease(LEASE_NAME, _HOLDER, ttl):
        return {"skipped": "another worker holds the scan lease"}
    results = []
    try:
        for org_id in due_orgs():
            results.append(run_once_for(org_id))
            if STAGGER_SECONDS:
                time.sleep(STAGGER_SECONDS)
    finally:
        db.release_lease(LEASE_NAME, _HOLDER)
    return {"scanned": len(results), "results": results}


async def loop():
    """The task the app starts at boot."""
    if not enabled():
        return
    # A short, jittered first delay: let the app finish starting, and stop a
    # fleet restart from turning into a synchronized stampede.
    await asyncio.sleep(30 + random.uniform(0, 30))
    while True:
        try:
            await asyncio.to_thread(run_cycle)
        except Exception:                                    # pragma: no cover
            traceback.print_exc()
        await asyncio.sleep(max(300.0, INTERVAL_HOURS * 3600) + random.uniform(0, 60))
