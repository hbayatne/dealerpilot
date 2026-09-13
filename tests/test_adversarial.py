"""The adversarial corpus, as a regression test.

A false positive here is a product regression, not a test nit: it means we are
telling a business owner something that is not true. So is a finding of the
wrong kind — "your employee broke a promise" when the real fact is "your email
bounced" blames the wrong party for the wrong thing.
"""
import os
import tempfile
import unittest

os.environ.setdefault("CHAOS_DB", os.path.join(tempfile.mkdtemp(), "adv.db"))

from chaos import db, pipeline                       # noqa: E402
from chaos.corpus import adversarial                 # noqa: E402
from chaos.detect import rules                       # noqa: E402


def _run_corpus():
    os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "adv.db")
    import importlib
    importlib.reload(db)
    db.init()
    uid = db.create_user("adv@x.test", "x")
    cases, now = adversarial.build()
    now_iso = now.isoformat(timespec="seconds")
    out = []
    for name, msgs, expected, why in cases:
        oid = db.create_org(name, user_id=uid, domains=[adversarial.US])
        org = db.get_org(oid)
        pipeline.ingest(org, msgs)
        got = sorted(f["detector"] for f, _ in rules.run(org, now_iso=now_iso))
        out.append((name, sorted(expected), got, why))
    return out


class Adversarial(unittest.TestCase):
    def test_no_false_positives(self):
        problems = [f"{n}: expected silence ({w}), got {g}"
                    for n, e, g, w in _run_corpus() if not e and g]
        self.assertEqual(problems, [], "\n".join(problems))

    def test_nothing_is_missed(self):
        problems = [f"{n}: expected {e} ({w}), got nothing"
                    for n, e, g, w in _run_corpus() if e and not g]
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_right_detector_fires(self):
        problems = [f"{n}: expected {e}, got {g} — {w}"
                    for n, e, g, w in _run_corpus() if e and g and e != g]
        self.assertEqual(problems, [], "\n".join(problems))

    def test_a_bounce_is_not_reported_as_a_broken_promise(self):
        by_name = {n: g for n, _e, g, _w in _run_corpus()}
        bounce = next(g for n, g in by_name.items() if n.startswith("A5"))
        self.assertIn("undelivered_email", bounce)
        self.assertNotIn("overdue_commitment", bounce)

    def test_being_copied_in_creates_no_obligation(self):
        by_name = {n: g for n, _e, g, _w in _run_corpus()}
        cc_only = next(g for n, g in by_name.items() if "only CC" in n)
        self.assertEqual(cc_only, [],
                         "a thread between other people is not ours to answer")


if __name__ == "__main__":
    unittest.main()
