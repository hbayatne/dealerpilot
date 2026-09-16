"""Scheduler behaviour: leases, due-ness, and never failing silently."""
import datetime
import os
import tempfile
import unittest

os.environ.setdefault("CHAOS_DB", os.path.join(tempfile.mkdtemp(), "sched.db"))

from chaos import db, demo, pipeline, scheduler          # noqa: E402


class Leases(unittest.TestCase):
    def setUp(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "lease.db")
        import importlib
        importlib.reload(db)
        db.init()

    def test_only_one_worker_wins(self):
        self.assertTrue(db.acquire_lease("scan", "worker-a", 60))
        self.assertFalse(db.acquire_lease("scan", "worker-b", 60),
                         "a second worker must not run the same cycle")

    def test_holder_can_renew(self):
        db.acquire_lease("scan", "worker-a", 60)
        self.assertTrue(db.acquire_lease("scan", "worker-a", 60))

    def test_lapsed_lease_is_reclaimed(self):
        """A worker that dies mid-cycle must not block the fleet forever."""
        db.acquire_lease("scan", "dead-worker", 60)
        stale = (datetime.datetime.utcnow()
                 - datetime.timedelta(seconds=10)).isoformat(timespec="seconds")
        with db._conn() as c:
            c.execute("UPDATE job_leases SET expires_at=? WHERE name=?", (stale, "scan"))
        self.assertTrue(db.acquire_lease("scan", "worker-b", 60))

    def test_release_frees_it(self):
        db.acquire_lease("scan", "worker-a", 60)
        db.release_lease("scan", "worker-a")
        self.assertTrue(db.acquire_lease("scan", "worker-b", 60))


class DueOrgs(unittest.TestCase):
    def setUp(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "due.db")
        import importlib
        importlib.reload(db)
        importlib.reload(scheduler)
        db.init()
        self.uid = db.create_user("sched@x.test", "x")

    def test_org_with_integration_is_due_when_never_scanned(self):
        oid = db.create_org("Never scanned", user_id=self.uid)
        db.upsert_integration(oid, "imap", label="m@x.test")
        self.assertIn(oid, scheduler.due_orgs())

    def test_org_without_any_integration_is_not_visited(self):
        oid = db.create_org("Nothing connected", user_id=self.uid)
        self.assertNotIn(oid, scheduler.due_orgs())

    def test_recently_scanned_org_is_not_due(self):
        oid = db.create_org("Fresh", user_id=self.uid)
        db.upsert_integration(oid, "imap", label="m@x.test")
        job = db.start_job(oid, "scheduled_scan")
        db.finish_job(job, "ok", "nothing new")
        self.assertNotIn(oid, scheduler.due_orgs())

    def test_stale_org_becomes_due_again(self):
        oid = db.create_org("Stale", user_id=self.uid)
        db.upsert_integration(oid, "imap", label="m@x.test")
        job = db.start_job(oid, "scheduled_scan")
        db.finish_job(job, "ok", "done")
        old = (datetime.datetime.utcnow()
               - datetime.timedelta(hours=scheduler.INTERVAL_HOURS + 1)
               ).isoformat(timespec="seconds")
        with db._conn() as c:
            c.execute("UPDATE job_runs SET finished_at=? WHERE id=?", (old, job))
        self.assertIn(oid, scheduler.due_orgs())

    def test_failed_run_does_not_count_as_scanned(self):
        """A broken sync must be retried, not treated as up to date."""
        oid = db.create_org("Broken", user_id=self.uid)
        db.upsert_integration(oid, "imap", label="m@x.test")
        job = db.start_job(oid, "scheduled_scan")
        db.finish_job(job, "error", "login refused")
        self.assertIn(oid, scheduler.due_orgs())


class RunRecording(unittest.TestCase):
    def setUp(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "run.db")
        import importlib
        importlib.reload(db)
        importlib.reload(scheduler)
        db.init()
        self.uid = db.create_user("run@x.test", "x")

    def test_successful_run_is_recorded(self):
        oid = db.create_org("Recorded", user_id=self.uid, domains=demo.ORG["domains"])
        org = db.get_org(oid)
        msgs, _ = demo.build(datetime.datetime(2026, 9, 9, 10, 0))
        pipeline.ingest(org, msgs)
        result = scheduler.run_once_for(oid)
        self.assertNotIn("error", result)
        runs = [r for r in db.job_history(oid) if r["job"] == "scheduled_scan"]
        self.assertTrue(runs)
        self.assertEqual(runs[0]["status"], "ok")
        self.assertIn("open", runs[0]["detail"])

    def test_missing_org_is_recorded_not_raised(self):
        result = scheduler.run_once_for(999999)
        self.assertIn("error", result)

    def test_sample_data_org_scans_cleanly(self):
        """A demo business carries an integration row so the UI reads naturally,
        but nothing is behind it. It must not report a broken mailbox forever."""
        oid = db.create_org("Demo Co", user_id=self.uid, domains=demo.ORG["domains"])
        db.upsert_integration(oid, "imap", label="demo mailbox (sample data)",
                              config={"sample_data": True})
        org = db.get_org(oid)
        pipeline.ingest(org, demo.build(datetime.datetime(2026, 9, 9, 10, 0))[0])
        result = scheduler.run_once_for(oid)
        self.assertNotIn("error", result)
        runs = [r for r in db.job_history(oid) if r["job"] == "scheduled_scan"]
        self.assertEqual(runs[0]["status"], "ok")

    def test_unreadable_credential_gives_an_actionable_message(self):
        """A raw `binascii.Error: Incorrect padding` reaches the customer in the
        integration's error banner and tells them nothing about what to do."""
        from chaos import crypto
        with self.assertRaises(crypto.SecretsUnavailable) as cm:
            crypto.decrypt("v1:not-valid-base64!!")
        self.assertIn("Reconnect", str(cm.exception))

    def test_a_broken_mailbox_sync_is_not_reported_as_a_clean_run(self):
        """The scan still yields findings from stored mail; the sync is what
        broke, and the customer has to be able to see that."""
        oid = db.create_org("BadCreds", user_id=self.uid, domains=demo.ORG["domains"])
        db.upsert_integration(oid, "imap", label="m@x.test",
                              config={"host": "imap.invalid.example", "port": 993,
                                      "user": "m@x.test"},
                              secret="v1:not-decryptable")
        scheduler.run_once_for(oid)
        runs = [r for r in db.job_history(oid) if r["job"] == "scheduled_scan"]
        self.assertEqual(runs[0]["status"], "error")
        self.assertTrue(runs[0]["detail"])


class SchedulerToggle(unittest.TestCase):
    def test_disabled_by_env(self):
        os.environ["CHAOS_DISABLE_SCHEDULER"] = "1"
        try:
            self.assertFalse(scheduler.enabled())
        finally:
            os.environ.pop("CHAOS_DISABLE_SCHEDULER")

    def test_zero_interval_disables(self):
        import importlib
        os.environ["CHAOS_SCAN_INTERVAL_HOURS"] = "0"
        try:
            importlib.reload(scheduler)
            self.assertFalse(scheduler.enabled())
        finally:
            os.environ.pop("CHAOS_SCAN_INTERVAL_HOURS")
            importlib.reload(scheduler)


if __name__ == "__main__":
    unittest.main()
