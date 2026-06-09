"""Tests for queue shaping, sibling burying, hypercorrection, and activity stats.

Uses a throwaway SQLite file per test. Run: python -m unittest discover tests
"""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.db.database import Database, to_iso
from app.db.repository import Repository


def days_ago(n: float) -> str:
    return to_iso(datetime.now() - timedelta(days=n))


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = Database(Path(self._tmp.name) / "test.db")
        db.initialize()
        self.repo = Repository(db=db)

    def tearDown(self):
        self._tmp.cleanup()

    def make_topic(self, title: str, n_cards: int = 1) -> tuple[int, list[int]]:
        lid = self.repo.create_learning(title, f"content of {title}")
        qids = [
            self.repo.create_question(lid, f"{title} q{i}", f"{title} a{i}")
            for i in range(n_cards)
        ]
        return lid, qids

    def set_reviewed(self, qid: int, stability: float, reviewed_days_ago: float,
                     due_days_ago: float = 0.5):
        """Make a card a REVIEW-state card that is currently due."""
        self.repo.db.execute(
            "UPDATE questions SET state = 2, stability = ?, difficulty = 5, "
            "last_reviewed_at = ?, next_review_at = ? WHERE id = ?",
            (stability, days_ago(reviewed_days_ago), days_ago(due_days_ago), qid),
        )


class TestQueueShaping(RepoCase):
    def test_one_card_per_learning_per_fetch(self):
        self.make_topic("Mohr's circle", n_cards=4)
        queue = self.repo.get_due_questions()
        self.assertEqual(len(queue), 1)

    def test_learning_scoped_queue_keeps_all_cards(self):
        lid, _ = self.make_topic("Mohr's circle", n_cards=4)
        queue = self.repo.get_due_questions(learning_id=lid)
        self.assertEqual(len(queue), 4)

    def test_most_at_risk_reviews_come_first_then_new(self):
        _, (q_fresh,) = self.make_topic("hoop stress")
        _, (q_risky,) = self.make_topic("buckling")
        self.make_topic("brand new topic")  # NEW card, never reviewed
        self.set_reviewed(q_fresh, stability=10, reviewed_days_ago=1)    # high R
        self.set_reviewed(q_risky, stability=10, reviewed_days_ago=40)   # low R
        queue = self.repo.get_due_questions()
        self.assertEqual([q.id for q in queue[:2]], [q_risky, q_fresh])
        self.assertEqual(queue[2].state, 0)  # the new card rides last

    def test_new_per_day_budget(self):
        for i in range(5):
            self.make_topic(f"topic {i}")
        self.repo.set_setting("new_per_day", 2)
        queue = self.repo.get_due_questions()
        self.assertEqual(len(queue), 2)

    def test_limit_caps_session(self):
        for i in range(6):
            self.make_topic(f"topic {i}")
        queue = self.repo.get_due_questions(limit=3)
        self.assertEqual(len(queue), 3)


class TestBurying(RepoCase):
    def test_review_buries_due_siblings_to_tomorrow(self):
        lid, qids = self.make_topic("TTT diagrams", n_cards=3)
        q = self.repo.get_question(qids[0])
        self.assertEqual(self.repo.get_due_count(), 3)
        self.repo.apply_review(q, rating=3)
        self.assertEqual(self.repo.get_due_count(), 0)  # 1 scheduled out, 2 buried
        for sib in qids[1:]:
            nxt = self.repo.get_question(sib).next_review_at
            self.assertIsNotNone(nxt)
            self.assertGreater(nxt, datetime.now())
            self.assertEqual(self.repo.get_question(sib).state, 0)  # still NEW

    def test_bury_can_be_disabled_for_topic_practice(self):
        lid, qids = self.make_topic("TTT diagrams", n_cards=3)
        q = self.repo.get_question(qids[0])
        self.repo.apply_review(q, rating=3, bury_siblings=False)
        self.assertEqual(self.repo.get_due_count(), 2)

    def test_bury_does_not_touch_other_learnings(self):
        self.make_topic("other topic")
        lid, qids = self.make_topic("TTT diagrams", n_cards=2)
        self.repo.apply_review(self.repo.get_question(qids[0]), rating=3)
        self.assertEqual(self.repo.get_due_count(), 1)


class TestHypercorrection(RepoCase):
    def test_confident_miss_shortens_next_interval(self):
        _, (qa,) = self.make_topic("A")
        _, (qb,) = self.make_topic("B")
        self.set_reviewed(qa, stability=10, reviewed_days_ago=10)
        self.set_reviewed(qb, stability=10, reviewed_days_ago=10)
        plain = self.repo.apply_review(self.repo.get_question(qa), rating=2)
        hyper = self.repo.apply_review(self.repo.get_question(qb), rating=2,
                                       confidence=3, ai_verdict="wrong")
        self.assertLess(hyper.interval_days, plain.interval_days)


