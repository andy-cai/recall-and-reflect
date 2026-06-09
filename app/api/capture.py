"""Reflect (capture) endpoints: streaming follow-up questions + card generation."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.db.repository import Repository
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
        generated = llm.generate_cards(req.transcript, n=max(1, min(8, req.n)), basic_only=True)
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"cards": generated}


class IdeasReq(BaseModel):
    transcript: str


@router.post("/ideas")
def ideas(req: IdeasReq):
    """Distill the conversation into key ideas — the rubric future recall is graded against."""
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    try:
        extracted = llm.extract_key_ideas(req.transcript)
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"ideas": extracted}


class SubjectReq(BaseModel):
    transcript: str


@router.post("/subject")
def suggest_subject(req: SubjectReq):
    """Suggest a subject area for what was just captured (prefers existing subjects)."""
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    try:
        subject = llm.suggest_subject(req.transcript, Repository().subject_names())
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"subject": subject}
