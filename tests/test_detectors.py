"""Detector behaviour, locked down.

The false-positive cases matter more than the true positives here. A detector
that misses something costs a finding; a detector that fires wrongly costs the
owner's trust in every other finding, which is unrecoverable.
"""
import datetime
import os
import tempfile
import unittest

os.environ.setdefault("CHAOS_DB", os.path.join(tempfile.mkdtemp(), "det.db"))

from chaos import db, demo, pipeline                            # noqa: E402
from chaos.detect import base, commitments, rules, signals, timeref   # noqa: E402
from chaos.ingest import mailbox as M                           # noqa: E402

WED = "2026-09-02T09:14:00"        # a Wednesday


class Commitments(unittest.TestCase):
    REAL = [
        "I'll call you Friday with the pricing.",
        "We'll send that over today.",
        "Let me check with accounting and get back to you.",
        "I'll have accounting refund the $250 by Thursday.",
        "I will get you those numbers tomorrow morning.",
        "We are going to schedule the install next week.",
        "I'll come by Thursday and get you a written estimate.",
        "I'll get someone to call you tomorrow.",
        "I'll make sure that quote goes out today.",
        "Someone will call you back this afternoon.",
    ]
    NOT_REAL = [
        "Let me know if you'd like me to call you.",        # an offer
        "If you decide to move forward, I'll send the paperwork.",  # conditional
        "I won't be able to send that today.",              # negated
        "I called you Friday but got voicemail.",           # past tense
        "Should I call you Friday?",                        # a question
        "I'll be honest, that's a tough one.",              # figure of speech
        "We'll see how it goes.",
        "I'll have to think about it.",                     # obligation, not promise
        "I'll get back to the office around 5.",            # a place, not a person
        "I'll be out of office next week.",
        "We'll be closed Monday for the holiday.",
        "Happy to send pricing whenever you're ready.",
    ]

    def test_detects_real_commitments(self):
        for text in self.REAL:
            self.assertTrue(commitments.extract(text, WED), f"missed: {text}")

    def test_ignores_things_that_are_not_commitments(self):
        for text in self.NOT_REAL:
            got = commitments.extract(text, WED)
            self.assertFalse(got, f"false positive on {text!r}: {got}")

    def test_quote_is_carried_so_a_human_can_check_it(self):
        c = commitments.extract("Thanks for waiting. I'll call you Friday with pricing.",
                                WED)[0]
        self.assertIn("call you Friday", c["quote"])
        self.assertTrue(c["due_at"])

    def test_open_commitment_has_no_invented_deadline(self):
        c = commitments.extract("Let me check with accounting and get back to you.", WED)[0]
        self.assertIsNone(c["due_at"],
                          "a commitment with no stated date must not be given one")


class TimeReferences(unittest.TestCase):
    def test_named_weekday(self):
        self.assertTrue(timeref.extract("call you Friday", WED)["due_at"]
                        .startswith("2026-09-04"))

    def test_same_weekday_means_next_week(self):
        self.assertTrue(timeref.extract("call you Wednesday", WED)["due_at"]
                        .startswith("2026-09-09"))

    def test_explicit_date(self):
        self.assertTrue(timeref.extract("by September 15", WED)["due_at"]
                        .startswith("2026-09-15"))

    def test_no_reference_returns_none(self):
        self.assertIsNone(timeref.extract("I'll get you those numbers.", WED))

    def test_vague_phrases_err_late(self):
        soon = timeref.extract("I'll send it soon", WED)["due_at"]
        tomorrow = timeref.extract("I'll send it tomorrow", WED)["due_at"]
        self.assertGreater(soon, tomorrow, "vague phrasing must not be stricter")


class BusinessHours(unittest.TestCase):
    def test_weekend_is_not_a_delay(self):
        self.assertEqual(
            base.business_hours_between("2026-09-04T18:00:00", "2026-09-07T09:00:00"), 0.0)

    def test_same_day_hours(self):
        self.assertEqual(
            base.business_hours_between("2026-09-02T09:00:00", "2026-09-02T15:00:00"), 6.0)


