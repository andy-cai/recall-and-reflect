"""Context-window handling for local Ollama calls.

Ollama defaults to a 4k context on GPUs under 24 GB; the app must request its
own window on every call (one fixed value, so the model is never reloaded) and
keep its inputs inside it. A fake HTTP client captures payloads; no network."""

import json
import unittest
from unittest import mock

from app.config import OLLAMA_NUM_CTX
from app.services import llm as llm_mod
from app.services.llm import LLMService, clip_middle, fit_history


class _Resp:
    def __init__(self, body: dict, lines=None):
        self.status_code = 200
        self._body = body
        self._lines = lines or []

    def json(self):
        return self._body

    def read(self):
        return b""

    def iter_lines(self):
        return iter(self._lines)

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeClient:
    payloads: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        return _Resp({"models": [{"name": "qwen3.5:9b"}]})

    def post(self, url, json=None, **kw):
        _FakeClient.payloads.append(json)
        return _Resp({"message": {"content": '{"subject": "Fluids"}'}})

    def stream(self, method, url, json=None, **kw):
        _FakeClient.payloads.append(json)
        line = '{"message": {"content": "Why?"}, "done": true}'
        return _Resp({}, lines=[line])


class TestNumCtxOnEveryCall(unittest.TestCase):
    def setUp(self):
        _FakeClient.payloads = []
        self.patch = mock.patch.object(llm_mod.httpx, "Client", _FakeClient)
        self.patch.start()
        self.llm = LLMService("qwen3.5:9b")

    def tearDown(self):
        self.patch.stop()

    def test_json_stream_and_warm_share_one_num_ctx(self):
        self.llm.suggest_subject("Bernoulli along a streamline", [])
        list(self.llm.capture_followup_stream([{"role": "user", "content": "learned x"}]))
        self.llm.warm()
        ctxs = [p["options"]["num_ctx"] for p in _FakeClient.payloads]
        self.assertEqual(len(ctxs), 3)
        self.assertEqual(set(ctxs), {OLLAMA_NUM_CTX})

    def test_card_generation_prompt_fits_the_window(self):
        huge = "word " * 40000            # ~200k chars of transcript
        with mock.patch.object(LLMService, "_complete_json_once",
                               side_effect=lambda m, msgs, *a, **k: self._capture(msgs)):
            try:
                self.llm.generate_cards(huge)
            except Exception:
                pass
        chars = sum(len(m["content"]) for m in self._msgs)
        self.assertLess(chars / 4, OLLAMA_NUM_CTX * 0.75)   # room left for the answer

    def _capture(self, msgs):
        self._msgs = msgs
        raise llm_mod.OllamaError("stop")


class TestInputFitting(unittest.TestCase):
    def test_clip_middle_keeps_both_ends(self):
        text = "START " + "x" * 1000 + " END"
        out = clip_middle(text, 120)
        self.assertTrue(out.startswith("START"))
        self.assertTrue(out.endswith("END"))
        self.assertLessEqual(len(out), 130)
        self.assertEqual(clip_middle("short", 120), "short")

    def test_fit_history_keeps_first_and_latest(self):
        hist = [{"role": "user", "content": "FIRST " + "a" * 50}]
        for i in range(40):
            hist.append({"role": "assistant" if i % 2 == 0 else "user",
                         "content": f"turn{i} " + "b" * 200})
        out = fit_history(hist, 2000)
        self.assertTrue(out[0]["content"].startswith("FIRST"))
        self.assertEqual(out[-1]["content"], hist[-1]["content"])
        self.assertLessEqual(sum(len(m["content"]) for m in out), 2000)

    def test_fit_history_short_chat_untouched(self):
        hist = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        self.assertEqual(fit_history(hist, 2000), hist)

    def test_fit_history_does_not_mutate_input(self):
        hist = [{"role": "user", "content": "z" * 5000}]
        fit_history(hist, 1000)
        self.assertEqual(len(hist[0]["content"]), 5000)


if __name__ == "__main__":
    unittest.main()
