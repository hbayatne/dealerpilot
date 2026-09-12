"""
The Chaos Scan — the orchestrator that turns connected systems into a report.

The pipeline is intentionally re-runnable end to end: sync, ingest, detect,
rank, score. Detection reads stored messages rather than the wire, so improving
a detector and re-scanning costs nothing and touches nobody's mailbox.

Progress is written to the `scans` row as it goes, because a scan of a real
mailbox takes minutes and a spinner with no explanation is how people conclude
software is broken.
"""
import secrets

from chaos import attention, crypto, db, entitlements, pipeline, score as score_mod, website
from chaos.detect import rules
from chaos.ingest import imap_source


def _step(scan_id, pct, text):
    db.update_scan(scan_id, progress=pct, step=text, status="running")


# ---------------------------------------------------------------- website only
def website_scan(url, org_id=None, share=False):
    """The free, no-signup scan. Returns the stored scan row id and result."""
    token = secrets.token_urlsafe(18) if share else None
    scan_id = db.create_scan(org_id, "website", url, share_token=token)
    _step(scan_id, 10, "Loading your website")
    try:
        result = website.analyze(url)
    except website.UnsafeTarget as e:
        db.update_scan(scan_id, status="error", error=str(e))
        return scan_id, {"error": str(e)}
    except Exception as e:                                   # pragma: no cover
        db.update_scan(scan_id, status="error", error=str(e)[:200])
        return scan_id, {"error": "We couldn't scan that site."}

    result["share_token"] = token
    db.update_scan(scan_id, status="done", progress=100, step="Complete",
                   result=result, shared=1 if share else 0)
    db.track("website_scan_completed", org_id=org_id, url=url,
             issues=len(result.get("issues") or []))
    return scan_id, result


# ---------------------------------------------------------------- email sync
def sync_email(org, integration=None, limit=None):
    """Pull new mail for an org and ingest it. Returns ingestion stats."""
    org_id = org["id"]
    integ = integration or db.integration(org_id, "imap")
    if not integ:
        return {"error": "No mailbox connected."}
    cfg = integ.get("config") or {}
    try:
        password = crypto.decrypt(integ.get("secret"))
    except crypto.SecretsUnavailable as e:
        db.mark_sync(org_id, "imap", error=str(e))
        return {"error": str(e)}

    cap = limit or entitlements.limit(org, "messages_scanned") or 5000
    try:
        raw, cursor = imap_source.fetch(
            cfg.get("host"), cfg.get("port"), cfg.get("user"), password,
            cursor=integ.get("cursor"), folders=cfg.get("folders"),
            limit=min(cap, 5000),
            since_days=entitlements.limit(org, "history_days") or 180)
    except imap_source.ImapError as e:
        db.mark_sync(org_id, "imap", error=str(e))
        return {"error": str(e)}

    stats = pipeline.ingest(org, raw, source="email")
    db.mark_sync(org_id, "imap", cursor=cursor)
    stats["fetched"] = len(raw)
    return stats


# ---------------------------------------------------------------- analysis
def analyze(org, now_iso=None):
    """Detect, persist, rank and score against whatever is already stored."""
    org_id = org["id"]
    now_iso = now_iso or db.now()

    commit_counts = rules.record_commitments(org, now_iso)

    created = updated = 0
    for f, ev in rules.run(org, now_iso=now_iso):
        f.pop("_conversation_id", None)
        key = f.pop("dedupe_key")
        fid, is_new = db.upsert_finding(org_id, key, **f)
        db.add_evidence(org_id, fid, ev)
        created += 1 if is_new else 0
        updated += 0 if is_new else 1

    ranked = attention.rank(org_id, now_iso=now_iso)
    attention.persist(org_id, ranked)

    latest_site = _latest_website_result(org_id)
    result = score_mod.compute(org_id, now_iso=now_iso, website_result=latest_site)
    score_mod.save(org_id, result)

    return {"commitments": commit_counts, "findings_new": created,
            "findings_updated": updated, "findings_total": len(ranked),
            "score": result["score"], "band": result["band_label"],
            "coverage": result["coverage"]}


def _latest_website_result(org_id):
    for s in db.scans(org_id, limit=25):
        if s["kind"] == "website" and s["status"] == "done":
            full = db.get_scan(s["id"], org_id)
            return (full or {}).get("result")
    return None


# ---------------------------------------------------------------- full scan
def full_scan(org, scan_id=None, now_iso=None, do_sync=True):
    """Everything: website, mailbox, detection, score. Safe to re-run."""
    org_id = org["id"]
    scan_id = scan_id or db.create_scan(org_id, "full", org.get("website") or "")
    out = {"steps": {}}
    try:
        if org.get("website"):
            _step(scan_id, 10, "Checking your website")
            try:
                _sid, wres = website_scan(org["website"], org_id=org_id)
                out["steps"]["website"] = {"issues": len(wres.get("issues") or []),
                                           "error": wres.get("error")}
            except Exception as e:
                out["steps"]["website"] = {"error": str(e)[:160]}

        if do_sync and db.integration(org_id, "imap"):
            _step(scan_id, 35, "Reading your mailbox")
            out["steps"]["email"] = sync_email(org)

        _step(scan_id, 70, "Building your business memory")
        _step(scan_id, 80, "Looking for what's falling through the cracks")
        out["steps"]["analysis"] = analyze(org, now_iso=now_iso)

        _step(scan_id, 95, "Scoring")
        out["score"] = out["steps"]["analysis"]["score"]
        out["band"] = out["steps"]["analysis"]["band"]
        out["coverage"] = out["steps"]["analysis"]["coverage"]
        db.update_scan(scan_id, status="done", progress=100, step="Complete", result=out)
        db.track("full_scan_completed", org_id=org_id,
                 findings=out["steps"]["analysis"]["findings_total"])
    except Exception as e:                                   # pragma: no cover
        db.update_scan(scan_id, status="error", error=str(e)[:300])
        out["error"] = str(e)[:300]
    return scan_id, out


# ---------------------------------------------------------------- report
def report(org_id, limit=50):
    """The Chaos Report — everything the owner sees after a scan."""
    org = db.get_org(org_id)
    latest = db.latest_score(org_id)
    ranked = attention.rank(org_id)
    summary = attention.summarize(org_id, ranked)
    history = db.score_history(org_id, limit=30)

    visible_cap = entitlements.limit(org, "findings_visible")
    shown = ranked[:visible_cap] if visible_cap else ranked[:limit]

    commitments = db.commitments(org_id, limit=200)
    return {
        "org": {"id": org["id"], "name": org["name"], "website": org.get("website"),
                "industry": org.get("industry"), "domains": org.get("domains")},
        "score": latest,
        "history": history,
        "summary": summary,
        "findings": shown,
        "findings_withheld": max(0, len(ranked) - len(shown)),
        "today": attention.today(org_id, ranked),
        "commitments": {
            "total": len(commitments),
            "overdue": len([c for c in commitments if c["state"] == "overdue"]),
            "open": len([c for c in commitments if c["state"] == "open"]),
            "kept": len([c for c in commitments if c["state"] == "likely_fulfilled"]),
        },
        "integrations": db.integrations(org_id),
        "plan": entitlements.describe(org),
        "memory": {
            "people": len(db.entities(org_id, kind="person", limit=5000)),
            "companies": len(db.entities(org_id, kind="company", limit=5000)),
            "conversations": len(db.conversations(org_id, limit=5000)),
            "messages": db.message_count(org_id),
        },
    }
