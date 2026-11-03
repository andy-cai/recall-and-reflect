"""Tests for the FSRS-6 scheduler adapter (app/core/fsrs.py over py-fsrs).

Three layers: (1) the curve and constants match py-fsrs's own, (2) the adapter
agrees with calling py-fsrs directly, (3) a frozen trajectory, so any change in
scheduling behavior (including a py-fsrs upgrade) is a deliberate decision.
Run: python -m unittest discover tests
"""

import unittest
from datetime import datetime, timedelta, timezone

import fsrs as ref

from app.core.fsrs import (
    DECAY, DEFAULT_RETENTION, DEFAULT_WEIGHTS, FACTOR, CardState, Rating, State,
    format_interval, format_result, preview_intervals, retrievability, schedule,
)

NOW = datetime(2026, 6, 1, 9, 0, 0)   # naive local, as the app stores it


def _review_card(s=5.0, d=5.0, days_ago=5):
    return CardState(state=State.REVIEW, stability=s, difficulty=d,
                     lapses=0, last_reviewed_at=NOW - timedelta(days=days_ago))


class TestCurve(unittest.TestCase):
    def test_parameters_are_py_fsrs_defaults(self):
        self.assertEqual(len(DEFAULT_WEIGHTS), 21)
        self.assertEqual(DEFAULT_WEIGHTS, tuple(ref.Scheduler().parameters))

    def test_anchor_90_percent_at_t_equals_stability(self):
        for s in (0.5, 1.0, 7.3, 42.0):
            self.assertAlmostEqual(retrievability(s, s), 0.9, places=12)

    def test_decay_is_trainable_w20(self):
        self.assertAlmostEqual(DECAY, -DEFAULT_WEIGHTS[20])
        self.assertAlmostEqual((1 + FACTOR) ** DECAY, 0.9, places=12)

    def test_monotone_and_full_at_zero(self):
        self.assertEqual(retrievability(5.0, 0.0), 1.0)
        vals = [retrievability(10.0, t) for t in (0, 1, 5, 10, 50, 200)]
        self.assertEqual(vals, sorted(vals, reverse=True))

    def test_matches_reference_on_whole_days(self):
        sched = ref.Scheduler(enable_fuzzing=False)
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        card = ref.Card(state=ref.State.Review, step=None, stability=12.0, difficulty=5.0,
                        last_review=now - timedelta(days=9), due=now)
        self.assertAlmostEqual(retrievability(12.0, 9), sched.get_card_retrievability(card, now),
                               places=12)


class TestAgreesWithReference(unittest.TestCase):
    def test_review_card_matches_py_fsrs(self):
        sched = ref.Scheduler(enable_fuzzing=False, learning_steps=(timedelta(minutes=10),),
                              relearning_steps=(timedelta(minutes=10),))
        utc_now = NOW.astimezone().astimezone(timezone.utc)
        for rating in Rating:
            ours = schedule(_review_card(), rating, now=NOW)
            card = ref.Card(state=ref.State.Review, step=None, stability=5.0, difficulty=5.0,
                            last_review=utc_now - timedelta(days=5), due=utc_now)
            theirs, _ = sched.review_card(card, ref.Rating(int(rating)), review_datetime=utc_now)
            self.assertAlmostEqual(ours.stability, theirs.stability, places=9)
            self.assertAlmostEqual(ours.difficulty, theirs.difficulty, places=9)
            self.assertEqual(ours.next_review_at,
                             theirs.due.astimezone().replace(tzinfo=None))


class TestNewCards(unittest.TestCase):
    def test_initial_stability_comes_from_weights(self):
        for rating in Rating:
            res = schedule(CardState(), rating, now=NOW)
            self.assertAlmostEqual(res.stability, DEFAULT_WEIGHTS[rating - 1], places=6)

    def test_again_is_a_ten_minute_step(self):
        res = schedule(CardState(), Rating.AGAIN, now=NOW)
        self.assertEqual(res.state, State.LEARNING)
        self.assertEqual(res.step, 0)
        self.assertEqual(res.next_review_at, NOW + timedelta(minutes=10))
        self.assertEqual(format_result(res), "10m")

    def test_hard_is_fifteen_minutes(self):
        res = schedule(CardState(), Rating.HARD, now=NOW)
        self.assertEqual(res.state, State.LEARNING)
        self.assertEqual(res.interval_minutes, 15)

    def test_good_graduates_to_review(self):
        res = schedule(CardState(), Rating.GOOD, now=NOW)
        self.assertEqual(res.state, State.REVIEW)
        self.assertIsNone(res.step)
        self.assertGreaterEqual(res.interval_days, 1)

    def test_difficulty_ordering_easy_lowest(self):
        d = {r: schedule(CardState(), r, now=NOW).difficulty for r in Rating}
        self.assertGreater(d[Rating.AGAIN], d[Rating.GOOD])
        self.assertGreater(d[Rating.GOOD], d[Rating.EASY])


