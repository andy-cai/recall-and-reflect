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
    CLOUD_MODEL_MARKERS, DEFAULT_GEN_STYLE, DEFAULT_MODEL, OLLAMA_BASE_URL,
    OLLAMA_CONNECT_TIMEOUT, OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT,
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


class KeyIdeaList(BaseModel):
    ideas: list[str] = Field(default_factory=list, description="3-8 one-line key ideas")


class IdeaResult(BaseModel):
    index: int = Field(description="0-based index of the key idea")
    result: str = Field(description="one of: hit, partial, miss")


class RubricGrade(BaseModel):
    items: list[IdeaResult] = Field(default_factory=list)
    poke: str = Field(default="", description="one short Socratic question; never reveal the answer")


class SubjectGuess(BaseModel):
    subject: str = Field(default="", description="one concise subject area, Title Case, 1-3 words")


class SubjectAssign(BaseModel):
    id: int = Field(description="the note id")
    subject: str = Field(default="", description="subject area for this note, Title Case")


class SubjectAssigns(BaseModel):
    items: list[SubjectAssign] = Field(default_factory=list)


class TopicItem(BaseModel):
    title: str = Field(default="", description="short topic title (a concept worth remembering)")
    note: str = Field(default="", description="optional one-line note from the text, else empty")


class TopicList(BaseModel):
    topics: list[TopicItem] = Field(default_factory=list)


class PrettyText(BaseModel):
    text: str = Field(default="", description="the same text with math typeset as $...$ TeX")


class FocusPlan(BaseModel):
    subjects: list[str] = Field(default_factory=list, description="existing subject names the user wants to prioritize")
    learning_ids: list[int] = Field(default_factory=list, description="ids of specific topics the user wants to prioritize")


# ---------- prompts ----------

_CAPTURE_SYSTEM = """You are a sharp, warm study partner helping someone lock in something they just learned.
They will tell you what they learned. Your job is to make THEM think harder, because
generating their own explanations is what makes knowledge stick.

Ask exactly ONE short follow-up question per turn. Pick the highest-leverage angle:
- why is that true / what's the mechanism (elaborative interrogation)
- how does it connect to something they already know (self-explanation)
- a concrete example or where they'd apply it (transfer)
- how it differs from a related idea (discrimination)
- where it breaks down (boundary conditions)

The bar, by example. If they wrote "finer grains make metals stronger, sigma_y = sigma_0 + k/sqrt(d)":
  Banned (generic): "Can you elaborate on that?" / "Why is that important?"
  Good: "What is the boundary physically doing to a dislocation that makes more of them mean stronger?"
  Good: "Strengthening usually costs ductility. Does Hall-Petch? Why or why not?"

Keep it to one or two sentences, specific to what they actually wrote. Never lecture,
never answer for them, never praise emptily. If the material is a plain fact with
nothing to elaborate, ask for a concrete example or the one-sentence gist instead."""

_CARDS_SYSTEM = """You turn a short study conversation into spaced-repetition cards that test ACTIVE RECALL.

Produce a focused set (aim for the number requested) mixing two types:
- "basic": a {question, answer} testing one core idea, distinction, or application.
- "cloze": a {source} that is ONE standalone sentence with {{c1::term}} markers
  (1-2 markers, substantive terms only).

Rules: test the most important ideas, not trivia. Prefer the learner's own words and
examples. Answers concise and unambiguous. Vary the cognitive angle (recall,
application, contrast). NEVER copy the conversation, speaker labels, or multiple lines
into a cloze source — it must be a single clean sentence. Output only the structured object."""

_CARDS_BASIC_SYSTEM = """You turn a short study conversation into a few open questions that test ACTIVE RECALL.

Produce ONLY "basic" question/answer pairs (never fill-in-the-blank / cloze). Every
question must earn its place: one load-bearing idea (a mechanism, a condition, a
distinction, a failure mode), answerable in a sentence or two, phrased as why / how /
when-does-it-break rather than "what is". Never trivia, never yes/no.

The quality bar, by example:
  Weak:   "What is the Hall-Petch equation?"
  Strong: "Why does refining grain size raise yield strength, and at roughly what
           scale does $\\sigma_y = \\sigma_0 + k/\\sqrt{d}$ stop working?"
  Weak:   "What is the endurance limit?"
  Strong: "Steel has an endurance limit and aluminum does not. What does that change
           about how you design each against fatigue?"

Answers must teach, compactly: the result, the governing relation in $...$ TeX where
one exists, the physical mechanism in a sentence, and the boundary where it fails.
Use the learner's framing where it is correct; quietly fix it where it is not.
Output only the structured object."""

