"""Opt-in cloud assist via the Anthropic API (official `anthropic` SDK).

Strictly opt-in, per-click: nothing here runs unless BOTH are true —
ANTHROPIC_API_KEY is set in the environment AND the Settings toggle is on —
and even then only when the user explicitly clicks a cloud action (e.g.
"Improve with Claude" on a card). Reviews, capture chat, grading, and
embeddings always stay on the local models. Only the single card/topic text
involved in the click is sent.
"""

import importlib.util
import os
from typing import Any, Optional

from app.config import CLOUD_DEFAULT_MODEL, CLOUD_MODELS


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
    def key_present() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    @staticmethod
    def sdk_installed() -> bool:
        return importlib.util.find_spec("anthropic") is not None

    def status(self) -> dict:
        ready = self.enabled and self.key_present() and self.sdk_installed()
        reason = None
        if not self.enabled:
            reason = "Cloud assist is switched off."
        elif not self.key_present():
            reason = "Set ANTHROPIC_API_KEY in the environment, then restart."
        elif not self.sdk_installed():
            reason = "Install the SDK: pip install anthropic"
        return {"enabled": self.enabled, "model": self.model,
                "key_present": self.key_present(), "ready": ready, "reason": reason}

    # ---------- calls ----------

    def complete_json(self, system: str, prompt: str, schema: type,
                      max_tokens: int = 2000) -> Any:
        """One structured-output Messages API call. Raises CloudError unless ready."""
        st = self.status()
        if not st["ready"]:
            raise CloudError(st["reason"] or "Cloud assist is not configured.")
        import anthropic
        client = anthropic.Anthropic()
        try:
            response = client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
        except anthropic.AuthenticationError:
            raise CloudError("Anthropic API key was rejected — check ANTHROPIC_API_KEY.")
        except anthropic.RateLimitError:
            raise CloudError("Rate limited by the Anthropic API — try again shortly.")
        except anthropic.APIError as e:
            raise CloudError(f"Cloud request failed: {getattr(e, 'message', e)}")
        if response.parsed_output is None:
            raise CloudError("Cloud model returned no structured output.")
        return response.parsed_output

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
