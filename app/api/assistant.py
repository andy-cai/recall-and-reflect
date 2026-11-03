"""Ask R&R endpoints: /ask (read tools + proposals) and /confirm (executes a write)."""

import logging
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.assistant import Assistant, InvalidArgs

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
log = logging.getLogger(__name__)


class Turn(BaseModel):
    role: Optional[str] = "user"
    content: Optional[str] = ""


class AskReq(BaseModel):
    message: Optional[str] = ""
    history: list[Turn] = []


class ConfirmReq(BaseModel):
    tool: str = ""
    args: dict[str, Any] = {}


@router.post("/ask")
def ask(body: AskReq):
    try:
        return Assistant().ask(body.message, [t.model_dump() for t in body.history])
    except Exception as e:   # never a 500: the panel always gets a readable reply
        log.exception("assistant ask failed")
        return {"reply": f"Something went wrong: {e}", "actions": [], "available": True}


@router.post("/confirm")
def confirm(body: ConfirmReq):
    try:
        return Assistant().confirm(body.tool, body.args)
    except InvalidArgs as e:
        return JSONResponse({"error": str(e)}, status_code=400)