_GRADE_SYSTEM = """You grade a learner's free-recall answer against a reference answer, then nudge them.

Grade ONLY against the reference. Reward correct meaning even if the wording differs or
it's terse. If the core idea is present, mark "correct". If partially right or missing a
key piece, "partial". If absent/wrong, "wrong". Do NOT invent requirements beyond the
reference, and do not be harsh about phrasing.

Then ALWAYS write ONE short Socratic "poke" (never leave it empty): a single question
that pushes them toward the gap they missed, or — if they nailed it — one level deeper
(a "why", an edge case, or an application). Never reveal the answer. Keep it to one sentence."""


_IDEAS_SYSTEM = """You distill a study conversation into the KEY IDEAS of the topic, the rubric a
learner's future free recall will be graded against.

Write 3-8 one-line ideas. Each idea:
- is one self-contained claim, mechanism, formula, distinction, or condition worth
  remembering on its own (include the equation in $...$ TeX when there is one),
- uses the learner's own framing and examples where correct,
- is concrete enough to check a recall against ("boundaries block dislocation motion",
  not "understands grain boundaries").

Example, for a Hall-Petch conversation:
  1. $\\sigma_y = \\sigma_0 + k/\\sqrt{d}$: finer grains raise yield strength
  2. Mechanism: boundaries block dislocations, pile-ups must trigger slip across
  3. Strengthens without the usual ductility penalty
  4. Inverts below ~20 nm where boundary sliding takes over

Order from most to least central. No trivia, no duplicates. Output only the structured object."""

_RUBRIC_GRADE_SYSTEM = """You grade a learner's free recall of a topic against a numbered rubric of key ideas.

For EVERY rubric index, judge whether the learner's recall expressed that idea:
- "hit": the idea is present in substance (wording may differ wildly; terse is fine)
- "partial": touched but incomplete or muddled
- "miss": absent or wrong
Judge meaning, not phrasing. Do not require ideas beyond the rubric.

Then write ONE short Socratic poke (never empty, never revealing): aim it at the most
important missed idea — or, if everything was hit, one level deeper (a why, an edge
case, or an application). Output only the structured object."""

_DRILL_SYSTEM = """You write ONE focused active-recall question drilling a specific key idea the learner
keeps missing. The question targets exactly that idea (favor why/how/when phrasing),
is answerable in a sentence or two, and the answer is the idea itself, stated clearly.
Output only the structured object."""

_CONTRAST_SYSTEM = """You write ONE contrast card for two concepts a learner studies separately but could
confuse. The question forces discrimination: when do they differ, disagree, or apply —
not definitions of each. The answer states the key distinction crisply (include the
condition where choosing wrong matters). Use the learners' own notes. Output only the
structured object."""

_STUDENT_SYSTEM = """You are a curious FIRST-YEAR STUDENT being taught a topic by the learner. You do NOT
know the topic. Your job is to make their explanation earn its clarity:

- Ask exactly ONE short question per turn, the most natural confusion a beginner
  would actually have about what they just said.
- If they use jargon or a symbol without defining it, ask what it means.
- If they state a rule, ask why it's true, or what happens at the edge.
- If an explanation is genuinely clear, say what clicked in one short phrase, then
  probe the next gap.
Never lecture. Never correct them with facts. Never reveal that you know anything.
One or two sentences max per turn."""

REFINE_SYSTEM = """You improve ONE spaced-repetition card based on the learner's feedback about it.

You get the topic context, the current question/answer, and what the learner disliked.
Rewrite the card to address the feedback while keeping it a focused active-recall
prompt: one idea, answerable in a sentence or two, why/how/when-it-fails phrasing
preferred over definitions. Keep what the feedback didn't complain about. Output only
the structured object with the improved question and answer."""

_PRETTY_SYSTEM = """You typeset the math in a learner's note. They write informally — "sigma_y = sigma0 +
k/sqrt(d)", "P_cr = pi^2 EI over (KL)^2", "omega_n equals root k over m" — and you return
THE SAME TEXT with every mathematical expression converted to proper inline $...$ TeX
(\\sigma_y = \\sigma_0 + k/\\sqrt{d} etc.).

Rules:
- Do NOT change their prose wording, sentence order, or ideas. Only the math notation.
- Fix obvious slips in the equations themselves (a dropped square, a flipped ratio) when
  the surrounding text makes the intent unambiguous — silently, in the TeX.
- If a passage has no math, return it unchanged.
Output only the structured object."""

