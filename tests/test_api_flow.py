"""End-to-end: the flow a real business owner actually walks through, plus the
tenant-isolation checks that must never regress."""
import datetime
import os
import tempfile
import unittest

os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "api.db")
os.environ["CHAOS_SECRET_KEY"] = "test-key"
os.environ["CHAOS_SECURE_COOKIES"] = "0"
# Importing the app must never start background work in a test run.
os.environ["CHAOS_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient                    # noqa: E402
from chaos import db, demo, pipeline, ratelimit, scan         # noqa: E402
from chaos.app import app                                     # noqa: E402


class ApiFlow(unittest.TestCase):
    def setUp(self):
        # Every test here shares one client address; without a reset the limiter
        # correctly refuses later tests. Rate limiting itself is covered in
        # tests/test_security.py.
        ratelimit.reset()
        self.c = TestClient(app)

    def _signup(self, email):
        c = TestClient(app)
        r = c.post("/api/signup", json={"email": email, "password": "password123"})
        self.assertEqual(r.status_code, 200, r.text)
        return c

    def test_health_is_public(self):
        r = self.c.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertIn("brand", r.json())

    def test_signup_login_and_org(self):
        c = self._signup("flow@acme.test")
        r = c.post("/api/orgs", json={"name": "Acme", "website": "acme.test",
                                      "industry": "roofing", "domains": ["acme.test"]})
        self.assertEqual(r.status_code, 200, r.text)
        org = r.json()["org"]
        self.assertEqual(org["domains"], ["acme.test"])
        self.assertEqual(c.get("/api/me").json()["orgs"][0]["role"], "owner")

    def test_weak_password_rejected(self):
        r = self.c.post("/api/signup", json={"email": "weak@acme.test", "password": "abc"})
        self.assertEqual(r.status_code, 400)

    def test_auth_required(self):
        fresh = TestClient(app)
        self.assertEqual(fresh.get("/api/me").status_code, 401)
        self.assertEqual(fresh.get("/api/orgs/1/report").status_code, 401)

    def test_tenant_isolation(self):
        """A user must not be able to read another organization's data, and the
        response must not even confirm that it exists."""
        a = self._signup("tenant-a@acme.test")
        b = self._signup("tenant-b@other.test")
        oid = a.post("/api/orgs", json={"name": "A Co", "domains": ["acme.test"]}
                     ).json()["org"]["id"]
        for path in (f"/api/orgs/{oid}", f"/api/orgs/{oid}/report",
                     f"/api/orgs/{oid}/findings", f"/api/orgs/{oid}/entities",
                     f"/api/orgs/{oid}/commitments", f"/api/orgs/{oid}/audit"):
            self.assertEqual(b.get(path).status_code, 404, f"{path} leaked")
        self.assertEqual(b.post(f"/api/orgs/{oid}/scan").status_code, 404)
        self.assertEqual(b.delete(f"/api/orgs/{oid}/data").status_code, 404)

    def test_full_scan_flow_produces_findings_with_evidence(self):
        c = self._signup("scan@northside.test")
        oid = c.post("/api/orgs", json={"name": demo.ORG["name"],
                                        "domains": demo.ORG["domains"]}).json()["org"]["id"]
        org = db.get_org(oid)
        db.upsert_integration(oid, "imap", label="test mailbox")
        now = datetime.datetime(2026, 9, 9, 10, 0)
        msgs, _ = demo.build(now)
        pipeline.ingest(org, msgs)
        scan.analyze(org, now_iso=now.isoformat(timespec="seconds"))

        rep = c.get(f"/api/orgs/{oid}/report").json()
        self.assertGreaterEqual(len(rep["findings"]), 3)
        self.assertIsNotNone(rep["score"])
        self.assertIn("statement", rep["score"]["coverage"])

        fid = rep["findings"][0]["id"]
        detail = c.get(f"/api/orgs/{oid}/findings/{fid}").json()
        self.assertTrue(detail["evidence"], "every finding must carry evidence")
        for e in detail["evidence"]:
            self.assertTrue(e["label"])

    def test_false_positive_feedback_removes_and_never_resurrects(self):
        c = self._signup("fp@northside.test")
        oid = c.post("/api/orgs", json={"name": "FP Co",
                                        "domains": demo.ORG["domains"]}).json()["org"]["id"]
        org = db.get_org(oid)
        now = datetime.datetime(2026, 9, 9, 10, 0)
        msgs, _ = demo.build(now)
        pipeline.ingest(org, msgs)
        scan.analyze(org, now_iso=now.isoformat(timespec="seconds"))

        before = c.get(f"/api/orgs/{oid}/findings").json()["findings"]
        fid = before[0]["id"]
        r = c.post(f"/api/orgs/{oid}/findings/{fid}/feedback",
                   json={"verdict": "false_positive", "note": "already handled by phone"})
        self.assertEqual(r.status_code, 200)
        after = c.get(f"/api/orgs/{oid}/findings").json()["findings"]
        self.assertNotIn(fid, [f["id"] for f in after])

        # Re-running detection must not bring a dismissed finding back.
        scan.analyze(org, now_iso=now.isoformat(timespec="seconds"))
        again = c.get(f"/api/orgs/{oid}/findings").json()["findings"]
        self.assertNotIn(fid, [f["id"] for f in again])

        quality = c.get(f"/api/orgs/{oid}/quality").json()["detectors"]
        self.assertTrue(any(v["false_positive"] for v in quality.values()))

    def test_website_scan_is_public_and_blocks_ssrf(self):
        for bad in ("http://localhost/", "http://169.254.169.254/", "file:///etc/passwd"):
            r = self.c.post("/api/scan/website", json={"url": bad})
            self.assertEqual(r.status_code, 400, f"{bad} was not rejected")

    def test_integration_secret_never_returned(self):
        c = self._signup("sec@acme.test")
        oid = c.post("/api/orgs", json={"name": "Sec Co"}).json()["org"]["id"]
        from chaos import crypto
        db.upsert_integration(oid, "imap", label="m@acme.test",
                              config={"host": "imap.acme.test", "user": "m@acme.test"},
                              secret=crypto.encrypt("super-secret-password"))
        body = c.get(f"/api/orgs/{oid}/integrations").text
        self.assertNotIn("super-secret-password", body)
        self.assertNotIn("secret", c.get(f"/api/orgs/{oid}/integrations"
                                         ).json()["integrations"][0])

    def test_transparency_and_data_deletion(self):
        c = self._signup("priv@acme.test")
        oid = c.post("/api/orgs", json={"name": "Priv Co",
                                        "domains": demo.ORG["domains"]}).json()["org"]["id"]
        org = db.get_org(oid)
        msgs, _ = demo.build(datetime.datetime(2026, 9, 9, 10, 0))
        pipeline.ingest(org, msgs)
        self.assertGreater(db.message_count(oid), 0)

        t = c.get(f"/api/orgs/{oid}/transparency").json()
        self.assertIn("does_not_store", t["integrations"][0])

        self.assertEqual(c.delete(f"/api/orgs/{oid}/data").status_code, 200)
        self.assertEqual(db.message_count(oid), 0)
        self.assertEqual(len(db.entities(oid)), 0)


if __name__ == "__main__":
    unittest.main()
