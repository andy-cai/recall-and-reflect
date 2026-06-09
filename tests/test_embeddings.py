"""Tests for embedding storage and similarity math (no Ollama needed —
vectors are injected directly)."""

import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.db.repository import Repository
from app.services.embeddings import EmbeddingService, cosine, _hash, _text_for


class EmbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = Database(Path(self._tmp.name) / "test.db")
        db.initialize()
        self.repo = Repository(db=db)
        self.emb = EmbeddingService(db=db)

    def tearDown(self):
        self._tmp.cleanup()

    def topic(self, title, vec):
        lid = self.repo.create_learning(title, f"content of {title}")
        self.emb.store(lid, vec, _hash(_text_for(title, f"content of {title}")))
        return lid


class TestCosine(unittest.TestCase):
    def test_identical(self):
        self.assertAlmostEqual(cosine([1, 2, 3], [1, 2, 3]), 1.0)

    def test_orthogonal(self):
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)

    def test_opposite(self):
        self.assertAlmostEqual(cosine([1, 0], [-1, 0]), -1.0)

    def test_degenerate(self):
        self.assertEqual(cosine([], [1]), 0.0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)


class TestNearest(EmbCase):
    def test_orders_by_similarity_and_excludes_self(self):
        a = self.topic("tresca", [1.0, 0.0, 0.1])
        b = self.topic("von mises", [0.95, 0.05, 0.1])   # near a
        c = self.topic("injection molding", [0.0, 1.0, 0.0])
        near = self.emb.nearest(a, k=5)
        ids = [n["learning_id"] for n in near]
        self.assertEqual(ids[0], b)
        self.assertNotIn(a, ids)
        self.assertNotIn(c, ids)  # below the floor

    def test_inactive_learnings_are_invisible(self):
        a = self.topic("a", [1.0, 0.0])
        b = self.topic("b", [0.99, 0.01])
        self.repo.db.execute("UPDATE learnings SET is_active = 0 WHERE id = ?", (b,))
        self.assertEqual(self.emb.nearest(a), [])

    def test_store_upserts(self):
        a = self.topic("a", [1.0, 0.0])
        self.emb.store(a, [0.0, 1.0], "newhash")
        self.assertEqual(self.emb.get_vector(a), [0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
