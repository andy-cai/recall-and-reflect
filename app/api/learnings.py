"""Learnings + cards CRUD, and saving a captured learning."""

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.cloze import extract_cloze_cards
from app.db.repository import Repository
from app.services.llm import OllamaError, get_llm

router = APIRouter(prefix="/api", tags=["learnings"])


class CardIn(BaseModel):
    type: str = "basic"
    question: str = ""
    answer: str = ""
    source: str = ""


class LearningIn(BaseModel):
    title: str = ""
    content: str = ""
    reflection: Optional[str] = None
    subject: Optional[str] = None
    conversation: Optional[str] = None
    tags: list[str] = []
    cards: list[CardIn] = []
    recall_card: bool = True   # auto-add a free-recall prompt for the topic


def _derive_title(content: str) -> str:
    first = (content or "").strip().splitlines()[0] if content.strip() else "Untitled"
    first = first.strip().lstrip("#").strip()
    return (first[:70] + "…") if len(first) > 70 else (first or "Untitled")


def _persist_cards(repo: Repository, learning_id: int, cards: list[CardIn]) -> int:
    n = 0
    for c in cards:
        ctype = (c.type or "basic").strip().lower()
        if ctype == "cloze" and c.source.strip():
            for cc in extract_cloze_cards(c.source.strip()):
                repo.create_question(
                    learning_id, cc.question, cc.answer, card_type="cloze",
                    cloze_source=c.source.strip(), cloze_index=cc.index,
                )
                n += 1
        elif c.question.strip() and c.answer.strip():
            repo.create_question(learning_id, c.question.strip(), c.answer.strip())
            n += 1
    return n


@router.post("/learnings")
def create_learning(body: LearningIn):
    repo = Repository()
    title = body.title.strip() or _derive_title(body.content)
    lid = repo.create_learning(title, body.content.strip(), body.reflection,
                              subject=body.subject, tags=body.tags, conversation=body.conversation)
    n = _persist_cards(repo, lid, body.cards)
    if body.recall_card:
        repo.create_recall_card(lid, title, body.content.strip())
        n += 1
    return {"id": lid, "title": title, "cards": n}


@router.get("/learnings")
def list_learnings(search: str = "", tag: Optional[str] = None):
    repo = Repository()
    items = repo.list_learnings(search=search, tag=tag)
    return {
        "learnings": [
            {
                "id": it["learning"].id,
                "title": it["learning"].title,
                "subject": it["learning"].subject or "",
                "created_at": it["learning"].created_at.isoformat() if it["learning"].created_at else None,
                "tags": it["learning"].tags,
                "card_count": it["card_count"],
                "due_count": it["due_count"],
            }
            for it in items
        ],
        "tags": repo.all_tags(),
        "subjects": repo.subjects_summary(),
    }


@router.get("/learnings/{learning_id}")
def get_learning(learning_id: int):
    repo = Repository()
    learning = repo.get_learning(learning_id)
    if not learning:
        return JSONResponse({"error": "not_found"}, status_code=404)
    cards = repo.get_questions_for_learning(learning_id)
    return {
        "learning": {
            "id": learning.id, "title": learning.title, "content": learning.content,
            "reflection": learning.reflection, "subject": learning.subject or "",
            "conversation": learning.conversation, "notes": learning.notes or "",
            "tags": learning.tags,
            "created_at": learning.created_at.isoformat() if learning.created_at else None,
        },
        "cards": [
            {
                "id": c.id, "question": c.question, "answer": c.answer,
                "card_type": c.card_type, "cloze_source": c.cloze_source,
                "suspended": c.suspended, "state": c.state,
                "next_review_at": c.next_review_at.isoformat() if c.next_review_at else None,
                "stability": round(c.stability, 1),
            }
            for c in cards
        ],
    }


class LearningUpdate(BaseModel):
    title: str
    content: str
    reflection: Optional[str] = None
    subject: Optional[str] = None
    tags: list[str] = []


@router.put("/learnings/{learning_id}")
def update_learning(learning_id: int, body: LearningUpdate):
    repo = Repository()
    repo.update_learning(learning_id, body.title.strip(), body.content.strip(),
                         reflection=body.reflection, subject=body.subject, tags=body.tags)
    return {"ok": True}


@router.delete("/learnings/{learning_id}")
def delete_learning(learning_id: int):
    Repository().delete_learning(learning_id)
    return {"ok": True}


@router.post("/learnings/{learning_id}/cards")
def add_card(learning_id: int, body: CardIn):
    repo = Repository()
    n = _persist_cards(repo, learning_id, [body])
    return {"added": n}


class CardUpdate(BaseModel):
    question: str
    answer: str


@router.put("/cards/{card_id}")
def update_card(card_id: int, body: CardUpdate):
    Repository().update_question(card_id, body.question.strip(), body.answer.strip())
    return {"ok": True}


@router.delete("/cards/{card_id}")
def delete_card(card_id: int):
    Repository().delete_question(card_id)
    return {"ok": True}


class SuspendReq(BaseModel):
    suspended: bool


@router.post("/cards/{card_id}/suspend")
def suspend_card(card_id: int, body: SuspendReq):
    Repository().set_suspended(card_id, body.suspended)
    return {"ok": True}


# ---------- subjects ----------

@router.get("/subjects")
def list_subjects():
    repo = Repository()
    return {"subjects": repo.subjects_summary(), "names": repo.subject_names()}


@router.post("/subjects/suggest")
def suggest_subjects():
    """One LLM pass proposing a subject for each uncategorized note (for approval)."""
    repo = Repository()
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    items = repo.uncategorized_learnings()
    if not items:
        return {"suggestions": []}
    batch = items[:40]
    try:
        guesses = llm.suggest_subjects(
            [{"id": i["id"], "title": i["title"]} for i in batch], repo.subject_names())
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    by_id = {g["id"]: g["subject"] for g in guesses}
    return {"suggestions": [
        {"id": i["id"], "title": i["title"], "subject": by_id.get(i["id"], "")} for i in batch]}


class Assignment(BaseModel):
    id: int
    subject: str = ""


class AssignReq(BaseModel):
    assignments: list[Assignment]


@router.post("/subjects/assign")
def assign_subjects(body: AssignReq):
    repo = Repository()
    for a in body.assignments:
        repo.set_subject(a.id, a.subject.strip() or None)
    return {"updated": len(body.assignments)}
