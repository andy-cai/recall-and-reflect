"""Reflect (capture) endpoints: streaming follow-up questions + card generation."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.services.llm import OllamaError, get_llm

router = APIRouter(prefix="/api/capture", tags=["capture"])


class Msg(BaseModel):
    role: str
    content: str


class FollowupReq(BaseModel):
    messages: list[Msg]


class CardsReq(BaseModel):
    transcript: str
    n: int = 4


@router.post("/followup")
def followup(req: FollowupReq):
    """Stream the AI's next single follow-up question (plain text chunks)."""
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)

    history = [{"role": m.role, "content": m.content} for m in req.messages]

    def gen():
        try:
            for piece in llm.capture_followup_stream(history):
                yield piece
        except OllamaError:
            return

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@router.post("/cards")
def cards(req: CardsReq):
    """Generate draft cards from the capture conversation."""
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    try:
        generated = llm.generate_cards(req.transcript, n=max(1, min(8, req.n)))
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"cards": generated}
