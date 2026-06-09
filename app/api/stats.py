"""Stats + the Today home summary."""

from datetime import date, timedelta

from fastapi import APIRouter

from app.db.repository import Repository
from app.services.llm import get_llm

router = APIRouter(prefix="/api", tags=["stats"])


def _streak(by_day: dict[str, int]) -> int:
    """Consecutive active days ending today (with a one-day grace for 'today not done yet')."""
    today = date.today()
    cursor = today
    if by_day.get(today.isoformat(), 0) == 0:
        cursor = today - timedelta(days=1)  # don't zero the streak just because today is pending
    streak = 0
    while by_day.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _consistency(by_day: dict[str, int], window: int = 14) -> int:
    today = date.today()
    active = sum(
        1 for i in range(window)
        if by_day.get((today - timedelta(days=i)).isoformat(), 0) > 0
    )
    return round(active / window * 100)


@router.get("/today")
def today():
    repo = Repository()
    # Streak/consistency/heatmap count *activity* (reviews + captures):
    # a day spent reflecting is showing up, not a dead day.
    by_day = repo.activity_by_day(365)
    return {
        "due": repo.get_due_count(),
        "reviews_today": repo.reviews_today(),
        "daily_target": repo.get_daily_target(),
        "streak": _streak(by_day),
        "consistency": _consistency(by_day),
        "heatmap": by_day,
        "totals": repo.total_counts(),
        "at_risk": repo.at_risk_cards(3),
        "focus": repo.focus_summary(),
        "gap_days": repo.days_since_last_activity(),
        "llm": get_llm().status(),
    }


@router.get("/stats")
def stats():
    repo = Repository()
    by_day = repo.reviews_by_day(365)
    activity = repo.activity_by_day(365)
    retention = repo.retention_rate(30)
    return {
        "totals": repo.total_counts(),
        "retention_30": round(retention * 100, 1) if retention is not None else None,
        "reviews_by_day": by_day,
        "heatmap": activity,
        "maturity": repo.maturity_breakdown(),
        "forecast": repo.due_forecast(14),
        "reviews_today": repo.reviews_today(),
        "daily_target": repo.get_daily_target(),
        "streak": _streak(activity),
        "consistency": _consistency(activity),
        "desired_retention": repo.get_desired_retention(),
        "calibration": repo.calibration(90),
    }
