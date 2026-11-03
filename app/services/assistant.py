"""Ask R&R: a scoped local helper over the learner's own study data.

The local model (Ollama tool calling, never cloud) may READ freely through three
tools. Everything else it calls is turned into a *proposal*: navigate actions
the frontend follows on click, and write actions that change nothing until the
learner clicks Confirm, which re-validates the args (confirm()) and executes.

Every argument is validated server-side, and button labels are built from the
validated args plus database values, never from the model's text.
"""

import json
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.api import learnings as learnings_api
from app.api.stats import _consistency, _streak
from app.config import OLLAMA_BASE_URL, OLLAMA_CONNECT_TIMEOUT, OLLAMA_KEEP_ALIVE, OLLAMA_NUM_CTX, OLLAMA_TIMEOUT
from app.db.repository import Repository
from app.services.llm import (
    ASSISTANT_SYSTEM, LLMService, OllamaError, clip_middle, fit_history, get_llm, strip_think,
)

MAX_ROUNDS = 3            # model calls per /ask
MAX_CALLS_PER_ROUND = 6   # tool calls honoured from one model message
MAX_ACTIONS = 4
MAX_MESSAGE = 1000
HISTORY_TURNS = 6
_HISTORY_BUDGET = OLLAMA_NUM_CTX   # chars (~1/4 of the window): tools + tool results need the rest

READ_TOOLS = ("search_topics", "get_topic", "get_stats")
NAV_TOOLS = ("start_review", "open_topic")
WRITE_TOOLS = ("set_focus", "clear_focus", "create_topic", "add_card")

UNAVAILABLE_REPLY = ("Start Ollama to use Ask: run `ollama serve`, then `ollama pull qwen3.5:9b`. "
                     "Ask only ever uses the local model.")


class InvalidArgs(ValueError):
    pass


def _fn(name: str, description: str, props: dict, required: Optional[list] = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required or []}}}


_INT = {"type": "integer"}
_STR = {"type": "string"}

TOOLS = [
    _fn("search_topics", "Find the learner's topics by words or meaning. Returns id, title, subject, due_count.",
        {"query": _STR}, ["query"]),
    _fn("get_topic", "One topic's details: subject, key ideas, card and due counts.",
        {"learning_id": _INT}, ["learning_id"]),
    _fn("get_stats", "Progress: due, today's reviews vs target, streak, retention, focus, at-risk topics.", {}),
    _fn("start_review", "Propose a review session. limit=3 is 'Just 3'; evening=true is the wind-down session.",
        {"limit": _INT, "focus": {"type": "boolean"}, "subject": _STR, "evening": {"type": "boolean"}}),
    _fn("open_topic", "Propose opening a topic in the Library.", {"learning_id": _INT}, ["learning_id"]),
    _fn("set_focus", "Propose prioritizing existing subjects and/or topic ids in reviews.",
        {"subjects": {"type": "array", "items": _STR}, "learning_ids": {"type": "array", "items": _INT}}),
    _fn("clear_focus", "Propose clearing all focus.", {}),
    _fn("create_topic", "Propose saving a new topic from text the learner gave.",
        {"title": _STR, "content": _STR, "subject": _STR}, ["title", "content"]),
    _fn("add_card", "Propose adding a question/answer card to an existing topic.",
        {"learning_id": _INT, "question": _STR, "answer": _STR}, ["learning_id", "question", "answer"]),
]


# ---------- argument hygiene ----------

