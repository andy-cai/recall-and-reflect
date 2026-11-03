"""FSRS-6 spaced-repetition scheduling, backed by the maintained `py-fsrs` package.

This module is a thin adapter: the algorithm itself (21 parameters, a trainable
forgetting-curve decay, native same-day / short-term memory) lives in
https://github.com/open-spaced-repetition/py-fsrs. The adapter keeps the app's
own interface (CardState in, ScheduleResult out, naive local datetimes) so the
rest of the code never touches py-fsrs types.

App-specific choices, all deliberate:
- One 10-minute learning step and one 10-minute relearning step, close to the
  app's original feel (Again -> back in 10 min, Hard -> 15 min, Good graduates).
- No interval fuzzing, so the interval previewed on a rating button is the one
  you get.
- `weights=None` uses py-fsrs's published defaults; pass fitted parameters
  (from the FSRS optimizer) to personalize.
Behavior is pinned by tests/test_fsrs.py.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from functools import lru_cache
from typing import Optional, Sequence

import fsrs as _fsrs


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


class State(IntEnum):
    # 1-3 match py-fsrs's State values; NEW is the app's "never reviewed".
    NEW = 0
    LEARNING = 1
    REVIEW = 2
    RELEARNING = 3


DEFAULT_WEIGHTS: tuple = tuple(_fsrs.Scheduler().parameters)
DEFAULT_RETENTION = 0.90
MAX_INTERVAL_DAYS = 36500
LEARNING_STEPS = (timedelta(minutes=10),)
RELEARNING_STEPS = (timedelta(minutes=10),)

# FSRS-6 forgetting curve: R(t) = (1 + FACTOR * t / S) ** DECAY, with
# DECAY = -w[20] and FACTOR chosen so that R(S) = 0.9 exactly.
DECAY = -DEFAULT_WEIGHTS[20]
FACTOR = 0.9 ** (1 / DECAY) - 1


@dataclass
class CardState:
    state: State = State.NEW
    stability: float = 0.0
    difficulty: float = 0.0
    lapses: int = 0
    last_reviewed_at: Optional[datetime] = None
    step: Optional[int] = None          # learning-step index (LEARNING/RELEARNING only)


@dataclass
class ScheduleResult:
    state: State
    stability: float
    difficulty: float
    lapses: int
    interval_days: int                  # 0 while in a (re)learning step
    next_review_at: datetime
    step: Optional[int] = None
    interval_minutes: int = 0           # set for (re)learning steps, else 0


# ---------- time conversion (app: naive local; py-fsrs: aware UTC) ----------

def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.astimezone()            # interpret naive values as local time
    return dt.astimezone(timezone.utc)


def _to_local_naive(dt: datetime) -> datetime:
    return dt.astimezone().replace(tzinfo=None)


@lru_cache(maxsize=32)
def _scheduler(retention: float, weights: tuple) -> "_fsrs.Scheduler":
    return _fsrs.Scheduler(
        parameters=weights,
        desired_retention=retention,
        learning_steps=LEARNING_STEPS,
        relearning_steps=RELEARNING_STEPS,
        maximum_interval=MAX_INTERVAL_DAYS,
        enable_fuzzing=False,
    )


def _to_fsrs_card(card: CardState, now: datetime) -> "_fsrs.Card":
    if card.state == State.NEW or card.stability <= 0:
        return _fsrs.Card(state=_fsrs.State.Learning, step=0)
    state = _fsrs.State(int(card.state))
    step = (card.step or 0) if state != _fsrs.State.Review else None
    last = card.last_reviewed_at or now
    return _fsrs.Card(
        state=state, step=step,
        stability=card.stability, difficulty=card.difficulty or 5.0,
        last_review=_to_utc(last), due=_to_utc(now),
    )


# ---------- public API ----------

def retrievability(stability: float, elapsed_days: float) -> float:
    """Current recall probability of a card (used for at-risk ranking).
    Continuous in elapsed time, unlike py-fsrs's whole-day version."""
    if stability <= 0:
        return 1.0
    return (1 + FACTOR * max(0.0, elapsed_days) / stability) ** DECAY


def schedule(
    card: CardState,
    rating: Rating,
    now: Optional[datetime] = None,
    retention: float = DEFAULT_RETENTION,
    weights: Optional[Sequence[float]] = None,
) -> ScheduleResult:
    """Compute the next schedule for a card given a rating."""
    now = now or datetime.now()
    sched = _scheduler(float(retention), tuple(weights) if weights else DEFAULT_WEIGHTS)
    was_review = card.state == State.REVIEW and card.stability > 0
    new, _log = sched.review_card(_to_fsrs_card(card, now), _fsrs.Rating(int(rating)),
                                  review_datetime=_to_utc(now))

    next_at = _to_local_naive(new.due)
    state = State(int(new.state))
    if state == State.REVIEW:
        interval_days = max(1, round((next_at - now).total_seconds() / 86400))
        interval_minutes = 0
    else:
        interval_days = 0
        interval_minutes = max(1, round((next_at - now).total_seconds() / 60))
    lapses = card.lapses + (1 if was_review and rating == Rating.AGAIN else 0)
    return ScheduleResult(
        state=state,
        stability=float(new.stability),
        difficulty=float(new.difficulty),
        lapses=lapses,
        interval_days=interval_days,
        next_review_at=next_at,
        step=new.step,
        interval_minutes=interval_minutes,
    )


def preview_intervals(
    card: CardState, now: Optional[datetime] = None, retention: float = DEFAULT_RETENTION,
    weights: Optional[Sequence[float]] = None,
) -> dict:
    """Return the scheduled result for each rating without persisting."""
    now = now or datetime.now()
    return {r: schedule(card, r, now, retention, weights) for r in Rating}


def format_interval(days: int, minutes: int = 0) -> str:
    if days <= 0:
        if minutes:
            return f"{minutes}m" if minutes < 60 else f"{round(minutes / 60)}h"
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


def format_result(res: ScheduleResult) -> str:
    return format_interval(res.interval_days, res.interval_minutes)


RATING_LABEL = {
    Rating.AGAIN: "Again",
    Rating.HARD: "Hard",
    Rating.GOOD: "Good",
    Rating.EASY: "Easy",
}
