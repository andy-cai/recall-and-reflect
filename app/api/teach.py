"""Feynman teach-back: the model plays a confused first-year student.

The learner explains a topic; the student asks naive why/how questions and flags
undefined jargon. Wrapping up applies a normal FSRS review to the topic's recall
card and appends the transcript to the topic's reflection."""

import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.db.repository import Repository
from app.services.llm import OllamaError, get_llm

router = APIRouter(prefix="/api/teach", tags=["teach"])


class Msg(BaseModel):
    role: str
    content: str


class TurnReq(BaseModel):
    learning_id: int
    messages: list[Msg]


@router.post("/turn")
def turn(req: TurnReq):
    """Stream the student's next question (plain text chunks)."""
    repo = Repository()
    learning = repo.get_learning(req.learning_id)
    if not learning:
        return JSONResponse({"error": "not_found"}, status_code=404)
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)

    history = [{"role": m.role, "content": m.content} for m in req.messages]

    def gen():
        try:
            for piece in llm.teach_student_stream(learning.title, history):
                yield piece
        except OllamaError:
            return

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


class FinishReq(BaseModel):
    learning_id: int
    messages: list[Msg]
    rating: int


@router.post("/finish")
def finish(req: FinishReq):
    """Teach-back done: log the transcript, count it as a review of the topic."""
    repo = Repository()
    learning = repo.get_learning(req.learning_id)
    if not learning:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if req.rating not in (1, 2, 3, 4):
        return JSONResponse({"error": "bad_rating"}, status_code=400)

    if req.messages:
        lines = [f"{'Me' if m.role == 'user' else 'Student'}: {m.content}"
                 for m in req.messages]
        stamp = datetime.now().strftime("%Y-%m-%d")
        repo.append_reflection(req.learning_id,
                               f"Teach-back {stamp}:\n" + "\n".join(lines))

    result = None
    card = repo.get_recall_card(req.learning_id)
    if card:
        transcript = json.dumps([m.model_dump() for m in req.messages])[:8000]
        result = repo.apply_review(card, req.rating, recall_text=transcript,
                                   ai_verdict=None, confidence=None)
    return {
        "ok": True,
        "reviewed": card.id if card else None,
        "next_review_at": result.next_review_at.isoformat() if result else None,
    }
