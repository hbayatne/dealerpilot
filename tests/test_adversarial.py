"""The adversarial corpus, as a regression test.

A false positive here is a product regression, not a test nit: it means we are
telling a business owner something that is not true.
"""
import os
import tempfile
import unittest

os.environ.setdefault("CHAOS_DB", os.path.join(tempfile.mkdtemp(), "adv.db"))

from chaos import db, pipeline                       # noqa: E402
from chaos.corpus import adversarial                 # noqa: E402
from chaos.detect import rules                       # noqa: E402


class Adversarial(unittest.TestCase):
    def test_corpus(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "adv.db")
        import importlib
        importlib.reload(db)
        db.init()
        uid = db.create_user("adv@x.test", "x")
        cases, now = adversarial.build()
        now_iso = now.isoformat(timespec="seconds")
        problems = []
        for name, msgs, why in cases:
            oid = db.create_org(name, user_id=uid, domains=[adversarial.US])
            org = db.get_org(oid)
            pipeline.ingest(org, msgs)
            found = rules.run(org, now_iso=now_iso)
            should_fire = "SHOULD FIRE" in why
            got = [f["detector"] for f, _ in found]
            if bool(got) != should_fire:
                problems.append(
                    f"{name}: expected {'a finding' if should_fire else 'silence'}, "
                    f"got {got or 'silence'} — {why}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_bounce_produces_the_right_finding(self):
        """A bounced email is a delivery problem, never a broken promise."""
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "bounce.db")
        import importlib
        importlib.reload(db)
        db.init()
        uid = db.create_user("b@x.test", "x")
        cases, now = adversarial.build()
        case = next(c for c in cases if c[0].startswith("A2"))
        oid = db.create_org("Bounce Co", user_id=uid, domains=[adversarial.US])
        org = db.get_org(oid)
        pipeline.ingest(org, case[1])
        detectors = [f["detector"] for f, _ in
                     rules.run(org, now_iso=now.isoformat(timespec="seconds"))]
        self.assertIn("undelivered_email", detectors)
        self.assertNotIn("overdue_commitment", detectors)


if __name__ == "__main__":
    unittest.main()
