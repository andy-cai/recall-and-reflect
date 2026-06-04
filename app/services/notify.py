"""Gentle Windows toast reminders when reviews are due.

Optional and easily disabled in Settings. No-op on non-Windows platforms.
"""

import sys
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import (
    APP_NAME, HOST, NOTIFY_CHECK_INTERVAL_MIN, NOTIFY_COOLDOWN_MIN, PORT,
)
from app.db.repository import Repository


class ReminderService:
    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo or Repository()
        self._scheduler: Optional[BackgroundScheduler] = None
        self._last_notified: Optional[datetime] = None

    def start(self) -> None:
        if sys.platform != "win32":
            return
        self._scheduler = BackgroundScheduler(daemon=True)
        self._scheduler.add_job(
            self._check, "interval", minutes=NOTIFY_CHECK_INTERVAL_MIN,
            next_run_time=datetime.now() + timedelta(seconds=25),
        )
        self._scheduler.start()

    def stop(self) -> None:
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def _enabled(self) -> bool:
        return str(self.repo.get_setting("notifications", "1")) == "1"

    def _check(self) -> None:
        try:
            if not self._enabled():
                return
            due = self.repo.get_due_count()
            if due <= 0:
                return
            if self._last_notified and \
                    datetime.now() - self._last_notified < timedelta(minutes=NOTIFY_COOLDOWN_MIN):
                return
            self._notify(due)
            self._last_notified = datetime.now()
        except Exception:
            pass

    def _notify(self, due: int) -> None:
        from winotify import Notification
        n = Notification(
            app_id=APP_NAME,
            title=f"{due} review{'s' if due != 1 else ''} ready",
            msg="A few minutes of recall now keeps it from slipping away.",
            duration="short",
        )
        n.add_actions(label="Open Recall & Reflect", launch=f"http://{HOST}:{PORT}")
        n.show()
