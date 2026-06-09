"""Recall (review) endpoints: queue, AI grading, rating (FSRS), undo."""

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.cloze import render_answer, render_question
from app.core.fsrs import CardState, State, format_interval, preview_intervals
from app.db.models import Question
from app.db.repository import Repository
from app.services.llm import OllamaError, get_llm

router = APIRouter(prefix="/api/review", tags=["review"])


def _serialize(q: Question, title: str, retention: float) -> dict:
    if q.card_type == "cloze" and q.cloze_source and q.cloze_index is not None:
        front = render_question(q.cloze_source, q.cloze_index)
        answer = render_answer(q.cloze_source, q.cloze_index)
    else:
        front = q.question
        answer = q.answer

    card = CardState(
        state=State(q.state), stability=q.stability, difficulty=q.difficulty,
        lapses=q.lapses, last_reviewed_at=q.last_reviewed_at,
    )
    preview = preview_intervals(card, retention=retention)
    intervals = {r.name.lower(): format_interval(res.interval_days) for r, res in preview.items()}

    return {
        "id": q.id,
        "learning_id": q.learning_id,
        "card_type": q.card_type,
        "front": front,
        "answer": answer,
        "reference": q.answer if q.card_type != "cloze" else answer,
        "source": q.cloze_source,
        "title": title,
        "is_new": q.state == State.NEW,
        "intervals": intervals,
    }


@router.get("/queue")
def queue(tag: Optional[str] = None, learning_id: Optional[int] = None,
          subject: Optional[str] = None, limit: int = 200):
    repo = Repository()
    retention = repo.get_desired_retention()
    due = repo.get_due_questions(limit=limit, tag=tag, learning_id=learning_id, subject=subject)

    titles: dict[int, str] = {}
    for q in due:
        if q.learning_id not in titles:
            learning = repo.get_learning(q.learning_id)
            titles[q.learning_id] = learning.title if learning else ""

    cards = [_serialize(q, titles.get(q.learning_id, ""), retention) for q in due]
    return {"cards": cards, "llm": get_llm().status()["available"]}


class GradeReq(BaseModel):
    question_id: int
    recall: str = ""


@router.post("/grade")
def grade(req: GradeReq):
    repo = Repository()
    q = repo.get_question(req.question_id)
    if not q:
        return JSONResponse({"error": "not_found"}, status_code=404)
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)

    if q.card_type == "cloze" and q.cloze_source and q.cloze_index is not None:
        front = render_question(q.cloze_source, q.cloze_index)
        reference = render_answer(q.cloze_source, q.cloze_index)
    else:
        front, reference = q.question, q.answer

    try:
        result = llm.grade_recall(front, reference, req.recall)
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return result


class AnswerReq(BaseModel):
    question_id: int
    rating: int
    recall: Optional[str] = None
    confidence: Optional[int] = None
    ai_verdict: Optional[str] = None
    elapsed_ms: Optional[int] = None
    bury: bool = True   # false for topic-scoped practice sessions


@router.post("/answer")
def answer(req: AnswerReq):
    repo = Repository()
    q = repo.get_question(req.question_id)
    if not q:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if req.rating not in (1, 2, 3, 4):
        return JSONResponse({"error": "bad_rating"}, status_code=400)

    result = repo.apply_review(
        q, req.rating, recall_text=req.recall, confidence=req.confidence,
        ai_verdict=req.ai_verdict, elapsed_ms=req.elapsed_ms, bury_siblings=req.bury,
    )
    return {
        "interval_days": result.interval_days,
        "interval_label": format_interval(result.interval_days),
        "next_review_at": result.next_review_at.isoformat(),
        "due": repo.get_due_count(),
    }


@router.post("/undo")
def undo():
    qid = Repository().undo_last_review()
    return {"question_id": qid}
