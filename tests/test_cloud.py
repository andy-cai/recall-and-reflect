"""Cloud assist gating: it must be impossible to reach the network without
the env key AND the explicit toggle. No network is touched in these tests."""

import os
import unittest
from unittest import mock

from app.config import CLOUD_DEFAULT_MODEL, CLOUD_MODELS
from app.services.cloud import CloudAssist, CloudError, usable_models


class TestCloudGating(unittest.TestCase):
    def setUp(self):
        self.cloud = CloudAssist()

    def test_off_by_default(self):
        self.assertFalse(self.cloud.enabled)
        self.assertFalse(self.cloud.status()["ready"])

    def test_enabled_without_key_is_not_ready(self):
        self.cloud.set_enabled(True)
        with mock.patch.dict(os.environ, {}, clear=True):
            st = self.cloud.status()
            self.assertFalse(st["ready"])
            self.assertIn("GEMINI_API_KEY", st["reason"])

    def test_key_without_toggle_is_not_ready(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            st = self.cloud.status()
            self.assertFalse(st["ready"])
            self.assertIn("switched off", st["reason"])

    def test_google_api_key_also_accepted(self):
        self.cloud.set_enabled(True)
        with mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}, clear=True):
            self.assertTrue(self.cloud.status()["ready"])

    def test_complete_json_refuses_when_not_ready(self):
        class Dummy:  # schema class is never touched when gating refuses
            pass

        with self.assertRaises(CloudError):
            self.cloud.complete_json("sys", "prompt", Dummy)

    def test_model_falls_back_to_default_on_unknown(self):
        self.cloud.set_model("gpt-9000")
        self.assertEqual(self.cloud.model, CLOUD_DEFAULT_MODEL)
        self.cloud.set_model("gemini-3.6-flash")
        self.assertEqual(self.cloud.model, "gemini-3.6-flash")

    def test_model_id_cannot_inject_into_the_url(self):
        for bad in ("gemini-x/../../v1/files", "gemini-x:streamGenerateContent?alt=sse",
                    "gemini-x?key=1", "models/gemini-x", "GEMINI-X"):
            self.cloud.set_model(bad)
            self.assertEqual(self.cloud.model, CLOUD_DEFAULT_MODEL, bad)


_LISTING = {"models": [
    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent", "countTokens"]},
    {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-4-argon-preview", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.6-pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.6-flash-tts", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-002", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-3.6-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-bison", "supportedGenerationMethods": ["generateText"]},
]}


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Client:
    """Fake httpx.Client: GET /models returns the listing; POST answers with
    `post_status`. Records every URL so tests can see what would go out."""
    post_status = 200
    urls: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        _Client.urls.append(url)
        return _Resp(200, _LISTING)

    def post(self, url, **kw):
        _Client.urls.append(url)
        body = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        return _Resp(_Client.post_status, body)


class TestModelDiscovery(unittest.TestCase):
    def setUp(self):
        _Client.urls, _Client.post_status = [], 200
        self.cloud = CloudAssist()
        self.cloud.set_enabled(True)
        self.patches = [
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            mock.patch("httpx.Client", _Client),
            mock.patch.object(CloudAssist, "_log", lambda *a, **k: None),
            mock.patch.object(CloudAssist, "_people_names", staticmethod(lambda: [])),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_filter_and_order(self):
        self.assertEqual(usable_models(_LISTING["models"]), [
            "gemini-3.8-flash", "gemini-3.6-flash",      # stable Flash, newest first
            "gemini-3.5-flash-lite",                     # then Lite
            "gemini-3.6-pro",                            # then Pro
            "gemini-4-argon-preview",                    # previews last
        ])

    def test_no_listing_call_unless_ready(self):
        self.cloud.set_enabled(False)
        self.assertEqual(self.cloud.available_models()[:2], list(CLOUD_MODELS))
        self.assertEqual(_Client.urls, [])

    def test_listing_is_cached(self):
        self.cloud.available_models()
        self.cloud.available_models()
        self.assertEqual(len(_Client.urls), 1)

    def test_retired_saved_model_is_remapped_before_sending(self):
        self.cloud.set_model("gemini-2.5-flash")       # shut down 2026-10-16
        self.cloud._generate("sys", [{"role": "user", "parts": [{"text": "hi"}]}], {})
        sent = [u for u in _Client.urls if ":generateContent" in u]
        self.assertEqual(len(sent), 1)
        self.assertNotIn("gemini-2.5-flash", sent[0])
        self.assertIn("/models/gemini-3.8-flash:generateContent", sent[0])

    def test_404_explains_and_invalidates_the_list(self):
        self.cloud.available_models()
        _Client.post_status = 404
        with self.assertRaises(CloudError) as ctx:
            self.cloud._generate("sys", [{"role": "user", "parts": [{"text": "hi"}]}], {})
        self.assertIn("no longer offers", str(ctx.exception))
        self.assertIsNone(self.cloud._listed)


if __name__ == "__main__":
    unittest.main()
