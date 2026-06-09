"""Tests for the FSRS-4.5 scheduler.

Anchors, invariants, and a frozen-snapshot sequence so the algorithm can never
silently drift again (the original port mixed the FSRS-v4 forgetting curve with
non-4.5 weights). Run: python -m unittest discover tests
"""

import unittest
from datetime import datetime, timedelta

from app.core.fsrs import (
    DECAY, DEFAULT_RETENTION, DEFAULT_WEIGHTS, FACTOR, CardState, Rating, State,
    _next_interval, format_interval, preview_intervals, retrievability, schedule,
)

NOW = datetime(2026, 6, 1, 9, 0, 0)


class TestForgettingCurve(unittest.TestCase):
    def test_full_strength_at_zero_elapsed(self):
        self.assertEqual(retrievability(5.0, 0.0), 1.0)

    def test_anchor_90_percent_at_t_equals_stability(self):
        # FSRS-4.5 anchor: R(S) = (1 + 19/81)^-0.5 = 0.9 exactly.
        for s in (0.5, 1.0, 7.3, 42.0):
            self.assertAlmostEqual(retrievability(s, s), 0.9, places=12)

    def test_curve_constants_are_fsrs_45(self):
        self.assertAlmostEqual(DECAY, -0.5)
        self.assertAlmostEqual(FACTOR, 19.0 / 81.0)
        self.assertAlmostEqual((1 + FACTOR) ** DECAY, 0.9, places=12)

    def test_monotonically_decreasing(self):
        vals = [retrievability(10.0, t) for t in (0, 1, 5, 10, 50, 200)]
        self.assertEqual(vals, sorted(vals, reverse=True))


class TestIntervals(unittest.TestCase):
    def test_interval_equals_stability_at_default_retention(self):
        # By construction R(S) = 0.9, so the 90% interval is the stability itself.
        for s in (1.0, 5.0, 30.7, 365.0):
            self.assertEqual(_next_interval(s, 0.90), max(1, round(s)))

    def test_higher_retention_means_shorter_interval(self):
        ivs = [_next_interval(30.0, r) for r in (0.80, 0.85, 0.90, 0.95)]
        self.assertEqual(ivs, sorted(ivs, reverse=True))

    def test_interval_floor_and_cap(self):
        self.assertEqual(_next_interval(0.1, 0.97), 1)
        self.assertEqual(_next_interval(1e9, 0.90), 36500)


class TestFirstReview(unittest.TestCase):
    def test_initial_stability_comes_from_weights(self):
        for rating in Rating:
            res = schedule(CardState(), rating, now=NOW)
            self.assertAlmostEqual(res.stability, max(0.1, DEFAULT_WEIGHTS[rating - 1]))

    def test_again_enters_learning_with_short_step(self):
        res = schedule(CardState(), Rating.AGAIN, now=NOW)
        self.assertEqual(res.state, State.LEARNING)
        self.assertEqual(res.next_review_at, NOW + timedelta(minutes=10))

    def test_good_enters_review_with_day_scale_interval(self):
        res = schedule(CardState(), Rating.GOOD, now=NOW)
        self.assertEqual(res.state, State.REVIEW)
        self.assertEqual(res.interval_days, round(DEFAULT_WEIGHTS[2]))

    def test_difficulty_ordering_easy_lowest(self):
        d = {r: schedule(CardState(), r, now=NOW).difficulty for r in Rating}
        self.assertGreater(d[Rating.AGAIN], d[Rating.GOOD])
        self.assertGreater(d[Rating.GOOD], d[Rating.EASY])


class TestSubsequentReviews(unittest.TestCase):
    def _card(self, s=5.0, d=5.0, days_ago=5):
        return CardState(state=State.REVIEW, stability=s, difficulty=d,
                         lapses=0, last_reviewed_at=NOW - timedelta(days=days_ago))

    def test_pass_grows_stability(self):
        res = schedule(self._card(), Rating.GOOD, now=NOW)
        self.assertGreater(res.stability, 5.0)

    def test_rating_ordering(self):
        s = {r: schedule(self._card(), r, now=NOW).stability for r in Rating}
        self.assertLess(s[Rating.AGAIN], s[Rating.HARD])
        self.assertLess(s[Rating.HARD], s[Rating.GOOD])
        self.assertLess(s[Rating.GOOD], s[Rating.EASY])

    def test_again_lapses_and_relearns(self):
        res = schedule(self._card(), Rating.AGAIN, now=NOW)
        self.assertEqual(res.state, State.RELEARNING)
        self.assertEqual(res.lapses, 1)
        self.assertLess(res.stability, 5.0)

    def test_preview_covers_all_ratings(self):
        p = preview_intervals(self._card(), now=NOW)
        self.assertEqual(set(p), set(Rating))


class TestFrozenSnapshot(unittest.TestCase):
    """A pinned multi-review trajectory. If any of these change, the scheduling
    behavior changed — that must be a deliberate, reviewed decision."""

    def test_good_good_again_good_sequence(self):
        card = CardState()
        t = NOW
        expected = [
            # (rating, days until next review, stability, difficulty) after each step
            (Rating.GOOD, 4, 3.7145, 5.1618),
            (Rating.GOOD, 15, 14.8081, 5.1618),
            (Rating.AGAIN, 0, 3.0776, 6.9012),
            (Rating.GOOD, 3, 3.0934, 6.8472),
        ]
        for rating, exp_interval, exp_s, exp_d in expected:
            res = schedule(card, rating, now=t, retention=DEFAULT_RETENTION)
            self.assertEqual(res.interval_days, exp_interval,
                             msg=f"interval after {rating.name}")
            self.assertAlmostEqual(res.stability, exp_s, places=3,
                                   msg=f"stability after {rating.name}")
            self.assertAlmostEqual(res.difficulty, exp_d, places=3,
                                   msg=f"difficulty after {rating.name}")
            card = CardState(state=res.state, stability=res.stability,
                             difficulty=res.difficulty, lapses=res.lapses,
                             last_reviewed_at=t)
            t = res.next_review_at


class TestFormatting(unittest.TestCase):
    def test_format_interval(self):
        self.assertEqual(format_interval(0), "<10m")
        self.assertEqual(format_interval(1), "1d")
        self.assertEqual(format_interval(6), "6d")
        self.assertEqual(format_interval(14), "2w")
        self.assertEqual(format_interval(60), "2mo")
        self.assertEqual(format_interval(730), "2y")


if __name__ == "__main__":
    unittest.main()
