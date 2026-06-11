"""Opt-in cloud assist via the Google Gemini API (free tier).

Strictly opt-in, per-click: nothing here runs unless BOTH are true —
GEMINI_API_KEY (or GOOGLE_API_KEY) is set in the environment AND the Settings
toggle is on — and even then only when the user explicitly clicks a cloud
action (e.g. "Improve with Gemini" on a card). Reviews, capture chat, grading,
and embeddings always stay on the local models. Only the single card/topic
text involved in the click is sent.

Get a free key at https://aistudio.google.com (the free tier covers this
app's per-click usage comfortably).
"""

import json
import os
import re
from typing import Any, Optional

from app.config import CLOUD_BASE_URL, CLOUD_DEFAULT_MODEL, CLOUD_MODELS


class CloudError(Exception):
    pass


class CloudAssist:
    def __init__(self):
        self.enabled: bool = False
        self.model: str = CLOUD_DEFAULT_MODEL

    # ---------- configuration ----------

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def set_model(self, model: str) -> None:
        self.model = model if model in CLOUD_MODELS else CLOUD_DEFAULT_MODEL

    @staticmethod
    def _key() -> str:
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

    @classmethod
    def key_present(cls) -> bool:
        return bool(cls._key())

    def status(self) -> dict:
        ready = self.enabled and self.key_present()
        reason = None
        if not self.enabled:
            reason = "Cloud assist is switched off."
        elif not self.key_present():
            reason = "Set GEMINI_API_KEY in the environment (free key at aistudio.google.com), then restart."
        return {"enabled": self.enabled, "model": self.model,
                "key_present": self.key_present(), "ready": ready, "reason": reason}

    # ---------- calls ----------

    def complete_json(self, system: str, prompt: str, schema: type,
                      max_tokens: int = 2500) -> Any:
        """One structured-output generateContent call, validated against the
        pydantic schema. Raises CloudError unless ready."""
        st = self.status()
        if not st["ready"]:
            raise CloudError(st["reason"] or "Cloud assist is not configured.")

        # Dynamic thinking stays ON: quality over latency for these per-click
        # calls. Thoughts count against the output budget, so give headroom.
        gen_config: dict = {
            "responseMimeType": "application/json",
            "temperature": 0.4,
            "maxOutputTokens": max(max_tokens, 8000),
        }
        sys_text = (f"{system}\n\nReturn ONLY a JSON object matching this schema "
                    f"(no prose, no code fences):\n{json.dumps(schema.model_json_schema())}")
        text = self._generate(sys_text, [{"role": "user", "parts": [{"text": prompt}]}], gen_config)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            return schema.model_validate_json(text)
        except Exception:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    return schema.model_validate_json(match.group())
                except Exception:
                    pass
            raise CloudError("Could not parse Gemini's structured output.")

    def _generate(self, system: str, contents: list, gen_config: dict) -> str:
        """One generateContent call; returns the joined text parts."""
        st = self.status()
        if not st["ready"]:
            raise CloudError(st["reason"] or "Cloud assist is not configured.")
        import httpx
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": gen_config,
        }
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    f"{CLOUD_BASE_URL}/models/{self.model}:generateContent",
                    headers={"x-goog-api-key": self._key()},
                    json=body,
                )
        except httpx.HTTPError as e:
            raise CloudError(f"Cloud request failed: {e}")
        if resp.status_code == 400:
            raise CloudError("Gemini rejected the request. Check that GEMINI_API_KEY is valid.")
        if resp.status_code == 429:
            raise CloudError("Free-tier rate limit hit. Wait a minute and try again.")
        if resp.status_code >= 500:
            raise CloudError(f"Gemini service error ({resp.status_code}). Try again shortly.")
        if resp.status_code != 200:
            raise CloudError(f"Cloud request failed (HTTP {resp.status_code}).")
        try:
            parts = resp.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except (KeyError, IndexError, ValueError):
            raise CloudError("Gemini returned no usable content (possibly safety-blocked).")

    def followup(self, history: list[dict], style: str) -> str:
        """One Socratic follow-up for the Reflect manuscript (engineering mode)."""
        from app.services.llm import _CAPTURE_SYSTEM
        contents = [{"role": "user" if m["role"] == "user" else "model",
                     "parts": [{"text": m["content"]}]} for m in history]
        system = f"{_CAPTURE_SYSTEM}\n\nSTYLE (follow strictly):\n{style}"
        return self._generate(system, contents,
                              {"temperature": 0.7, "maxOutputTokens": 8000})

    def extract_key_ideas(self, transcript: str, style: str) -> list[str]:
        from app.services.llm import _IDEAS_SYSTEM, KeyIdeaList
        system = f"{_IDEAS_SYSTEM}\n\nSTYLE (follow strictly):\n{style}"
        prompt = f"Conversation:\n---\n{transcript[:8000]}\n---\nDistill the key ideas."
        result = self.complete_json(system, prompt, KeyIdeaList, max_tokens=3000)
        return [i.strip() for i in result.ideas if i.strip()][:8]

    def refine_card(self, topic: str, content: str, question: str, answer: str,
                    feedback: str, style: str) -> dict:
        from app.services.llm import REFINE_SYSTEM, GenCard, build_refine_prompt
        system = f"{REFINE_SYSTEM}\n\nSTYLE (follow strictly):\n{style}"
        prompt = build_refine_prompt(topic, content, question, answer, feedback)
        result = self.complete_json(system, prompt, GenCard, max_tokens=1500)
        if not (result.question.strip() and result.answer.strip()):
            raise CloudError("Cloud model returned no usable card.")
        return {"question": result.question.strip(), "answer": result.answer.strip()}

    def generate_cards(self, transcript: str, n: int, style: str) -> list[dict]:
        from app.services.llm import _CARDS_BASIC_SYSTEM, CardSet
        system = f"{_CARDS_BASIC_SYSTEM}\n\nSTYLE (follow strictly):\n{style}"
        prompt = f"Aim for about {n} questions.\n\nConversation:\n---\n{transcript[:6000]}\n---"
        result = self.complete_json(system, prompt, CardSet, max_tokens=3000)
        out = [{"type": "basic", "question": c.question.strip(), "answer": c.answer.strip()}
               for c in result.cards if c.question.strip() and c.answer.strip()]
        if not out:
            raise CloudError("Cloud model returned no usable cards.")
        return out


_service: Optional[CloudAssist] = None


def get_cloud() -> CloudAssist:
    global _service
    if _service is None:
        _service = CloudAssist()
    return _service
