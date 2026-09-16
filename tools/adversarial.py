"""Run the adversarial corpus with per-case output. `python3 tools/adversarial.py`

Exits non-zero on any mismatch. A case that fires the *wrong* detector counts as
a failure just as much as one that stays silent when it shouldn't — a finding of
the wrong kind blames the wrong party for the wrong thing.
"""
import os
import sys
import tempfile

os.environ.setdefault("CHAOS_DB", os.path.join(tempfile.mkdtemp(), "adv.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chaos import db, pipeline                    # noqa: E402
from chaos.corpus import adversarial              # noqa: E402
from chaos.detect import rules                    # noqa: E402


def main():
    db.init()
    uid = db.create_user("adv@x.test", "x")
    cases, now = adversarial.build()
    now_iso = now.isoformat(timespec="seconds")
    fails = 0
    for name, msgs, expected, why in cases:
        oid = db.create_org(name, user_id=uid, domains=[adversarial.US])
        org = db.get_org(oid)
        pipeline.ingest(org, msgs)
        got = sorted(f["detector"] for f, _ in rules.run(org, now_iso=now_iso))
        ok = got == sorted(expected)
        fails += 0 if ok else 1
        if ok:
            mark = "ok    "
        elif expected and not got:
            mark = "MISS  "
        elif got and not expected:
            mark = "FALSE+"
        else:
            mark = "WRONG "
        print(f"[{mark}] {name:46} -> {', '.join(got) or 'silent'}")
        if not ok:
            print(f"          expected: {', '.join(expected) or 'silence'} — {why}")
    print(f"\n{len(cases) - fails}/{len(cases)} adversarial cases correct")
    return fails


if __name__ == "__main__":
    sys.exit(main())
