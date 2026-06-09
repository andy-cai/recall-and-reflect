"""Learnings + cards CRUD, and saving a captured learning."""

import threading
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.cloze import extract_cloze_cards
from app.db.repository import Repository
from app.services.cloud import CloudError, get_cloud
from app.services.embeddings import get_embeddings
from app.services.llm import OllamaError, get_llm

router = APIRouter(prefix="/api", tags=["learnings"])

CONTRAST_FLOOR = 0.86   # similarity above which two topics look confusable


def _embed_async(learning_id: int, title: str, content: str) -> None:
    """Embed off the hot path; failures are silent (no embed model running)."""
    threading.Thread(
        target=lambda: get_embeddings().ensure(learning_id, title, content),
        daemon=True,
    ).start()


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
    key_ideas: list[str] = []  # the rubric the topic's free recall is graded against
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
    if body.key_ideas:
        repo.set_key_ideas(lid, body.key_ideas)
    if body.recall_card:
        repo.create_recall_card(lid, title, body.content.strip())
        n += 1
    _embed_async(lid, title, body.content)
    return {"id": lid, "title": title, "cards": n}


@router.get("/learnings")
def list_learnings(search: str = "", tag: Optional[str] = None):
    repo = Repository()
    items = repo.list_learnings(search=search, tag=tag)
    # Semantic enrich: "plasticity onset" should find Luder's bands even though
    # no word matches. Appended after the literal hits, best-effort.
    if search and not tag:
        emb = get_embeddings()
        if emb.model_available():
            near = emb.nearest_to_text(search, k=8, floor=0.45)
            have = {it["learning"].id for it in items}
            wanted = [n["learning_id"] for n in near if n["learning_id"] not in have]
            if wanted:
                by_id = {it["learning"].id: it
                         for it in repo.list_learnings(search="", tag=None, limit=1000)}
                items += [by_id[lid] for lid in wanted if lid in by_id]
    return {
        "learnings": [
            {
                "id": it["learning"].id,
                "title": it["learning"].title,
                "subject": it["learning"].subject or "",
                "priority": it["learning"].priority,
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
            "priority": learning.priority, "tags": learning.tags,
            "created_at": learning.created_at.isoformat() if learning.created_at else None,
        },
        "key_ideas": repo.get_key_ideas(learning_id),
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
    notes: Optional[str] = None
    tags: list[str] = []
    key_ideas: Optional[list[str]] = None


@router.put("/learnings/{learning_id}")
def update_learning(learning_id: int, body: LearningUpdate):
    repo = Repository()
    repo.update_learning(learning_id, body.title.strip(), body.content.strip(),
                         reflection=body.reflection, subject=body.subject,
                         tags=body.tags, notes=body.notes)
    if body.key_ideas is not None:
        repo.set_key_ideas(learning_id, body.key_ideas)
    _embed_async(learning_id, body.title, body.content)
    return {"ok": True}


# ---------- related concepts / contrast cards (local embeddings) ----------

@router.get("/learnings/{learning_id}/related")
def related(learning_id: int):
    repo = Repository()
    learning = repo.get_learning(learning_id)
    if not learning:
        return JSONResponse({"error": "not_found"}, status_code=404)
    emb = get_embeddings()
    if not emb.model_available():
        return {"related": [], "contrast": None, "embeddings": False}
    emb.ensure(learning_id, learning.title, learning.content)
    emb.backfill(24)   # opportunistically embed the rest of the library
    near = emb.nearest(learning_id, k=5)
    out = []
    for n in near:
        other = repo.get_learning(n["learning_id"])
        if other:
            out.append({"id": other.id, "title": other.title, "score": n["score"]})
    contrast = None
    if out and out[0]["score"] >= CONTRAST_FLOOR and get_llm().status()["available"]:
        contrast = {"with_id": out[0]["id"], "with_title": out[0]["title"]}
    return {"related": out, "contrast": contrast, "embeddings": True}


class ContrastReq(BaseModel):
    with_id: int


@router.post("/learnings/{learning_id}/contrast")
def add_contrast(learning_id: int, body: ContrastReq):
    """Generate + attach a discrimination card for two confusable topics."""
    repo = Repository()
    a, b = repo.get_learning(learning_id), repo.get_learning(body.with_id)
    if not a or not b:
        return JSONResponse({"error": "not_found"}, status_code=404)
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    try:
        card = llm.contrast_card({"title": a.title, "content": a.content},
                                 {"title": b.title, "content": b.content})
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    repo.create_question(learning_id, card["question"], card["answer"])
    return {"added": 1, "question": card["question"]}


class DupeCheckReq(BaseModel):
    titles: list[str]


@router.post("/topics/check_dupes")
def check_dupes(body: DupeCheckReq):
    """Flag titles that are nearly identical to existing topics (before bulk add)."""
    emb = get_embeddings()
    titles = [t.strip() for t in body.titles if t.strip()][:60]
    if not titles or not emb.model_available():
        return {"dupes": []}
    repo = Repository()
    vectors = emb.embed_texts(titles)
    if not vectors:
        return {"dupes": []}
    emb.backfill(24)
    existing = emb.all_vectors()
    dupes = []
    from app.services.embeddings import cosine
    for title, vec in zip(titles, vectors):
        best_id, best = None, 0.0
        for lid, v in existing:
            s = cosine(vec, v)
            if s > best:
                best_id, best = lid, s
        if best_id is not None and best >= 0.88:
            match = repo.get_learning(best_id)
            if match:
                dupes.append({"title": title, "match_id": best_id,
                              "match_title": match.title, "score": round(best, 2)})
    return {"dupes": dupes}


@router.post("/learnings/{learning_id}/generate")
def generate_more(learning_id: int):
    """Generate a few more recall questions for an existing topic (on demand)."""
    repo = Repository()
    llm = get_llm()
    learning = repo.get_learning(learning_id)
    if not learning:
        return JSONResponse({"error": "not_found"}, status_code=404)
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    transcript = f"Topic: {learning.title}\n\n{learning.content or ''}\n\n{learning.reflection or ''}".strip()
    try:
        cards = llm.generate_cards(transcript, n=3, basic_only=True)
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    added = 0
    for c in cards:
        if c.get("type") == "basic" and c.get("question") and c.get("answer"):
            repo.create_question(learning_id, c["question"], c["answer"], card_type="basic")
            added += 1
    return {"added": added}


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


class RefineReq(BaseModel):
    feedback: str = ""
    use_cloud: bool = False   # explicit per-click opt-in


@router.post("/cards/{card_id}/refine")
def refine_card(card_id: int, body: RefineReq):
    """Rewrite a card from the learner's feedback. Local model by default;
    Claude only when the user explicitly clicked the cloud action."""
    repo = Repository()
    q = repo.get_question(card_id)
    if not q:
        return JSONResponse({"error": "not_found"}, status_code=404)
    learning = repo.get_learning(q.learning_id)
    topic = learning.title if learning else ""
    content = learning.content if learning else ""
    style = get_llm().gen_style

    if body.use_cloud:
        try:
            card = get_cloud().refine_card(topic, content, q.question, q.answer,
                                           body.feedback, style)
        except CloudError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        return {**card, "source": "cloud"}

    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    try:
        card = llm.refine_card(topic, content, q.question, q.answer, body.feedback)
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {**card, "source": "local"}


class BuryReq(BaseModel):
    days: int = 1


@router.post("/cards/{card_id}/bury")
def bury_card(card_id: int, body: BuryReq):
    """Push a card out N days without rating it ('not today')."""
    repo = Repository()
    q = repo.get_question(card_id)
    if not q:
        return JSONResponse({"error": "not_found"}, status_code=404)
    days = max(1, min(30, body.days))
    target = (datetime.now() + timedelta(days=days)).replace(hour=4, minute=0, second=0, microsecond=0)
    repo.set_card_due(card_id, target)
    return {"ok": True, "next_review_at": target.isoformat()}


class SuspendReq(BaseModel):
    suspended: bool


@router.post("/cards/{card_id}/suspend")
def suspend_card(card_id: int, body: SuspendReq):
    Repository().set_suspended(card_id, body.suspended)
    return {"ok": True}


# ---------- focus (priority topics) ----------

class PriorityReq(BaseModel):
    priority: int = 1


@router.post("/learnings/{learning_id}/priority")
def set_learning_priority(learning_id: int, body: PriorityReq):
    Repository().set_priority(learning_id, body.priority)
    return {"ok": True}


class FocusInterpretReq(BaseModel):
    text: str


@router.post("/focus/interpret")
def interpret_focus(body: FocusInterpretReq):
    """Map 'I want to prioritize my vibrations final + battery stuff' onto actual
    subjects and topics. Uses the local model when up, substring matching otherwise."""
    repo = Repository()
    llm = get_llm()
    topics = [{"id": r["id"], "title": r["title"]}
              for r in repo.db.fetch_all(
                  "SELECT id, title FROM learnings WHERE is_active = 1 "
                  "ORDER BY created_at DESC LIMIT 500")]
    titles = {t["id"]: t["title"] for t in topics}

    matched = None
    if llm.status()["available"]:
        try:
            plan = llm.interpret_focus(body.text, repo.subject_names(), topics)
            matched = {
                "subjects": plan["subjects"],
                "learnings": [{"id": i, "title": titles[i]} for i in plan["learning_ids"]],
            }
        except OllamaError:
            matched = None
    if matched is None or (not matched["subjects"] and not matched["learnings"]):
        matched = repo.match_focus_text(body.text)
    return matched


class FocusApplyReq(BaseModel):
    subjects: list[str] = []
    learning_ids: list[int] = []
    priority: int = 1


@router.post("/focus/apply")
def apply_focus(body: FocusApplyReq):
    repo = Repository()
    for s in body.subjects:
        if s.strip():
            repo.set_subject_priority(s.strip(), body.priority)
    for lid in body.learning_ids:
        repo.set_priority(lid, body.priority)
    return {"ok": True, "focus": repo.focus_summary()}


@router.post("/focus/clear")
def clear_focus():
    cleared = Repository().clear_focus()
    return {"cleared": cleared}


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


# ---------- bulk add topics ----------

class BulkItem(BaseModel):
    title: str
    note: str = ""


class BulkReq(BaseModel):
    items: list[BulkItem]
    subject: Optional[str] = None
    tags: list[str] = []
    per_day: int = 8   # ease-in: how many become due each day


@router.post("/topics/bulk")
def bulk_topics(body: BulkReq):
    """Create many topics fast. Each gets a free-recall card; due dates are staggered
    so a big backlog eases into review over days instead of all at once."""
    repo = Repository()
    per_day = max(1, min(100, body.per_day))
    now = datetime.now()
    created = 0
    for i, it in enumerate(t for t in body.items if t.title.strip()):
        title = it.title.strip()
        lid = repo.create_learning(title, it.note.strip(), subject=body.subject, tags=body.tags)
        cid = repo.create_recall_card(lid, title, it.note.strip())
        offset = i // per_day
        if offset > 0:
            repo.set_card_due(cid, now + timedelta(days=offset))
        created += 1
    return {"created": created}


class SplitReq(BaseModel):
    text: str


@router.post("/topics/split")
def split_topics(body: SplitReq):
    """Use the local model to extract a list of topics from pasted text (for approval)."""
    llm = get_llm()
    if not llm.status()["available"]:
        return JSONResponse({"error": "no_local_model"}, status_code=503)
    try:
        topics = llm.split_topics(body.text)
    except OllamaError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    return {"topics": topics}
