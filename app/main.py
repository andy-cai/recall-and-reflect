"""FastAPI application: API routers + the static SPA, plus startup warm-up."""

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api import capture, learnings, review, settings as settings_api, stats
from app.config import APP_NAME, APP_VERSION, WEB_DIR
from app.db.database import get_database
from app.db.repository import Repository
from app.services.llm import OllamaError, get_llm
from app.services.notify import ReminderService

_reminder: ReminderService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_database()  # create schema if needed
    saved_model = Repository().get_setting("model")
    if saved_model:
        try:
            get_llm().set_model(saved_model)
        except OllamaError:
            pass
    threading.Thread(target=get_llm().warm, daemon=True).start()  # warm model off the hot path
    global _reminder
    _reminder = ReminderService(Repository())
    _reminder.start()
    yield
    if _reminder:
        _reminder.stop()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def no_store(request: Request, call_next):
    """Local single-user app — never let the browser cache stale JS/CSS/JSON."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


app.include_router(capture.router)
app.include_router(review.router)
app.include_router(learnings.router)
app.include_router(stats.router)
app.include_router(settings_api.router)

# The SPA. Mounted last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
