"""Ollama cloud models must never be selectable: they would send notes off-device.

Ollama names them two ways ("gpt-oss:120b-cloud", "gemma4:cloud") and marks
them structurally in /api/tags with remote_host / remote_model. No network is
touched in these tests."""

import unittest

from app.services.llm import LLMService, OllamaError, is_cloud_model, local_model_names


class TestCloudTagBlocking(unittest.TestCase):
    def test_both_naming_schemes_are_cloud(self):
        for tag in ("gpt-oss:120b-cloud", "qwen3.5:cloud", "gemma4:cloud",
                    "deepseek-v4-flash:cloud", "GEMMA4:CLOUD"):
            self.assertTrue(is_cloud_model(tag), tag)

    def test_local_tags_pass(self):
        for tag in ("qwen3:14b", "gemma4:31b", "gemma4:e4b", "embeddinggemma",
                    "qwen3.5:9b", "gemma4:latest"):
            self.assertFalse(is_cloud_model(tag), tag)

    def test_listing_drops_remote_entries_whatever_their_name(self):
        entries = [
            {"name": "qwen3:14b"},
            {"name": "gemma4:cloud"},
            {"name": "renamed-alias", "remote_host": "https://ollama.com:443",
             "remote_model": "gemma4:31b"},
            {"name": "other-alias", "remote_model": "kimi-k3"},
            {"name": ""},
            "garbage",
        ]
        self.assertEqual(local_model_names(entries), ["qwen3:14b"])

    def test_setters_refuse_cloud_tags(self):
        llm = LLMService()
        with self.assertRaises(OllamaError):
            llm.set_model("gemma4:cloud")
        with self.assertRaises(OllamaError):
            llm.set_fast_model("gemma4:cloud")


if __name__ == "__main__":
    unittest.main()
