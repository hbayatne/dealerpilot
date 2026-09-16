"""The parts of the Render deploy that can be checked without Render.

The network calls themselves are exercised only by running the job. What is
testable here is the part that would quietly destroy data: re-running a deploy
must never regenerate CHAOS_SECRET_KEY, because a new key makes every stored
mailbox credential unreadable, and the operator would see "deploy succeeded".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("RENDER_API_KEY", "test-key")

from tools import render_deploy as rd                        # noqa: E402


class EnvVars(unittest.TestCase):
    def merged(self, existing, database_url="postgres://x"):
        return {e["key"]: e["value"] for e in rd.env_vars(existing, database_url)}

    def test_first_run_generates_both_secrets(self):
        out = self.merged([])
        self.assertTrue(out["CHAOS_SECRET_KEY"])
        self.assertTrue(out["CHAOS_SIGNUP_CODE"])
        self.assertGreaterEqual(len(out["CHAOS_SECRET_KEY"]), 32)

    def test_existing_secrets_are_never_regenerated(self):
        keep = [{"key": "CHAOS_SECRET_KEY", "value": "the-original"},
                {"key": "CHAOS_SIGNUP_CODE", "value": "macan-141"}]
        out = self.merged(keep)
        self.assertEqual(out["CHAOS_SECRET_KEY"], "the-original")
        self.assertEqual(out["CHAOS_SIGNUP_CODE"], "macan-141")

    def test_unrelated_variables_are_left_alone(self):
        out = self.merged([{"key": "ANTHROPIC_API_KEY", "value": "sk-ant-x"}])
        self.assertEqual(out["ANTHROPIC_API_KEY"], "sk-ant-x")

    def test_proxy_trust_is_forced_on(self):
        """Render terminates TLS ahead of the app, so the client address only
        exists in X-Forwarded-For — rate limiting is per-source and needs it."""
        out = self.merged([{"key": "CHAOS_TRUST_PROXY", "value": "0"}])
        self.assertEqual(out["CHAOS_TRUST_PROXY"], "1")

    def test_no_database_means_no_database_url(self):
        self.assertNotIn("DATABASE_URL", self.merged([], database_url=None))

    def test_database_url_is_refreshed_not_kept(self):
        """A rotated connection string must win over the stored one."""
        out = self.merged([{"key": "DATABASE_URL", "value": "postgres://old"}])
        self.assertEqual(out["DATABASE_URL"], "postgres://x")


class ListShapes(unittest.TestCase):
    def test_wrapped_and_bare_rows_both_work(self):
        self.assertEqual(rd.unwrap([{"service": {"id": "a"}}], "service"), [{"id": "a"}])
        self.assertEqual(rd.unwrap([{"id": "b"}], "service"), [{"id": "b"}])
        self.assertEqual(rd.unwrap(None, "service"), [])


class OwnerSelection(unittest.TestCase):
    def setUp(self):
        self._real = rd.call
        os.environ.pop("RENDER_OWNER", None)

    def tearDown(self):
        rd.call = self._real
        os.environ.pop("RENDER_OWNER", None)

    def _owners(self, *names):
        rd.call = lambda m, p, b=None: [
            {"owner": {"id": f"tea-{n}", "name": n}} for n in names]

    def test_single_owner_is_used(self):
        self._owners("hadi")
        self.assertEqual(rd.owner_id(), "tea-hadi")

    def test_several_owners_is_an_error_not_a_guess(self):
        """Picking one would deploy a business's data into the wrong account."""
        self._owners("hadi", "car-place-dallas")
        with self.assertRaises(SystemExit):
            rd.owner_id()

    def test_named_owner_resolves(self):
        self._owners("hadi", "car-place-dallas")
        os.environ["RENDER_OWNER"] = "car-place-dallas"
        self.assertEqual(rd.owner_id(), "tea-car-place-dallas")


if __name__ == "__main__":
    unittest.main()