def parse_arguments(raw: Any) -> dict:
    """Ollama sends a dict; some models send a JSON string. Anything else is {}."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _text(v: Any, cap: int) -> str:
    if v is None or isinstance(v, (dict, list)):
        return ""
    return str(v).strip()[:cap]


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _list(v: Any) -> list:
    if isinstance(v, list):
        return v
    if v in (None, ""):
        return []
    return [v]


def _short(title: str, cap: int = 40) -> str:
    title = (title or "").strip()
    return title if len(title) <= cap else title[: cap - 1].rstrip() + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class Assistant:
    def __init__(self, repo: Optional[Repository] = None, llm: Optional[LLMService] = None):
        self.repo = repo or Repository()
        self.llm = llm or get_llm()

    # ---------- validation shared by /ask (proposals) and /confirm ----------

    def _active(self, learning_id: Any):
        lid = _int(learning_id)
        learning = self.repo.get_learning(lid) if lid is not None else None
        if not learning or not learning.is_active:
            raise InvalidArgs(f"No topic with id {learning_id}.")
        return learning

    def _subject(self, name: Any) -> Optional[str]:
        """Canonical existing subject name (case-insensitive), else None."""
        want = _text(name, 80).lower()
        if not want:
            return None
        return next((s for s in self.repo.subject_names() if s.strip().lower() == want), None)

    def validate(self, tool: str, args: dict) -> tuple[dict, str, Optional[str]]:
        """-> (clean args, label, href). Raises InvalidArgs."""
        if tool == "start_review":
            evening = _bool(args.get("evening"))
            limit = _int(args.get("limit"))
            limit = max(1, min(200, limit)) if limit is not None else None
            clean: dict = {}
            if evening:
                clean["evening"] = True
                if limit:
                    clean["limit"] = min(limit, 10)   # the evening queue caps at 10
                qs = "mode=evening" + (f"&limit={clean['limit']}" if limit else "")
                label = "Evening wind-down" + (f" ({_plural(clean['limit'], 'card')})" if limit else "")
                return clean, label, f"#/recall?{qs}"
            subject = self._subject(args.get("subject"))
            focus = _bool(args.get("focus"))
            parts = []
            if subject:
                clean["subject"] = subject
                parts.append("subject=" + quote(subject, safe=""))
            if focus:
                clean["focus"] = True
                parts.append("focus=1")
            if limit:
                clean["limit"] = limit
                parts.append(f"limit={limit}")
            quals = (["focus only"] if focus else []) + ([_plural(limit, "card")] if limit else [])
            if subject:
                label = f"Review {_short(subject)}" + (f" ({', '.join(quals)})" if quals else "")
            elif focus:
                label = "Review focus" + (f" ({_plural(limit, 'card')})" if limit else "")
            elif limit == 3:
                label = "Just 3"
            elif limit:
                label = f"Review {_plural(limit, 'card')}"
            else:
                label = "Start review"
            return clean, label, "#/recall" + ("?" + "&".join(parts) if parts else "")

        if tool == "open_topic":
            learning = self._active(args.get("learning_id"))
            return {"learning_id": learning.id}, f"Open {_short(learning.title)}", f"#/library/{learning.id}"

        if tool == "set_focus":
            subjects: list[str] = []
            for s in _list(args.get("subjects"))[:10]:
                canon = self._subject(s)
                if canon and canon not in subjects:
                    subjects.append(canon)
            topics = []
            for v in _list(args.get("learning_ids"))[:25]:
                try:
                    learning = self._active(v)
                except InvalidArgs:
                    continue
                if learning.id not in {t.id for t in topics}:
                    topics.append(learning)
            if not subjects and not topics:
                raise InvalidArgs("Nothing to focus: no matching subjects or topics.")
            per_subject = {s["name"].lower(): s["learnings"] for s in self.repo.subjects_summary()}
            chosen = {s.lower() for s in subjects}
            n = sum(per_subject.get(s, 0) for s in chosen)
            n += sum(1 for t in topics if (t.subject or "").strip().lower() not in chosen)
            names = [_short(s, 30) for s in subjects] + [_short(t.title, 30) for t in topics[:2]]
            if len(topics) > 2:
                names.append(f"+{len(topics) - 2} more")
            label = f"Focus {', '.join(names)} ({_plural(n, 'topic')})"
            return {"subjects": subjects, "learning_ids": [t.id for t in topics]}, label, None

        if tool == "clear_focus":
            n = self.repo.focus_summary()["topics"]
            return {}, f"Clear focus ({_plural(n, 'topic')})" if n else "Clear focus", None

        if tool == "create_topic":
            title = _text(args.get("title"), 120)
            content = _text(args.get("content"), 8000)
            if not title:
                raise InvalidArgs("A new topic needs a title.")
            clean = {"title": title, "content": content}
            subject = self._subject(args.get("subject"))
            if subject:
                clean["subject"] = subject
            label = f"Create topic “{_short(title)}”" + (f" in {_short(subject, 30)}" if subject else "")
            return clean, label, None

        if tool == "add_card":
            learning = self._active(args.get("learning_id"))
            question = _text(args.get("question"), 1000)
            answer = _text(args.get("answer"), 4000)
            if not question or not answer:
                raise InvalidArgs("A card needs both a question and an answer.")
            label = f"Add card to {_short(learning.title, 30)}: “{_short(question, 50)}”"
            return {"learning_id": learning.id, "question": question, "answer": answer}, label, None

        raise InvalidArgs(f"Unknown tool: {tool}")

    # ---------- read tools (executed during /ask) ----------

    def search_topics(self, args: dict) -> dict:
        query = _text(args.get("query"), 200)
        # Same literal + semantic search as the Library (GET /api/learnings).
        items = learnings_api.list_learnings(search=query)["learnings"][:8]
        return {"topics": [{"id": it["id"], "title": it["title"], "subject": it["subject"],
                            "due_count": it["due_count"]} for it in items]}

    def get_topic(self, args: dict) -> dict:
        learning = self._active(args.get("learning_id"))
        cards = self.repo.get_questions_for_learning(learning.id)
        now = datetime.now()
        due = sum(1 for c in cards if not c.suspended
                  and (c.next_review_at is None or c.next_review_at <= now))
        return {
            "id": learning.id, "title": learning.title, "subject": learning.subject or "",
            "key_ideas": [i["idea"] for i in self.repo.get_key_ideas(learning.id)][:8],
            "content": clip_middle(learning.content or "", 600),
            "cards": len(cards), "due": due, "private": learning.private,
        }

    def get_stats(self, args: dict) -> dict:
        repo = self.repo
        activity = repo.activity_by_day(365)
        retention = repo.retention_rate(30)
        hot = repo.calibration(90).get("overconfident_subject")
        out = {
            "due": repo.get_due_count(),
            "reviews_today": repo.reviews_today(),
            "daily_target": repo.get_daily_target(),
            "streak": _streak(activity),
            "consistency": _consistency(activity),
            "retention_30": round(retention * 100, 1) if retention is not None else None,
            "focus": repo.focus_summary(),
            "at_risk": [a["label"][:80] for a in repo.at_risk_cards(3)],
        }
        if hot:
            out["most_overconfident_subject"] = {"subject": hot["subject"],
                                                 "accuracy_when_confident": hot["accuracy"]}
        return out

    # ---------- the loop ----------

    def _chat(self, model: str, messages: list[dict]) -> dict:
        try:
            return self._chat_once(model, messages, think=False)
        except OllamaError as e:
            if "think" in str(e).lower():   # older Ollama / non-reasoning model
                return self._chat_once(model, messages, think=None)
            raise

    def _chat_once(self, model: str, messages: list[dict], think: Optional[bool]) -> dict:
        payload = {
            "model": model, "messages": messages, "tools": TOOLS, "stream": False,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0.2, "num_ctx": OLLAMA_NUM_CTX, "num_predict": 600},
        }
        if think is not None:
            payload["think"] = think
        try:
            with httpx.Client(timeout=httpx.Timeout(OLLAMA_TIMEOUT, connect=OLLAMA_CONNECT_TIMEOUT)) as client:
                resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                if resp.status_code != 200:
                    raise OllamaError(f"Ollama request failed: {LLMService._http_detail(resp)}")
                body = resp.json() or {}
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama request failed: {e}")
        msg = body.get("message")
        return msg if isinstance(msg, dict) else {}

    def _run_tool(self, name: str, args: dict, actions: list[dict]) -> dict:
        if name in READ_TOOLS:
            try:
                return getattr(self, name)(args)
            except InvalidArgs as e:
                return {"error": str(e)}
        if name in NAV_TOOLS or name in WRITE_TOOLS:
            try:
                clean, label, href = self.validate(name, args)
            except InvalidArgs as e:
                return {"error": str(e)}
            key = (name, json.dumps(clean, sort_keys=True))
            existing = next((a for a in actions if (a["tool"], json.dumps(a["args"], sort_keys=True)) == key), None)
            if existing is None:
                if len(actions) >= MAX_ACTIONS:
                    return {"error": "Too many proposals already; do not propose more."}
                actions.append({"id": f"a{len(actions) + 1}",
                                "kind": "navigate" if name in NAV_TOOLS else "write",
                                "tool": name, "args": clean, "label": label,
                                "href": href if name in NAV_TOOLS else None})
            if name in NAV_TOOLS:
                return {"status": "offered to the user as a button; not opened yet", "label": label}
            return {"status": "proposed to the user for confirmation; nothing has changed yet",
                    "label": label}
        return {"error": f"Unknown tool {name!r}; ignored."}

    def ask(self, message: str, history: Optional[list] = None) -> dict:
        message = (message or "").strip()[:MAX_MESSAGE]
        if not message:
            return {"reply": "Ask me about your topics, reviews or progress.", "actions": [], "available": True}
        model = self.llm.resolve_model()
        if not model:
            return {"reply": UNAVAILABLE_REPLY, "actions": [], "available": False}

        turns = []
        for h in (history or [])[-HISTORY_TURNS:]:
            if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
                content = _text(h.get("content"), 2000)
                if content:
                    turns.append({"role": h["role"], "content": content})
        messages = [{"role": "system", "content": ASSISTANT_SYSTEM},
                    *fit_history(turns, _HISTORY_BUDGET),
                    {"role": "user", "content": message}]

        actions: list[dict] = []
        reply = ""
        try:
            for _ in range(MAX_ROUNDS):
                msg = self._chat(model, messages)
                content = strip_think(msg.get("content") or "")
                calls = msg.get("tool_calls") or []
                if not isinstance(calls, list) or not calls:
                    reply = content
                    break
                messages.append({"role": "assistant", "content": msg.get("content") or "",
                                 "tool_calls": calls})
                for call in calls[:MAX_CALLS_PER_ROUND]:
                    fn = call.get("function") if isinstance(call, dict) else None
                    fn = fn if isinstance(fn, dict) else {}
                    name = str(fn.get("name") or "").strip()
                    result = self._run_tool(name, parse_arguments(fn.get("arguments")), actions)
                    messages.append({"role": "tool", "tool_name": name,
                                     "content": json.dumps(result, ensure_ascii=False, default=str)})
                reply = content   # keep any text that came alongside the calls
        except OllamaError as e:
            reason = str(e)
            if "does not support tools" in reason.lower():
                reply = (f"The local model {model} does not support tool calling, which Ask needs. "
                         "Choose a tool-capable model such as qwen3.5:9b in Settings.")
            else:
                reply = f"The local model could not answer: {reason}"
            return {"reply": reply, "actions": actions, "available": True}

        if not reply:
            reply = ("Here is what I can do; confirm below." if actions
                     else "I couldn't work that out. Try asking more specifically.")
        return {"reply": reply[:2000], "actions": actions, "available": True}

    # ---------- /confirm ----------

    def confirm(self, tool: str, args: Any) -> dict:
        """Execute a write proposal after re-validating it. Raises InvalidArgs."""
        if tool not in WRITE_TOOLS:
            raise InvalidArgs(f"Unknown tool: {tool}")
        if not isinstance(args, dict):
            raise InvalidArgs("args must be an object")
        clean, label, _ = self.validate(tool, args)
        repo = self.repo

        if tool == "set_focus":   # same as POST /api/focus/apply priority=1
            for s in clean["subjects"]:
                repo.set_subject_priority(s, 1)
            for lid in clean["learning_ids"]:
                repo.set_priority(lid, 1)
            f = repo.focus_summary()
            return {"ok": True, "href": None,
                    "message": f"Focus set: {_plural(f['topics'], 'topic')}, {f['due']} due."}

        if tool == "clear_focus":   # same as POST /api/focus/clear
            n = repo.clear_focus()
            return {"ok": True, "href": None, "message": f"Focus cleared ({_plural(n, 'topic')})."}

        if tool == "create_topic":   # same path as a Reflect save (POST /api/learnings)
            ideas: list[str] = []
            if clean["content"] and self.llm.resolve_model():
                try:
                    ideas = self.llm.extract_key_ideas(f"Topic: {clean['title']}\n\n{clean['content']}")
                except OllamaError:
                    ideas = []   # best-effort: the topic still saves
            res = learnings_api.create_learning(learnings_api.LearningIn(
                title=clean["title"], content=clean["content"], subject=clean.get("subject"),
                key_ideas=ideas, recall_card=True))
            extra = f" with {_plural(len(ideas), 'key idea')}" if ideas else ""
            return {"ok": True, "href": f"#/library/{res['id']}",
                    "message": f"Saved “{_short(res['title'])}”{extra} and a recall card."}

        if tool == "add_card":   # same as POST /api/learnings/{id}/cards (basic)
            lid = clean["learning_id"]
            learnings_api.add_card(lid, learnings_api.CardIn(
                type="basic", question=clean["question"], answer=clean["answer"]))
            title = repo.get_learning(lid).title
            return {"ok": True, "href": f"#/library/{lid}", "message": f"Card added to {_short(title)}."}

        raise InvalidArgs(f"Unknown tool: {tool}")   # pragma: no cover
