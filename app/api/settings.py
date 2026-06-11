"""Settings + LLM status."""

import threading
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import CLOUD_MODELS, DEFAULT_GEN_STYLE, DEFAULT_MODEL
from app.db.repository import Repository
from app.services.cloud import get_cloud
from app.services.llm import OllamaError, get_llm, prompt_catalog

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
        "gen_style": repo.get_setting("gen_style", DEFAULT_GEN_STYLE),
        "cloud": {**get_cloud().status(), "models": list(CLOUD_MODELS)},
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
    gen_style: Optional[str] = None
    cloud_enabled: Optional[bool] = None
    cloud_model: Optional[str] = None


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
    if body.gen_style is not None:
        get_llm().set_gen_style(body.gen_style)
        repo.set_setting("gen_style", body.gen_style.strip() or DEFAULT_GEN_STYLE)
    if body.cloud_enabled is not None:
        get_cloud().set_enabled(body.cloud_enabled)
        repo.set_setting("cloud_enabled", "1" if body.cloud_enabled else "0")
    if body.cloud_model is not None:
        get_cloud().set_model(body.cloud_model)
        repo.set_setting("cloud_model", get_cloud().model)
    return {"ok": True}


@router.get("/llm/status")
def llm_status():
    return get_llm().status()


@router.get("/prompts")
def prompts():
    """Every system prompt the app sends, verbatim, with its routing — so
    Settings can show exactly what each model is asked to do."""
    llm = get_llm()
    cloud = get_cloud()
    return {
        "prompts": prompt_catalog(),
        "main_model": llm.resolve_model() or llm.preferred,
        "fast_model": llm.resolve_fast_model() or llm.preferred,
        "cloud_model": cloud.model,
        "cloud_ready": cloud.status()["ready"],
        "gen_style": llm.gen_style,
    }


@router.get("/cloud/log")
def cloud_log(limit: int = 100):
    """The audit trail: every request that ever went to Gemini (when, what,
    how many characters, how many People names were redacted first)."""
    return {"entries": Repository().cloud_log_entries(max(1, min(500, limit)))}


@router.post("/cloud/log/clear")
def clear_cloud_log():
    return {"cleared": Repository().clear_cloud_log()}