class TestReviewCards(unittest.TestCase):
    def test_pass_grows_stability(self):
        self.assertGreater(schedule(_review_card(), Rating.GOOD, now=NOW).stability, 5.0)

    def test_rating_ordering(self):
        s = {r: schedule(_review_card(), r, now=NOW).stability for r in Rating}
        self.assertLess(s[Rating.AGAIN], s[Rating.HARD])
        self.assertLess(s[Rating.HARD], s[Rating.GOOD])
        self.assertLess(s[Rating.GOOD], s[Rating.EASY])

    def test_again_lapses_and_relearns(self):
        res = schedule(_review_card(), Rating.AGAIN, now=NOW)
        self.assertEqual(res.state, State.RELEARNING)
        self.assertEqual(res.lapses, 1)
        self.assertEqual(res.step, 0)
        self.assertLess(res.stability, 5.0)

    def test_higher_retention_means_shorter_interval(self):
        ivs = [schedule(_review_card(s=30.0, days_ago=30), Rating.GOOD, now=NOW,
                        retention=r).interval_days for r in (0.80, 0.85, 0.90, 0.95)]
        self.assertEqual(ivs, sorted(ivs, reverse=True))
        self.assertGreater(ivs[0], ivs[-1])

    def test_custom_weights_are_used(self):
        w = list(DEFAULT_WEIGHTS)
        w[2] = 10.0   # initial stability for Good
        self.assertAlmostEqual(schedule(CardState(), Rating.GOOD, now=NOW, weights=w).stability,
                               10.0, places=6)

    def test_stepless_legacy_learning_card_is_accepted(self):
        # Cards in LEARNING from the pre-py-fsrs schema have no stored step.
        legacy = CardState(state=State.LEARNING, stability=0.5, difficulty=7.0,
                           last_reviewed_at=NOW - timedelta(minutes=20), step=None)
        res = schedule(legacy, Rating.GOOD, now=NOW)
        self.assertEqual(res.state, State.REVIEW)

    def test_preview_covers_all_ratings(self):
        self.assertEqual(set(preview_intervals(_review_card(), now=NOW)), set(Rating))


class TestFrozenSnapshot(unittest.TestCase):
    """A pinned multi-review trajectory. If any of these change, the scheduling
    behavior changed (e.g. a py-fsrs upgrade) — that must be a reviewed decision."""

    def test_good_good_again_good_sequence(self):
        card = CardState()
        t = NOW
        expected = [
            # (rating, days until next review, stability, difficulty) after each step
            (Rating.GOOD, 2, 2.3065, 2.1181),
            (Rating.GOOD, 11, 10.9643, 2.1112),
            (Rating.AGAIN, 0, 1.5383, 7.3922),    # relearning step: back in 10 min
            (Rating.GOOD, 2, 1.5712, 7.3801),
        ]
        for rating, exp_interval, exp_s, exp_d in expected:
            res = schedule(card, rating, now=t, retention=DEFAULT_RETENTION)
            self.assertEqual(res.interval_days, exp_interval, msg=f"interval after {rating.name}")
            self.assertAlmostEqual(res.stability, exp_s, places=3,
                                   msg=f"stability after {rating.name}")
            self.assertAlmostEqual(res.difficulty, exp_d, places=3,
                                   msg=f"difficulty after {rating.name}")
            card = CardState(state=res.state, stability=res.stability, difficulty=res.difficulty,
                             lapses=res.lapses, last_reviewed_at=t, step=res.step)
            t = res.next_review_at


class TestFormatting(unittest.TestCase):
    def test_format_interval(self):
        self.assertEqual(format_interval(0), "<10m")
        self.assertEqual(format_interval(0, 15), "15m")
        self.assertEqual(format_interval(0, 120), "2h")
        self.assertEqual(format_interval(1), "1d")
        self.assertEqual(format_interval(6), "6d")
        self.assertEqual(format_interval(14), "2w")
        self.assertEqual(format_interval(60), "2mo")
        self.assertEqual(format_interval(730), "2y")


if __name__ == "__main__":
    unittest.main()
