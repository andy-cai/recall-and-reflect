"""Validate the curriculum seed files and the import/remove paths.

Every deck must parse, every topic must carry the full structure (title,
subject, content, recall prompt, 3+ key ideas), importing into a fresh
database must round-trip with correct cards and idempotency, and --remove
must delete exactly the seed-titled topics and nothing else.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.db.repository import Repository

SEED_DIR = Path(__file__).resolve().parent.parent / "seeds"


def load_tool():
    """Import tools/seed_curriculum.py as a module (tools/ is not a package)."""
    path = SEED_DIR.parent / "tools" / "seed_curriculum.py"
    spec = importlib.util.spec_from_file_location("seed_curriculum", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_all():
    decks = []
    for path in sorted(SEED_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            decks.append((path.name, json.load(f)))
    return decks


class TestSeedFiles(unittest.TestCase):
    def test_decks_exist_and_parse(self):
        decks = load_all()
        self.assertGreaterEqual(len(decks), 7)
        self.assertGreaterEqual(sum(len(d["topics"]) for _, d in decks), 80)

    def test_every_topic_is_complete(self):
        for fname, deck in load_all():
            for t in deck["topics"]:
                with self.subTest(file=fname, topic=t.get("title", "?")):
                    self.assertTrue(t["title"].strip())
                    self.assertTrue(t["subject"].strip())
                    self.assertGreater(len(t["content"].strip()), 80)
                    self.assertTrue(t["recall_prompt"].strip())
                    self.assertNotIn("recall everything", t["recall_prompt"].lower(),
                                     "recall prompts should be tasks, not generic")
                    self.assertGreaterEqual(len(t["key_ideas"]), 3)
                    self.assertLessEqual(len(t["key_ideas"]), 8)
                    for c in t.get("cards", []):
                        self.assertTrue(c["question"].strip())
                        self.assertTrue(c["answer"].strip())

    def test_titles_unique_across_decks(self):
        seen = set()
        for fname, deck in load_all():
            for t in deck["topics"]:
                key = t["title"].strip().lower()
                self.assertNotIn(key, seen, f"duplicate topic title: {t['title']}")
                seen.add(key)


class TestImport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = Database(Path(self._tmp.name) / "seed.db")
        db.initialize()
        self.repo = Repository(db=db)

    def tearDown(self):
        self._tmp.cleanup()

    def _import(self):
        created = 0
        existing = {r["title"].strip().lower()
                    for r in self.repo.db.fetch_all("SELECT title FROM learnings")}
        for _, deck in load_all():
            for t in deck["topics"]:
                if t["title"].strip().lower() in existing:
                    continue
                lid = self.repo.create_learning(t["title"], t["content"],
                                                subject=t["subject"], tags=t.get("tags", []))
                self.repo.set_key_ideas(lid, t["key_ideas"])
                self.repo.create_recall_card(lid, t["title"], t["content"],
                                             prompt=t.get("recall_prompt"))
                for c in t.get("cards", []):
                    self.repo.create_question(lid, c["question"], c["answer"])
                existing.add(t["title"].strip().lower())
                created += 1
        return created

    def test_import_and_idempotency(self):
        n = self._import()
        self.assertGreaterEqual(n, 80)
        self.assertEqual(self._import(), 0)  # second run creates nothing

    def test_recall_card_uses_custom_prompt(self):
        self._import()
        row = self.repo.db.fetch_one(
            "SELECT q.question FROM questions q JOIN learnings l ON l.id = q.learning_id "
            "WHERE l.title = ? AND q.card_type = 'recall'",
            ("Hall-Petch & grain size strengthening",))
        self.assertIn("grain size", row["question"].lower())
        self.assertNotIn("recall everything", row["question"].lower())

    def test_queue_respects_new_per_day_after_import(self):
        self._import()
        self.repo.set_setting("new_per_day", 6)
        queue = self.repo.get_due_questions()
        self.assertEqual(len(queue), 6)


class TestRemove(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = Database(Path(self._tmp.name) / "seed.db")
        db.initialize()
        self.repo = Repository(db=db)
        self.tool = load_tool()
        self.decks = self.tool.load_decks()
        self.tool.import_decks(self.repo, self.decks, verbose=False)

    def tearDown(self):
        self._tmp.cleanup()

    def _active_titles(self):
        rows = self.repo.db.fetch_all("SELECT title FROM learnings WHERE is_active = 1")
        return [r["title"] for r in rows]

    def test_preview_deletes_nothing(self):
        before = len(self._active_titles())
        topics, _ = self.tool.remove_decks(self.repo, self.decks, apply=False, verbose=False)
        self.assertEqual(topics, before)
        self.assertEqual(len(self._active_titles()), before)

    def test_remove_spares_user_topics_and_cascades(self):
        self.repo.create_learning("My own topic", "content long enough to matter " * 5,
                                  subject="Mine")
        topics, _ = self.tool.remove_decks(self.repo, self.decks, apply=True, verbose=False)
        self.assertGreaterEqual(topics, 80)
        self.assertEqual(self._active_titles(), ["My own topic"])
        orphans = self.repo.db.fetch_one(
            "SELECT COUNT(*) AS n FROM questions q "
            "LEFT JOIN learnings l ON l.id = q.learning_id WHERE l.id IS NULL")["n"]
        self.assertEqual(orphans, 0)
        # second pass finds nothing left to remove
        self.assertEqual(self.tool.remove_decks(self.repo, self.decks,
                                                apply=True, verbose=False)[0], 0)

    def test_renamed_topic_survives_remove(self):
        row = self.repo.db.fetch_one(
            "SELECT id FROM learnings WHERE title = ?", ("Column buckling",))
        self.repo.db.execute(
            "UPDATE learnings SET title = ? WHERE id = ?",
            ("Column buckling (my notes)", row["id"]))
        self.tool.remove_decks(self.repo, self.decks, apply=True, verbose=False)
        self.assertEqual(self._active_titles(), ["Column buckling (my notes)"])

    def test_review_history_is_counted(self):
        q = self.repo.db.fetch_one("SELECT id FROM questions LIMIT 1")
        self.repo.db.execute(
            "INSERT INTO reviews (question_id, rating, reviewed_at) "
            "VALUES (?, 3, '2026-01-01T00:00:00')", (q["id"],))
        _, reviews = self.tool.remove_decks(self.repo, self.decks, apply=False, verbose=False)
        self.assertEqual(reviews, 1)


if __name__ == "__main__":
    unittest.main()
