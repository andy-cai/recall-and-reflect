"""Recall (review) endpoints: queue, AI grading (plain + rubric), rating (FSRS), undo."""

import json
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


def _serialize(q: Question, title: str, retention: float,
               ideas: Optional[list[dict]] = None) -> dict:
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
        # the rubric for topic-recall cards: reveal checklist + idea-based hints
        "ideas": [{"id": i["id"], "text": i["idea"]} for i in ideas] if ideas else [],
        # solid topics qualify for a teach-back swap-in (stability ≥ 3 weeks)
        "teach_eligible": q.card_type == "recall" and q.stability >= 21,
    }


@router.get("/queue")
def queue(tag: Optional[str] = None, learning_id: Optional[int] = None,
          subject: Optional[str] = None, limit: int = 200,
          focus: int = 0, mode: Optional[str] = None):
    repo = Repository()
    retention = repo.get_desired_retention()
    if mode == "evening":
        # wind-down: today's misses + today's captures, a small pass before sleep
        due = repo.evening_queue(limit=min(limit, 10))
    else:
        due = repo.get_due_questions(limit=limit, tag=tag, learning_id=learning_id,
                                     subject=subject, focus=bool(focus))

    titles: dict[int, str] = {}
    ideas: dict[int, list[dict]] = {}
    for q in due:
        if q.learning_id not in titles:
            learning = repo.get_learning(q.learning_id)
            titles[q.learning_id] = learning.title if learning else ""
        if q.card_type == "recall" and q.learning_id not in ideas:
            ideas[q.learning_id] = repo.get_key_ideas(q.learning_id)

    cards = [
        _serialize(q, titles.get(q.learning_id, ""), retention,
                   ideas.get(q.learning_id) if q.card_type == "recall" else None)
        for q in due
    ]
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

    # Topic recall with a rubric → grade per key idea (successive relearning).
    if q.card_type == "recall":
        ideas = repo.get_key_ideas(q.learning_id)
        if ideas:
            return _grade_rubric(repo, llm, q, ideas, req.recall)

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


def _grade_rubric(repo: Repository, llm, q: Question, ideas: list[dict], recall: str):
    learning = repo.get_learning(q.learning_id)
    topic = learning.title if learning else q.question
    try:
        graded = llm.grade_rubric(topic, [i["idea"] for i in ideas], recall)
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    results = [
        {"id": idea["id"], "text": idea["idea"], "result": res}
        for idea, res in zip(ideas, graded["results"])
    ]
    hits = sum(1 for r in results if r["result"] == "hit")
    verdict = ("correct" if hits == len(results)
               else "wrong" if not any(r["result"] in ("hit", "partial") for r in results)
               else "partial")

    # Tally per-idea outcomes; a 2-miss streak earns the idea its own drill card.
    drilled = []
    for idea in repo.record_idea_results([{"id": r["id"], "result": r["result"]} for r in results]):
        try:
            card = llm.drill_question(topic, idea["idea"])
        except OllamaError:
            continue
        repo.create_question(q.learning_id, card["question"], card["answer"])
        repo.mark_idea_drilled(idea["id"])
        drilled.append(card["question"])

    missed = [r["text"] for r in results if r["result"] == "miss"]
    return {
        "verdict": verdict,
        "missing": missed[0] if missed else "",
        "poke": graded["poke"],
        "ideas": results,
        "drilled": drilled,
    }


class AnswerReq(BaseModel):
    question_id: int
    rating: int
    recall: Optional[str] = None
    confidence: Optional[int] = None
    ai_verdict: Optional[str] = None
    elapsed_ms: Optional[int] = None
    bury: bool = True   # false for topic-scoped practice sessions
    idea_results: Optional[list[dict]] = None  # rubric outcomes from /grade


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
        idea_results=json.dumps(req.idea_results) if req.idea_results else None,
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


class RampReq(BaseModel):
    days: int = 5


@router.post("/ramp")
def ramp(req: RampReq):
    """Welcome-back mode: spread the overdue pile over the next N days,
    keeping today's most-at-risk allotment."""
    return Repository().ramp_backlog(req.days)
