"""FSRS-4.5 spaced-repetition scheduler.

The open FSRS-4.5 algorithm with its published default weights (trained on a large
review corpus). FSRS-4.5's forgetting curve is R = (1 + 19/81 · t/S)^-0.5, anchored
so that R(S) = 0.90 exactly; weights and curve must always move together — they are
fitted jointly. Weights can be refitted to the user's own review log once enough
history exists. Reference: https://github.com/open-spaced-repetition/fsrs4anki
Behavior is pinned by tests/test_fsrs.py.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class State(IntEnum):
    NEW = 0
    LEARNING = 1
    REVIEW = 2
    RELEARNING = 3


DEFAULT_WEIGHTS = (
    0.4872, 1.4003, 3.7145, 13.8206,
    5.1618, 1.2298, 0.8975, 0.031,
    1.6474, 0.1367, 1.0461, 2.1072,
    0.0793, 0.3246, 1.587, 0.2272, 2.8755,
)

DEFAULT_RETENTION = 0.90
MAX_INTERVAL_DAYS = 36500

# FSRS-4.5 forgetting-curve constants: R(t) = (1 + FACTOR * t / S) ** DECAY.
# FACTOR is chosen so that R(S) = 0.9 exactly: (1 + 19/81) ** -0.5 == 0.9.
DECAY = -0.5
FACTOR = 19.0 / 81.0


@dataclass
class CardState:
    state: State = State.NEW
    stability: float = 0.0
    difficulty: float = 0.0
    lapses: int = 0
    last_reviewed_at: datetime | None = None


@dataclass
class ScheduleResult:
    state: State
    stability: float
    difficulty: float
    lapses: int
    interval_days: int
    next_review_at: datetime


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _init_stability(rating: Rating, w) -> float:
    return max(0.1, w[rating - 1])


def _init_difficulty(rating: Rating, w) -> float:
    return _clamp(w[4] - (rating - 3) * w[5], 1.0, 10.0)


def _retrievability(stability: float, elapsed_days: float) -> float:
    if stability <= 0:
        return 1.0
    return (1 + FACTOR * elapsed_days / stability) ** DECAY


def retrievability(stability: float, elapsed_days: float) -> float:
    """Current recall probability of a card (public: used for at-risk ranking)."""
    return _retrievability(stability, max(0.0, elapsed_days))


def _next_recall_stability(d: float, s: float, r: float, rating: Rating, w) -> float:
    hard_penalty = w[15] if rating == Rating.HARD else 1.0
    easy_bonus = w[16] if rating == Rating.EASY else 1.0
    return s * (
        1
        + math.exp(w[8])
        * (11 - d)
        * (s ** -w[9])
        * (math.exp(w[10] * (1 - r)) - 1)
        * hard_penalty
        * easy_bonus
    )


def _next_forget_stability(d: float, s: float, r: float, w) -> float:
    return (
        w[11]
        * (d ** -w[12])
        * (((s + 1) ** w[13]) - 1)
        * math.exp((1 - r) * w[14])
    )


def _mean_reversion(init: float, current: float, w) -> float:
    return w[7] * init + (1 - w[7]) * current


def _next_difficulty(d: float, rating: Rating, w) -> float:
    next_d = d - w[6] * (rating - 3)
    return _clamp(_mean_reversion(w[4], next_d, w), 1.0, 10.0)


def _next_interval(stability: float, retention: float) -> int:
    # Inverse of the forgetting curve: the t at which R(t) drops to `retention`.
    interval = max(1, round(stability / FACTOR * (retention ** (1 / DECAY) - 1)))
    return min(interval, MAX_INTERVAL_DAYS)


def schedule(
    card: CardState,
    rating: Rating,
    now: datetime | None = None,
    retention: float = DEFAULT_RETENTION,
    weights=DEFAULT_WEIGHTS,
) -> ScheduleResult:
    """Compute the next schedule for a card given a rating."""
    now = now or datetime.now()
    w = weights

    if card.state == State.NEW:
        stability = _init_stability(rating, w)
        difficulty = _init_difficulty(rating, w)
        new_state = State.LEARNING if rating == Rating.AGAIN else State.REVIEW
        lapses = card.lapses
    else:
        elapsed_days = 0.0
        if card.last_reviewed_at is not None:
            elapsed_days = max(0.0, (now - card.last_reviewed_at).total_seconds() / 86400)
        r = _retrievability(card.stability, elapsed_days)
        difficulty = _next_difficulty(card.difficulty, rating, w)

        if rating == Rating.AGAIN:
            stability = _next_forget_stability(difficulty, card.stability, r, w)
            new_state = State.RELEARNING
            lapses = card.lapses + 1
        else:
            stability = _next_recall_stability(difficulty, card.stability, r, rating, w)
            new_state = State.REVIEW
            lapses = card.lapses

    if new_state in (State.LEARNING, State.RELEARNING):
        if rating == Rating.AGAIN:
            interval = 0
            next_at = now + timedelta(minutes=10)
        elif rating == Rating.HARD:
            interval = 0
            next_at = now + timedelta(minutes=30)
        else:
            interval = 1
            next_at = now + timedelta(days=1)
    else:
        interval = _next_interval(stability, retention)
        next_at = now + timedelta(days=interval)

    return ScheduleResult(
        state=new_state,
        stability=stability,
        difficulty=difficulty,
        lapses=lapses,
        interval_days=interval,
        next_review_at=next_at,
    )


def preview_intervals(
    card: CardState, now: datetime | None = None, retention: float = DEFAULT_RETENTION
) -> dict[Rating, ScheduleResult]:
    """Return the scheduled result for each rating without persisting."""
    return {r: schedule(card, r, now, retention) for r in Rating}


def format_interval(days: int) -> str:
    if days <= 0:
        return "<10m"
    if days == 1:
        return "1d"
    if days < 7:
        return f"{days}d"
    if days < 30:
        weeks = round(days / 7)
        return f"{weeks}w"
    if days < 365:
        months = round(days / 30)
        return f"{months}mo"
    years = round(days / 365 * 10) / 10
    return f"{years:g}y"


RATING_LABEL = {
    Rating.AGAIN: "Again",
    Rating.HARD: "Hard",
    Rating.GOOD: "Good",
    Rating.EASY: "Easy",
}
