"""Run the adversarial corpus with per-case output. `python3 tools/adversarial.py`"""
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
    for name, msgs, why in cases:
        oid = db.create_org(name, user_id=uid, domains=[adversarial.US])
        org = db.get_org(oid)
        pipeline.ingest(org, msgs)
        found = rules.run(org, now_iso=now_iso)
        should_fire = "SHOULD FIRE" in why
        got = [f["detector"] for f, _ in found]
        ok = bool(got) == should_fire
        fails += 0 if ok else 1
        mark = "ok    " if ok else ("MISS  " if should_fire else "FALSE+")
        print(f"[{mark}] {name:34} -> {', '.join(got) or 'silent'}")
        if not ok:
            print(f"          expected: {why}")
    print(f"\n{len(cases) - fails}/{len(cases)} adversarial cases correct")
    return fails


if __name__ == "__main__":
    sys.exit(main())