_FOCUS_SYSTEM = """The learner tells you what they want to prioritize in their reviews (an exam, a project,
a vague theme). Match their request against their ACTUAL subjects and topic titles.

Return only subjects/topic-ids from the provided lists that genuinely match the intent —
including semantic matches ("battery stuff" → "Battery Engineering"; "my vibrations
final" → "Vibrations"). Prefer whole subjects when the request is broad; pick specific
topic ids only when the request names specifics. Return nothing that doesn't match.
Output only the structured object."""

_SUBJECT_SYSTEM = """You file study notes into broad subject areas (e.g. "Machine Learning",
"Spanish", "Microeconomics", "Anatomy", "Personal Finance").

Return concise areas in Title Case, 1–3 words. STRONGLY prefer reusing an existing
subject when one reasonably fits; invent a new area only when none do, and reuse the
SAME new area across related notes. Never return an empty subject."""

_SPLIT_SYSTEM = """You extract distinct STUDY TOPICS from a block of text the learner pasted.

Each topic is a concise title (a concept, skill, result, or fact worth remembering on
its own), plus an optional one-line note ONLY if the text says something specific about
it. Split granularly enough that each could be reviewed separately, but never invent
topics that aren't in the text. Output only the structured object."""


class LLMService:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.preferred = model
        self.fast_preferred: str = ""   # optional smaller model for grading/classifying
        self.gen_style: str = DEFAULT_GEN_STYLE  # user-editable question/answer style
        self._resolved: Optional[str] = None

    def set_gen_style(self, style: str) -> None:
        self.gen_style = (style or "").strip() or DEFAULT_GEN_STYLE

    def _styled(self, system: str) -> str:
        return f"{system}\n\nSTYLE (follow strictly):\n{self.gen_style}"

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

    def set_fast_model(self, name: str) -> None:
        """A smaller local model for latency-sensitive calls (grading, classifying).
        Empty string = use the main model for everything."""
        if name and is_cloud_model(name):
            raise OllamaError("Cloud models are blocked to keep your data on-device.")
        self.fast_preferred = name or ""

    def resolve_fast_model(self) -> Optional[str]:
        if self.fast_preferred and self.fast_preferred in self.local_models():
            return self.fast_preferred
        return self.resolve_model()

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

    def _chat_stream(self, messages: list[dict], temperature: float = 0.5,
                     num_predict: int = 0) -> Iterator[str]:
        model = self.resolve_model()
        if not model:
            raise OllamaError("No local model available.")
        options = {"temperature": temperature}
        if num_predict:
            options["num_predict"] = num_predict   # cap tail latency
        payload = {
            "model": model, "messages": messages, "stream": True,
            "keep_alive": OLLAMA_KEEP_ALIVE, "options": options,
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
        self, messages: list[dict], schema: type[BaseModel], temperature: float = 0.3,
        num_predict: int = 0, fast: bool = False,
    ) -> BaseModel:
        model = self.resolve_fast_model() if fast else self.resolve_model()
        if not model:
            raise OllamaError("No local model available.")
        try:
            return self._complete_json_once(model, messages, schema, temperature, num_predict)
        except OllamaError as e:
            # A token cap can truncate the JSON mid-object (verbose models,
            # long rubrics). Retry once uncapped before giving up.
            if num_predict and "parse" in str(e).lower():
                return self._complete_json_once(model, messages, schema, temperature, 0)
            raise

    def _complete_json_once(
        self, model: str, messages: list[dict], schema: type[BaseModel],
        temperature: float, num_predict: int,
    ) -> BaseModel:
        options = {"temperature": temperature}
        if num_predict:
            options["num_predict"] = num_predict   # cap tail latency
        payload = {
            "model": model, "messages": messages, "stream": False,
            "format": schema.model_json_schema(),
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": options,
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(OLLAMA_TIMEOUT, connect=OLLAMA_CONNECT_TIMEOUT)) as client:
                resp = client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
                resp.raise_for_status()
                content = strip_think((resp.json().get("message") or {}).get("content", ""))
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama request failed: {e}")
        if not content:
            raise OllamaError("Empty response from model (possibly truncated by the token cap).")
        try:
            return schema.model_validate_json(content)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return schema.model_validate_json(match.group())
                except Exception:
                    pass
            raise OllamaError("Could not parse structured output (model output may be truncated).")

    # ---------- high-level features ----------

    def capture_followup_stream(self, history: list[dict]) -> Iterator[str]:
        messages = [{"role": "system", "content": _CAPTURE_SYSTEM}, *history]
        yield from self._chat_stream(messages, temperature=0.6, num_predict=160)

    def generate_cards(self, transcript: str, n: int = 4, basic_only: bool = False) -> list[dict]:
        messages = [
            {"role": "system", "content": self._styled(_CARDS_BASIC_SYSTEM if basic_only else _CARDS_SYSTEM)},
            {"role": "user", "content": f"Aim for about {n} questions.\n\nConversation:\n---\n{transcript}\n---"},
        ]
        result = self._complete_json(messages, CardSet, temperature=0.4, num_predict=1800)
        out: list[dict] = []
        for c in result.cards:
            ctype = (c.type or "basic").strip().lower()
            if ctype == "cloze" and not basic_only and c.source.strip():
                # a cloze is one sentence — drop any leaked transcript / extra lines
                src = c.source.strip().split("\n")[0].strip()
                if "{{c" in src:
                    out.append({"type": "cloze", "source": src})
            elif c.question.strip() and c.answer.strip():
                out.append({"type": "basic", "question": c.question.strip(), "answer": c.answer.strip()})
        if not out:
            raise OllamaError("Model returned no usable cards.")
        return out

    def extract_key_ideas(self, transcript: str) -> list[str]:
        messages = [
            {"role": "system", "content": self._styled(_IDEAS_SYSTEM)},
            {"role": "user", "content": f"Conversation:\n---\n{transcript[:4000]}\n---\nDistill the key ideas."},
        ]
        result = self._complete_json(messages, KeyIdeaList, temperature=0.3, num_predict=1200)
        return [i.strip() for i in result.ideas if i.strip()][:8]

    def grade_rubric(self, topic: str, ideas: list[str], user_answer: str) -> dict:
        listing = "\n".join(f"{i}. {idea}" for i, idea in enumerate(ideas))
        prompt = (
            f"Topic: {topic}\n\nRubric of key ideas:\n{listing}\n\n"
            f"Learner's free recall:\n{user_answer or '(left blank)'}"
        )
        messages = [
            {"role": "system", "content": _RUBRIC_GRADE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        grade = self._complete_json(messages, RubricGrade, temperature=0.1, num_predict=700, fast=True)
        results = ["miss"] * len(ideas)
        for item in grade.items:
            if 0 <= item.index < len(ideas):
                r = item.result.strip().lower()
                results[item.index] = r if r in ("hit", "partial", "miss") else "miss"
        return {"results": results, "poke": grade.poke.strip()}

    def drill_question(self, topic: str, idea: str) -> dict:
        messages = [
            {"role": "system", "content": self._styled(_DRILL_SYSTEM)},
            {"role": "user", "content": f"Topic: {topic}\nKey idea they keep missing: {idea}\n\nWrite the drill question."},
        ]
        result = self._complete_json(messages, GenCard, temperature=0.4, num_predict=800)
        if not (result.question.strip() and result.answer.strip()):
            raise OllamaError("Model returned no usable drill question.")
        return {"question": result.question.strip(), "answer": result.answer.strip()}

    def grade_recall(self, question: str, reference: str, user_answer: str) -> dict:
        prompt = (
            f"Question:\n{question}\n\nReference answer:\n{reference[:1200]}\n\n"
            f"Learner's recall:\n{user_answer or '(left blank)'}"
        )
        messages = [
            {"role": "system", "content": _GRADE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        grade = self._complete_json(messages, Grade, temperature=0.1, num_predict=400, fast=True)
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
        return self._complete_json(messages, SubjectGuess, temperature=0.2, num_predict=60, fast=True).subject.strip()

    def suggest_subjects(self, items: list[dict], existing: list[str]) -> list[dict]:
        ex = ", ".join(existing) if existing else "(none yet)"
        listing = "\n".join(f"- [{it['id']}] {it['title']}" for it in items)
        messages = [
            {"role": "system", "content": _SUBJECT_SYSTEM},
            {"role": "user", "content": f"Existing subjects: {ex}\n\nAssign each note a subject area "
                f"(reuse existing where sensible; use the SAME area for related notes):\n{listing}"},
        ]
        result = self._complete_json(messages, SubjectAssigns, temperature=0.2, num_predict=900)
        valid = {it["id"] for it in items}
        return [{"id": a.id, "subject": a.subject.strip()}
                for a in result.items if a.id in valid and a.subject.strip()]

    def contrast_card(self, a: dict, b: dict) -> dict:
        """One discrimination card for two confusable topics ({title, content} each)."""
        prompt = (
            f"Concept A: {a['title']}\n{(a.get('content') or '')[:800]}\n\n"
            f"Concept B: {b['title']}\n{(b.get('content') or '')[:800]}\n\n"
            "Write the contrast card."
        )
        messages = [{"role": "system", "content": self._styled(_CONTRAST_SYSTEM)},
                    {"role": "user", "content": prompt}]
        result = self._complete_json(messages, GenCard, temperature=0.4, num_predict=800)
        if not (result.question.strip() and result.answer.strip()):
            raise OllamaError("Model returned no usable contrast card.")
        return {"question": result.question.strip(), "answer": result.answer.strip()}

    def teach_student_stream(self, topic: str, history: list[dict]) -> Iterator[str]:
        """Stream the confused student's next question during a teach-back."""
        system = _STUDENT_SYSTEM + f"\n\nThe topic being taught to you: {topic}"
        messages = [{"role": "system", "content": system}, *history]
        yield from self._chat_stream(messages, temperature=0.7, num_predict=120)

    def prettify_math(self, text: str) -> str:
        """Echo the learner's paragraph back with informal math typeset as TeX."""
        messages = [
            {"role": "system", "content": _PRETTY_SYSTEM},
            {"role": "user", "content": text[:2000]},
        ]
        result = self._complete_json(messages, PrettyText, temperature=0.1,
                                     num_predict=900, fast=True)
        out = result.text.strip()
        # Refuse rewrites that drifted from the original (the model must only typeset)
        if not out or abs(len(out) - len(text)) > max(80, len(text)):
            return text
        return out

    def refine_card(self, topic: str, content: str, question: str, answer: str,
                    feedback: str) -> dict:
        prompt = build_refine_prompt(topic, content, question, answer, feedback)
        messages = [{"role": "system", "content": self._styled(REFINE_SYSTEM)},
                    {"role": "user", "content": prompt}]
        result = self._complete_json(messages, GenCard, temperature=0.4, num_predict=1000)
        if not (result.question.strip() and result.answer.strip()):
            raise OllamaError("Model returned no usable card.")
        return {"question": result.question.strip(), "answer": result.answer.strip()}

    def interpret_focus(self, text: str, subjects: list[str], topics: list[dict]) -> dict:
        """Map a free-text 'what I want to prioritize' onto actual subjects/topic ids."""
        subj = ", ".join(subjects) if subjects else "(none)"
        listing = "\n".join(f"- [{t['id']}] {t['title']}" for t in topics[:200])
        messages = [
            {"role": "system", "content": _FOCUS_SYSTEM},
            {"role": "user", "content": f"Subjects: {subj}\n\nTopics:\n{listing}\n\n"
                f"The learner says: \"{text.strip()[:400]}\"\n\nWhat should be prioritized?"},
        ]
        plan = self._complete_json(messages, FocusPlan, temperature=0.1,
                                   num_predict=300, fast=True)
        valid_ids = {t["id"] for t in topics}
        subj_lower = {s.lower(): s for s in subjects}
        return {
            "subjects": [subj_lower[s.strip().lower()] for s in plan.subjects
                         if s.strip().lower() in subj_lower],
            "learning_ids": [i for i in plan.learning_ids if i in valid_ids],
        }

    def split_topics(self, text: str) -> list[dict]:
        messages = [
            {"role": "system", "content": _SPLIT_SYSTEM},
            {"role": "user", "content": f"Text:\n---\n{text[:4000]}\n---\nExtract the study topics."},
        ]
        result = self._complete_json(messages, TopicList, temperature=0.2, num_predict=900)
        out = []
        for t in result.topics:
            title = t.title.strip()
            if title:
                out.append({"title": title, "note": t.note.strip()})
        return out


def build_refine_prompt(topic: str, content: str, question: str, answer: str,
                        feedback: str) -> str:
    """Shared by the local model and the opt-in cloud path."""
    return (
        f"Topic: {topic}\n\nTopic notes:\n{(content or '')[:1500]}\n\n"
        f"Current question:\n{question}\n\nCurrent answer:\n{answer}\n\n"
        f"Learner's feedback about this card:\n{feedback or 'Make it sharper and more physical.'}"
    )


_service: Optional[LLMService] = None


def get_llm() -> LLMService:
    global _service
    if _service is None:
        _service = LLMService()
    return _service
