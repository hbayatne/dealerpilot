"""Assigning findings, and the guardrails around it.

The product must help a business rebalance work without becoming a surveillance
tool. That is a design constraint, not a slogan: the aggregate is grouped by
*work*, and the API refuses to hand work to anyone outside the organization.
"""
import os
import tempfile
import unittest

os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "assign.db")
os.environ["CHAOS_SECRET_KEY"] = "test-key"
os.environ["CHAOS_SECURE_COOKIES"] = "0"
os.environ["CHAOS_DISABLE_SCHEDULER"] = "1"

from fastapi.testclient import TestClient        # noqa: E402
from chaos import auth, db, ratelimit            # noqa: E402
from chaos.app import app                        # noqa: E402


class Assignment(unittest.TestCase):
    def setUp(self):
        ratelimit.reset()
        self.owner = TestClient(app)
        email = f"owner-{os.urandom(4).hex()}@x.test"
        self.owner.post("/api/signup", json={"email": email, "password": "password123"})
        self.oid = self.owner.post("/api/orgs", json={"name": "Assign Co"}
                                   ).json()["org"]["id"]
        self.me = db.get_user_by_email(email)["id"]
        self.mate = db.create_user(f"mate-{os.urandom(4).hex()}@x.test",
                                   auth.hash_password("password123"), name="Sam Cole")
        db.add_member(self.oid, self.mate, "employee")
        self.fid, _ = db.upsert_finding(self.oid, "k-assign", category="commitments",
                                        title="Overdue promise", detector="d")

    def test_assign_and_unassign(self):
        r = self.owner.post(f"/api/orgs/{self.oid}/findings/{self.fid}/assign",
                            json={"user_id": self.mate})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(db.get_finding(self.oid, self.fid)["assigned_to"], self.mate)

        r = self.owner.post(f"/api/orgs/{self.oid}/findings/{self.fid}/assign",
                            json={"user_id": None})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(db.get_finding(self.oid, self.fid)["assigned_to"])

    def test_cannot_assign_to_an_outsider(self):
        outsider = db.create_user(f"out-{os.urandom(4).hex()}@x.test", "h")
        r = self.owner.post(f"/api/orgs/{self.oid}/findings/{self.fid}/assign",
                            json={"user_id": outsider})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(db.get_finding(self.oid, self.fid)["assigned_to"])

    def test_employees_cannot_reassign_work(self):
        """Handing work around is a manager's call."""
        mate_client = TestClient(app)
        # Sign the teammate in directly; they were created without a session.
        token = auth._new_session(self.mate)
        mate_client.cookies.set("chaos_session", token)
        r = mate_client.post(f"/api/orgs/{self.oid}/findings/{self.fid}/assign",
                             json={"user_id": self.mate})
        self.assertEqual(r.status_code, 403)

    def test_assignment_is_audited(self):
        self.owner.post(f"/api/orgs/{self.oid}/findings/{self.fid}/assign",
                        json={"user_id": self.mate})
        actions = [e["action"] for e in db.audit_trail(self.oid)]
        self.assertIn("finding.assign", actions)

    def test_mine_filter_returns_only_my_work(self):
        other, _ = db.upsert_finding(self.oid, "k-other", category="revenue",
                                     title="Someone else's", detector="d")
        db.assign_finding(self.oid, self.fid, self.me)
        db.assign_finding(self.oid, other, self.mate)
        ids = [f["id"] for f in
               self.owner.get(f"/api/orgs/{self.oid}/findings?mine=true").json()["findings"]]
        self.assertIn(self.fid, ids)
        self.assertNotIn(other, ids)

    def test_workload_groups_by_work_and_counts_unassigned(self):
        db.assign_finding(self.oid, self.fid, self.mate)
        db.upsert_finding(self.oid, "k-pool", category="revenue", title="In the pool",
                          impact_cents=500000, detector="d")
        rows = self.owner.get(f"/api/orgs/{self.oid}/workload").json()["workload"]
        labels = {r["label"]: r for r in rows}
        self.assertIn("Unassigned", labels)
        self.assertIn("Sam Cole", labels)
        self.assertEqual(labels["Sam Cole"]["by_category"], {"commitments": 1})

    def test_resolved_work_leaves_the_workload(self):
        db.assign_finding(self.oid, self.fid, self.mate)
        db.set_finding_status(self.oid, self.fid, "resolved")
        rows = self.owner.get(f"/api/orgs/{self.oid}/workload").json()["workload"]
        self.assertNotIn("Sam Cole", {r["label"] for r in rows})

    def test_outsider_cannot_read_workload(self):
        stranger = TestClient(app)
        stranger.post("/api/signup", json={"email": f"s-{os.urandom(4).hex()}@x.test",
                                           "password": "password123"})
        self.assertEqual(stranger.get(f"/api/orgs/{self.oid}/workload").status_code, 404)


if __name__ == "__main__":
    unittest.main()
