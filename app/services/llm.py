"""Local LLM access via Ollama.

Everything here is local-only. Cloud model tags are refused so notes never leave
the device. Each feature degrades gracefully: if the model is unreachable, callers
fall back (manual cards / self-grading).
"""

import json
import re
from typing import Iterator, Optional

import httpx
from pydantic import BaseModel, Field

from app.config import (
    CLOUD_MODEL_MARKERS, DEFAULT_MODEL, OLLAMA_BASE_URL, OLLAMA_CONNECT_TIMEOUT,
    OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT,
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class OllamaError(Exception):
    pass


def is_cloud_model(name: str) -> bool:
    n = (name or "").lower()
    return any(marker in n for marker in CLOUD_MODEL_MARKERS)


def strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


class _ThinkFilter:
    """Streaming filter that drops <think>...</think> spans across chunk boundaries."""

    def __init__(self):
        self._buf = ""
        self._in_think = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out = []
        while self._buf:
            if not self._in_think:
                i = self._buf.find("<think>")
                if i == -1:
                    # hold back a small tail that might be a partial "<think>"
                    keep = min(len(self._buf), len("<think>") - 1)
                    out.append(self._buf[:-keep] if keep else self._buf)
                    self._buf = self._buf[-keep:] if keep else ""
                    break
                out.append(self._buf[:i])
                self._buf = self._buf[i + len("<think>"):]
                self._in_think = True
            else:
                j = self._buf.find("</think>")
                if j == -1:
                    keep = min(len(self._buf), len("</think>") - 1)
                    self._buf = self._buf[-keep:] if keep else ""
                    break
                self._buf = self._buf[j + len("</think>"):]
                self._in_think = False
        return "".join(out)

    def flush(self) -> str:
        rest = "" if self._in_think else self._buf
        self._buf = ""
        return rest


# ---------- structured output schemas ----------

class GenCard(BaseModel):
    type: str = Field(default="basic", description="'basic' or 'cloze'")
    question: str = Field(default="", description="basic card question")
    answer: str = Field(default="", description="basic card answer")
    source: str = Field(default="", description="cloze sentence with {{c1::term}} markers")


class CardSet(BaseModel):
    cards: list[GenCard] = Field(default_factory=list)


class Grade(BaseModel):
    verdict: str = Field(description="one of: correct, partial, wrong")
    missing: str = Field(default="", description="key idea the learner omitted, else empty")
    poke: str = Field(default="", description="one short Socratic question; never reveal the answer")


class SubjectGuess(BaseModel):
    subject: str = Field(default="", description="one concise subject area, Title Case, 1-3 words")


class SubjectAssign(BaseModel):
    id: int = Field(description="the note id")
    subject: str = Field(default="", description="subject area for this note, Title Case")


class SubjectAssigns(BaseModel):
    items: list[SubjectAssign] = Field(default_factory=list)


# ---------- prompts ----------

_CAPTURE_SYSTEM = """You are a sharp, warm study partner helping someone lock in something they just learned.
They will tell you what they learned. Your job is to make THEM think harder, because
generating their own explanations is what makes knowledge stick.

Ask exactly ONE short follow-up question per turn. Pick the highest-leverage angle:
- why is that true / what's the mechanism (elaborative interrogation)
- how does it connect to something they already know (self-explanation)
- a concrete example or where they'd apply it (transfer)
- how it differs from a related idea (discrimination)
- the one-sentence gist
Keep it to a single sentence. Be specific to what they wrote. Never lecture, never
answer for them, never praise emptily. If the material is a plain fact with nothing to
elaborate, ask for the gist or an example instead."""

_CARDS_SYSTEM = """You turn a short study conversation into spaced-repetition cards that test ACTIVE RECALL.

Produce a focused set (aim for the number requested) mixing two types:
- "basic": a {question, answer} testing one core idea, distinction, or application.
- "cloze": a {source} that is ONE standalone sentence with {{c1::term}} markers
  (1-2 markers, substantive terms only).

Rules: test the most important ideas, not trivia. Prefer the learner's own words and
examples. Answers concise and unambiguous. Vary the cognitive angle (recall,
application, contrast). NEVER copy the conversation, speaker labels, or multiple lines
into a cloze source — it must be a single clean sentence. Output only the structured object."""

_GRADE_SYSTEM = """You grade a learner's free-recall answer against a reference answer, then nudge them.

Grade ONLY against the reference. Reward correct meaning even if the wording differs or
it's terse. If the core idea is present, mark "correct". If partially right or missing a
key piece, "partial". If absent/wrong, "wrong". Do NOT invent requirements beyond the
reference, and do not be harsh about phrasing.

Then ALWAYS write ONE short Socratic "poke" (never leave it empty): a single question
that pushes them toward the gap they missed, or — if they nailed it — one level deeper
(a "why", an edge case, or an application). Never reveal the answer. Keep it to one sentence."""


_SUBJECT_SYSTEM = """You file study notes into broad subject areas (e.g. "Machine Learning",
"Spanish", "Microeconomics", "Anatomy", "Personal Finance").

Return concise areas in Title Case, 1–3 words. STRONGLY prefer reusing an existing
subject when one reasonably fits; invent a new area only when none do, and reuse the
SAME new area across related notes. Never return an empty subject."""


class LLMService:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.preferred = model
        self._resolved: Optional[str] = None

    # ---------- model discovery (local only) ----------

    def local_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=OLLAMA_CONNECT_TIMEOUT) as client:
                resp = client.get(f"{OLLAMA_BASE_URL}/api/tags")
                resp.raise_for_status()
                names = [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return []
        return [n for n in names if not is_cloud_model(n)]

    def resolve_model(self) -> Optional[str]:
        models = self.local_models()
        if not models:
            self._resolved = None
            return None
        if self.preferred in models:
            self._resolved = self.preferred
        else:
            base = self.preferred.split(":")[0]
            match = next((m for m in models if m.split(":")[0] == base), None)
            self._resolved = match or models[0]
        return self._resolved

    def status(self) -> dict:
        all_local = self.local_models()
        model = self.resolve_model()
        return {
            "available": model is not None,
            "model": model,
            "models": all_local,
            "reason": None if model else "No local Ollama model found. Run: ollama pull qwen2.5:7b",
        }

    def set_model(self, name: str) -> None:
        if is_cloud_model(name):
            raise OllamaError("Cloud models are blocked to keep your data on-device.")
        self.preferred = name
        self._resolved = None

    def warm(self) -> None:
        """Best-effort: load the model so the first real call isn't a cold start."""
        model = self.resolve_model()
        if not model:
            return
        try:
            with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
                client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={"model": model, "prompt": "ok", "stream": False,
                          "keep_alive": OLLAMA_KEEP_ALIVE, "options": {"num_predict": 1}},
                )
        except Exception:
            pass

    # ---------- primitives ----------

    def _chat_stream(self, messages: list[dict], temperature: float = 0.5) -> Iterator[str]:
        model = self.resolve_model()
        if not model:
            raise OllamaError("No local model available.")
        payload = {
            "model": model, "messages": messages, "stream": True,
            "keep_alive": OLLAMA_KEEP_ALIVE, "options": {"temperature": temperature},
        }
        filt = _ThinkFilter()
        try:
            with httpx.Client(timeout=httpx.Timeout(OLLAMA_TIMEOUT, connect=OLLAMA_CONNECT_TIMEOUT)) as client:
                with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        piece = (obj.get("message") or {}).get("content", "")
                        if piece:
                            emit = filt.feed(piece)
                            if emit:
                                yield emit
                        if obj.get("done"):
                            break
            tail = filt.flush()
            if tail:
                yield tail
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama request failed: {e}")

    def _complete_json(
        self, messages: list[dict], schema: type[BaseModel], temperature: float = 0.3
    ) -> BaseModel:
        model = self.resolve_model()
        if not model:
            raise OllamaError("No local model available.")
        payload = {
            "model": model, "messages": messages, "stream": False,
            "format": schema.model_json_schema(),
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": temperature},
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(OLLAMA_TIMEOUT, connect=OLLAMA_CONNECT_TIMEOUT)) as client:
                resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                resp.raise_for_status()
                content = strip_think((resp.json().get("message") or {}).get("content", ""))
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama request failed: {e}")
        if not content:
            raise OllamaError("Empty response from model.")
        try:
            return schema.model_validate_json(content)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return schema.model_validate_json(match.group())
                except Exception:
                    pass
            raise OllamaError("Could not parse structured output.")

    # ---------- high-level features ----------

    def capture_followup_stream(self, history: list[dict]) -> Iterator[str]:
        messages = [{"role": "system", "content": _CAPTURE_SYSTEM}, *history]
        yield from self._chat_stream(messages, temperature=0.6)

    def generate_cards(self, transcript: str, n: int = 4) -> list[dict]:
        messages = [
            {"role": "system", "content": _CARDS_SYSTEM},
            {"role": "user", "content": f"Aim for about {n} cards.\n\nConversation:\n---\n{transcript}\n---"},
        ]
        result = self._complete_json(messages, CardSet, temperature=0.4)
        out: list[dict] = []
        for c in result.cards:
            ctype = (c.type or "basic").strip().lower()
            if ctype == "cloze" and c.source.strip():
                # a cloze is one sentence — drop any leaked transcript / extra lines
                src = c.source.strip().split("\n")[0].strip()
                if "{{c" in src:
                    out.append({"type": "cloze", "source": src})
            elif c.question.strip() and c.answer.strip():
                out.append({"type": "basic", "question": c.question.strip(), "answer": c.answer.strip()})
        if not out:
            raise OllamaError("Model returned no usable cards.")
        return out

    def grade_recall(self, question: str, reference: str, user_answer: str) -> dict:
        prompt = (
            f"Question:\n{question}\n\nReference answer:\n{reference}\n\n"
            f"Learner's recall:\n{user_answer or '(left blank)'}"
        )
        messages = [
            {"role": "system", "content": _GRADE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        grade = self._complete_json(messages, Grade, temperature=0.1)
        verdict = grade.verdict.strip().lower()
        if verdict not in ("correct", "partial", "wrong"):
            verdict = "partial"
        return {"verdict": verdict, "missing": grade.missing.strip(), "poke": grade.poke.strip()}

    def suggest_subject(self, text: str, existing: list[str]) -> str:
        ex = ", ".join(existing) if existing else "(none yet)"
        messages = [
            {"role": "system", "content": _SUBJECT_SYSTEM},
            {"role": "user", "content": f"Existing subjects: {ex}\n\nNote:\n{text[:1500]}\n\nReturn the single best subject area."},
        ]
        return self._complete_json(messages, SubjectGuess, temperature=0.2).subject.strip()

    def suggest_subjects(self, items: list[dict], existing: list[str]) -> list[dict]:
        ex = ", ".join(existing) if existing else "(none yet)"
        listing = "\n".join(f"- [{it['id']}] {it['title']}" for it in items)
        messages = [
            {"role": "system", "content": _SUBJECT_SYSTEM},
            {"role": "user", "content": f"Existing subjects: {ex}\n\nAssign each note a subject area "
                f"(reuse existing where sensible; use the SAME area for related notes):\n{listing}"},
        ]
        result = self._complete_json(messages, SubjectAssigns, temperature=0.2)
        valid = {it["id"] for it in items}
        return [{"id": a.id, "subject": a.subject.strip()}
                for a in result.items if a.id in valid and a.subject.strip()]


_service: Optional[LLMService] = None


def get_llm() -> LLMService:
    global _service
    if _service is None:
        _service = LLMService()
    return _service
