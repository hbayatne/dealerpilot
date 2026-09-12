"""Accuracy harness — scores the detectors against the labelled demo corpus.

Run:  python3 tools_accuracy.py
Prints per-thread expected-vs-actual plus precision/recall. This is the loop the
detectors are tuned in; a change that raises recall while adding a false positive
is not an improvement.
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault("CHAOS_DB", os.path.join(tempfile.mkdtemp(), "acc.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chaos import db, demo, pipeline               # noqa: E402
from chaos.detect import rules                     # noqa: E402

NOW = datetime.datetime(2026, 9, 9, 10, 0)


def main():
    db.init()
    uid = db.create_user("owner@northsideroofing.example", "x")
    oid = db.create_org(demo.ORG["name"], user_id=uid, domains=demo.ORG["domains"])
    org = db.get_org(oid)
    msgs, expect = demo.build(NOW)
    pipeline.ingest(org, msgs)
    found = rules.run(org, now_iso=NOW.isoformat(timespec="seconds"))

    # Map each finding back to the thread it came from.
    by_conv = {}
    for f, ev in found:
        by_conv.setdefault(f.get("_conversation_id"), []).append(f)

    conv_of_thread = {}
    for e in expect:
        key = "ref:" + e["thread"].strip("<>")
        with db._conn() as c:
            r = c.execute("SELECT conversation_id FROM conversation_keys WHERE org_id=? AND key=?",
                          (oid, key)).fetchone()
        conv_of_thread[e["thread"]] = r["conversation_id"] if r else None

    tp = fp = fn = tn = 0
    print(f"{'thread':10} {'expected':12} {'actual':24} verdict")
    print("-" * 78)
    for e in expect:
        cid = conv_of_thread[e["thread"]]
        actual = [f["detector"] for f in by_conv.get(cid, [])]
        wanted = bool(e["should"])
        got = bool(actual)
        if wanted and got:
            tp += 1
            verdict = "HIT"
        elif wanted and not got:
            fn += 1
            verdict = "MISS  <-- recall loss"
        elif not wanted and got:
            fp += 1
            verdict = "FALSE POSITIVE  <-- trust loss"
        else:
            tn += 1
            verdict = "correctly silent"
        print(f"{e['thread']:10} {'finding' if wanted else 'silence':12} "
              f"{','.join(actual)[:23] or '-':24} {verdict}")
        if verdict.startswith(("MISS", "FALSE")):
            print(f"{'':10} reason expected: {e['why']}")

    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    print("-" * 78)
    print(f"threads: {len(expect)}   findings emitted: {len(found)}")
    print(f"true positives {tp}  false positives {fp}  misses {fn}  correctly silent {tn}")
    print(f"precision {prec:.0%}   recall {rec:.0%}")
    return 0 if (fp == 0 and fn == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
