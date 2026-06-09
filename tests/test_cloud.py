"""Cloud assist gating: it must be impossible to reach the network without
the env key AND the explicit toggle. No network is touched in these tests."""

import os
import unittest
from unittest import mock

from app.services.cloud import CloudAssist, CloudError


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
            self.assertIn("ANTHROPIC_API_KEY", st["reason"])

    def test_key_without_toggle_is_not_ready(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            st = self.cloud.status()
            self.assertFalse(st["ready"])
            self.assertIn("switched off", st["reason"])

    def test_complete_json_refuses_when_not_ready(self):
        class Dummy:  # schema class is never touched when gating refuses
            pass

        with self.assertRaises(CloudError):
            self.cloud.complete_json("sys", "prompt", Dummy)

    def test_model_falls_back_to_default_on_unknown(self):
        self.cloud.set_model("gpt-9000")
        self.assertEqual(self.cloud.model, "claude-opus-4-8")
        self.cloud.set_model("claude-haiku-4-5")
        self.assertEqual(self.cloud.model, "claude-haiku-4-5")


if __name__ == "__main__":
    unittest.main()