class TestKeyIdeas(RepoCase):
    def test_set_and_get_round_trip(self):
        lid, _ = self.make_topic("Hall-Petch")
        self.repo.set_key_ideas(lid, ["σy = σ0 + k/√d", "boundaries block dislocations", ""])
        ideas = self.repo.get_key_ideas(lid)
        self.assertEqual([i["idea"] for i in ideas],
                         ["σy = σ0 + k/√d", "boundaries block dislocations"])

    def test_editing_rubric_keeps_stats_for_unchanged_ideas(self):
        lid, _ = self.make_topic("Hall-Petch")
        self.repo.set_key_ideas(lid, ["kept idea", "dropped idea"])
        kept_id = self.repo.get_key_ideas(lid)[0]["id"]
        self.repo.record_idea_results([{"id": kept_id, "result": "miss"}])
        self.repo.set_key_ideas(lid, ["kept idea", "new idea"])
        ideas = {i["idea"]: i for i in self.repo.get_key_ideas(lid)}
        self.assertEqual(ideas["kept idea"]["misses"], 1)
        self.assertEqual(ideas["new idea"]["misses"], 0)

    def test_two_miss_streak_flags_drill_once(self):
        lid, _ = self.make_topic("Hall-Petch")
        self.repo.set_key_ideas(lid, ["inverse Hall-Petch at nano scale"])
        iid = self.repo.get_key_ideas(lid)[0]["id"]
        self.assertEqual(self.repo.record_idea_results([{"id": iid, "result": "miss"}]), [])
        flagged = self.repo.record_idea_results([{"id": iid, "result": "miss"}])
        self.assertEqual([f["id"] for f in flagged], [iid])
        self.repo.mark_idea_drilled(iid)
        self.assertEqual(self.repo.record_idea_results([{"id": iid, "result": "miss"}]), [])

    def test_hit_resets_streak(self):
        lid, _ = self.make_topic("Hall-Petch")
        self.repo.set_key_ideas(lid, ["idea"])
        iid = self.repo.get_key_ideas(lid)[0]["id"]
        self.repo.record_idea_results([{"id": iid, "result": "miss"}])
        self.repo.record_idea_results([{"id": iid, "result": "hit"}])
        flagged = self.repo.record_idea_results([{"id": iid, "result": "miss"}])
        self.assertEqual(flagged, [])


class TestFocus(RepoCase):
    def test_focused_topics_jump_the_queue(self):
        _, (q_risky,) = self.make_topic("unfocused but risky")
        lid, (q_focus,) = self.make_topic("focused topic")
        self.set_reviewed(q_risky, stability=10, reviewed_days_ago=60)  # very low R
        self.set_reviewed(q_focus, stability=10, reviewed_days_ago=2)   # high R
        self.repo.set_priority(lid, 1)
        queue = self.repo.get_due_questions()
        self.assertEqual(queue[0].id, q_focus)

    def test_focus_filter_only_returns_focused(self):
        self.make_topic("normal")
        lid, _ = self.make_topic("starred")
        self.repo.set_priority(lid, 1)
        queue = self.repo.get_due_questions(focus=True)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].learning_id, lid)

    def test_subject_priority_and_clear(self):
        lid_a, _ = self.make_topic("a")
        lid_b, _ = self.make_topic("b")
        self.repo.set_subject(lid_a, "Vibrations")
        self.repo.set_subject(lid_b, "Vibrations")
        self.repo.set_subject_priority("vibrations", 1)   # case-insensitive
        self.assertEqual(self.repo.focus_summary()["topics"], 2)
        self.assertEqual(self.repo.clear_focus(), 2)
        self.assertEqual(self.repo.focus_summary()["topics"], 0)

    def test_match_focus_text_fallback(self):
        lid, _ = self.make_topic("Mohr's circle sign convention")
        self.repo.set_subject(lid, "Mechanics of Materials")
        m = self.repo.match_focus_text("prioritize mechanics for the exam")
        self.assertIn("Mechanics of Materials", m["subjects"])
        m2 = self.repo.match_focus_text("mohr's circle")
        self.assertEqual([x["id"] for x in m2["learnings"]], [lid])


class TestRamp(RepoCase):
    def test_ramp_spreads_backlog_keeping_daily_target(self):
        self.repo.set_setting("daily_target", 2)
        self.repo.set_setting("new_per_day", 100)
        for i in range(8):
            _, (qid,) = self.make_topic(f"t{i}")
            self.set_reviewed(qid, stability=5, reviewed_days_ago=10 + i)
        self.assertEqual(self.repo.get_due_count(), 8)
        res = self.repo.ramp_backlog(days=3)
        self.assertEqual(res["moved"], 6)
        self.assertEqual(self.repo.get_due_count(), 2)
        # the two kept are the most at risk (longest since review)
        kept = {q.id for q in self.repo.get_due_questions()}
        self.assertEqual(len(kept), 2)

    def test_ramp_with_nothing_due(self):
        self.assertEqual(self.repo.ramp_backlog(days=5)["moved"], 0)


class TestEveningQueue(RepoCase):
    def test_misses_then_todays_captures(self):
        _, (q_missed,) = self.make_topic("missed today")
        _, (q_good,) = self.make_topic("aced today")
        self.repo.apply_review(self.repo.get_question(q_missed), rating=1)
        self.repo.apply_review(self.repo.get_question(q_good), rating=3)
        lid = self.repo.create_learning("captured tonight", "content")
        q_new = self.repo.create_recall_card(lid, "captured tonight", "content")
        evening = self.repo.evening_queue(limit=5)
        ids = [q.id for q in evening]
        self.assertIn(q_missed, ids)
        self.assertIn(q_new, ids)
        self.assertNotIn(q_good, ids)
        self.assertEqual(ids[0], q_missed)  # misses come first


class TestActivity(RepoCase):
    def test_capturing_counts_as_activity(self):
        self.make_topic("captured today")
        today = datetime.now().date().isoformat()
        self.assertEqual(self.repo.reviews_by_day().get(today), None)
        self.assertGreaterEqual(self.repo.activity_by_day().get(today, 0), 1)

    def test_at_risk_lists_lowest_retrievability(self):
        _, (qa,) = self.make_topic("fresh")
        _, (qb,) = self.make_topic("slipping")
        self.set_reviewed(qa, stability=10, reviewed_days_ago=1)
        self.set_reviewed(qb, stability=10, reviewed_days_ago=60)
        risk = self.repo.at_risk_cards(n=2)
        self.assertEqual(risk[0]["label"], "slipping q0")
        self.assertLess(risk[0]["retrievability"], risk[1]["retrievability"])


if __name__ == "__main__":
    unittest.main()