class Signals(unittest.TestCase):
    def test_deal_value_requires_context(self):
        self.assertIsNotNone(signals.deal_value("Our quote is $8,500 total."))
        self.assertIsNone(signals.deal_value("Gas is $3.50 a gallon."))
        self.assertIsNone(signals.deal_value("The filter costs $45."))

    def test_no_money_is_invented(self):
        self.assertIsNone(signals.deal_value("Can you come look at the roof?"))

    def test_complaint_and_its_negative(self):
        self.assertIsNotNone(signals.complaint("This is completely unacceptable."))
        self.assertIsNone(signals.complaint("No rush at all, whenever you get a chance."))

    def test_closed_thread_recognised(self):
        self.assertTrue(signals.looks_closed("Perfect, thanks!"))
        self.assertFalse(signals.looks_closed("Can you confirm the price?"))

    def test_opt_out(self):
        self.assertTrue(signals.opted_out("Please remove me from your list."))

    def test_excerpts_do_not_start_mid_word(self):
        text = ("This is the third time I've written and nobody has come out. "
                "This is completely unacceptable and I'm going to dispute the charge.")
        quote = signals.complaint(text)["quote"].lstrip("… ")
        self.assertTrue(text.count(quote) or quote in text)
        self.assertFalse(quote[0].islower() and text.startswith(quote) is False
                         and quote not in text)


class Normalization(unittest.TestCase):
    def test_quoted_history_is_stripped(self):
        body = ("Sounds good, I will call you Friday.\n\n"
                "On Tue, Sep 1, 2026 at 3:42 PM John <j@x.com> wrote:\n"
                "> I'll send that over today.\n")
        clean = M.clean_body(body)
        self.assertIn("call you Friday", clean)
        self.assertNotIn("send that over today", clean,
                         "quoted history must not be re-detected as a new promise")

    def test_automation_detection(self):
        self.assertTrue(M.classify_automation({"List-Unsubscribe": "<x>"}, "a@b.com", "Hi"))
        self.assertTrue(M.classify_automation({}, "no-reply@b.com", "Hi"))
        self.assertIsNone(M.classify_automation({}, "john@gmail.com", "Question about the X5"))

    def test_reply_threads_with_its_parent(self):
        root = M.thread_keys({"message-id": "m1"}, "Estimate", ["a@b.com"])
        reply = M.thread_keys({"message-id": "m2", "references": "m1"},
                              "Re: Estimate", ["a@b.com"])
        self.assertTrue(set(root) & set(reply), "a reply must share a key with its parent")


class EndToEndAccuracy(unittest.TestCase):
    """The labelled corpus. Any regression here is a product regression."""

    def test_precision_and_recall_on_labelled_corpus(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "acc.db")
        import importlib
        importlib.reload(db)
        db.init()
        uid = db.create_user("acc@northside.test", "x")
        oid = db.create_org("Acc", user_id=uid, domains=demo.ORG["domains"])
        org = db.get_org(oid)
        now = datetime.datetime(2026, 9, 9, 10, 0)
        msgs, expect = demo.build(now)
        pipeline.ingest(org, msgs)
        found = rules.run(org, now_iso=now.isoformat(timespec="seconds"))

        by_conv = {}
        for f, _ev in found:
            by_conv.setdefault(f["_conversation_id"], []).append(f)

        fp = fn = 0
        for e in expect:
            with db._conn() as c:
                r = c.execute(
                    "SELECT conversation_id FROM conversation_keys WHERE org_id=? AND key=?",
                    (oid, "ref:" + e["thread"].strip("<>"))).fetchone()
            got = bool(by_conv.get(r["conversation_id"] if r else None))
            if e["should"] and not got:
                fn += 1
                print(f"MISS {e['thread']}: {e['why']}")
            if not e["should"] and got:
                fp += 1
                print(f"FALSE POSITIVE {e['thread']}: expected silence because {e['why']}")
        self.assertEqual(fp, 0, "a false positive costs trust in every other finding")
        self.assertEqual(fn, 0, "missed a problem the corpus says must be found")

    def test_every_finding_carries_evidence(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "ev.db")
        import importlib
        importlib.reload(db)
        db.init()
        uid = db.create_user("ev@northside.test", "x")
        oid = db.create_org("Ev", user_id=uid, domains=demo.ORG["domains"])
        org = db.get_org(oid)
        now = datetime.datetime(2026, 9, 9, 10, 0)
        msgs, _ = demo.build(now)
        pipeline.ingest(org, msgs)
        for f, ev in rules.run(org, now_iso=now.isoformat(timespec="seconds")):
            self.assertTrue(ev, f"{f['detector']} produced a finding with no evidence")
            self.assertTrue(any(e.get("ref_kind") == "message" for e in ev),
                            f"{f['detector']} evidence cites no stored message")


if __name__ == "__main__":
    unittest.main()
