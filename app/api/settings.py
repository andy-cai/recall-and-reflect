"""Settings + LLM status."""

import threading
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import DEFAULT_MODEL
from app.db.repository import Repository
from app.services.llm import OllamaError, get_llm

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def get_settings():
    repo = Repository()
    llm = get_llm()
    status = llm.status()
    return {
        "daily_target": repo.get_daily_target(),
        "desired_retention": repo.get_desired_retention(),
        "new_per_day": repo.get_new_per_day(),
        "notifications": str(repo.get_setting("notifications", "1")) == "1",
        "theme": repo.get_setting("theme", "dark"),
        "model": status["model"] or repo.get_setting("model", DEFAULT_MODEL),
        "fast_model": repo.get_setting("fast_model", ""),
        "llm": status,
    }


class SettingsUpdate(BaseModel):
    daily_target: Optional[int] = None
    desired_retention: Optional[float] = None
    new_per_day: Optional[int] = None
    notifications: Optional[bool] = None
    theme: Optional[str] = None
    model: Optional[str] = None
    fast_model: Optional[str] = None   # '' = use the main model for everything


@router.put("/settings")
def update_settings(body: SettingsUpdate):
    repo = Repository()
    if body.daily_target is not None:
        repo.set_setting("daily_target", max(1, min(500, body.daily_target)))
    if body.new_per_day is not None:
        repo.set_setting("new_per_day", max(1, min(100, body.new_per_day)))
    if body.desired_retention is not None:
        repo.set_setting("desired_retention", max(0.7, min(0.97, body.desired_retention)))
    if body.notifications is not None:
        repo.set_setting("notifications", "1" if body.notifications else "0")
    if body.theme is not None:
        repo.set_setting("theme", body.theme)
    if body.model is not None:
        try:
            get_llm().set_model(body.model)
            repo.set_setting("model", body.model)
            threading.Thread(target=get_llm().warm, daemon=True).start()
        except OllamaError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
    if body.fast_model is not None:
        try:
            get_llm().set_fast_model(body.fast_model)
            repo.set_setting("fast_model", body.fast_model)
        except OllamaError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True}


@router.get("/llm/status")
def llm_status():
    return get_llm().status()
