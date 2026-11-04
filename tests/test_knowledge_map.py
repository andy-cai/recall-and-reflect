"""Knowledge map: outline parsing, editing ops, computed status, matching.

Run: python -m unittest tests.test_knowledge_map
"""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.db.database import Database, to_iso
from app.db.knowledge_map import MapStore, parse_outline
from app.db.repository import Repository

OUTLINE = """\
- Mechanics of Materials
    ○ Defining and calculating stresses
        ▪ Mohr's circle
        ▪ Buckling failure
    ○ Ductile, brittle, and fatigue failure
        ▪ ! TTT/CCT diagrams
## MFE
- Battery
\t- Cell capacity testing
"""


class MapCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = Database(Path(self._tmp.name) / "test.db")
        db.initialize()
        self.repo = Repository(db=db)
        self.map = MapStore(db=db)

    def tearDown(self):
        self._tmp.cleanup()

    def by_text(self, tree=None):
        tree = tree or self.map.tree()
        return {n["text"]: n for n in tree["nodes"]}

    def topic(self, title, stability=None, reviewed_days_ago=None, cards=1):
        lid = self.repo.create_learning(title, f"about {title}")
        for i in range(cards):
            qid = self.repo.create_question(lid, f"{title} q{i}", "a")
            if stability is not None:
                now = datetime.now()
                self.repo.db.execute(
                    "UPDATE questions SET state = 2, stability = ?, difficulty = 5, "
                    "last_reviewed_at = ?, next_review_at = ? WHERE id = ?",
                    (stability, to_iso(now - timedelta(days=reviewed_days_ago)),
                     to_iso(now + timedelta(days=3)), qid))
        return lid


class TestParse(unittest.TestCase):
    def test_depth_bullets_flags_and_source(self):
        rows = parse_outline(OUTLINE)
        self.assertEqual([r["depth"] for r in rows], [0, 1, 2, 2, 1, 2, 0, 1])
        self.assertEqual(rows[2]["text"], "Mohr's circle")
        self.assertTrue(rows[5]["flag"])
        self.assertEqual(rows[5]["text"], "TTT/CCT diagrams")
        self.assertIsNone(rows[0]["source"])
        self.assertEqual(rows[6]["source"], "MFE")
        self.assertEqual(rows[7]["text"], "Cell capacity testing")

    def test_trailing_flag_and_numbered_bullets(self):
        rows = parse_outline("1. Thermo\n   a) Brayton cycle !\n")
        self.assertEqual([r["text"] for r in rows], ["Thermo", "Brayton cycle"])
        self.assertTrue(rows[1]["flag"])


class TestEditing(MapCase):
    def test_import_builds_tree(self):
        self.assertEqual(self.map.import_outline(OUTLINE), 8)
        n = self.by_text()
        self.assertEqual(n["Mohr's circle"]["parent_id"], n["Defining and calculating stresses"]["id"])
        self.assertEqual(n["Cell capacity testing"]["source"], "MFE")
        self.assertTrue(n["TTT/CCT diagrams"]["flag"])
        self.assertEqual(self.map.path(n["Buckling failure"]["id"]),
                         ["Mechanics of Materials", "Defining and calculating stresses", "Buckling failure"])

    def test_add_after_inserts_in_place(self):
        a = self.map.add_node("A")
        c = self.map.add_node("C")
        b = self.map.add_node("B", after_id=a)
        order = [n["text"] for n in sorted(self.map.tree()["nodes"], key=lambda n: n["position"])]
        self.assertEqual(order, ["A", "B", "C"])
        self.assertIsNone(self.map.get_node(b)["parent_id"])
        self.assertTrue(c)

    def test_indent_outdent_up_down(self):
        a = self.map.add_node("A")
        b = self.map.add_node("B")
        self.assertFalse(self.map.shift(a, "indent"))     # first sibling can't indent
        self.assertTrue(self.map.shift(b, "indent"))
        self.assertEqual(self.map.get_node(b)["parent_id"], a)
        self.assertTrue(self.map.shift(b, "outdent"))
        self.assertIsNone(self.map.get_node(b)["parent_id"])
        self.assertTrue(self.map.shift(b, "up"))
        self.assertEqual(self.map.get_node(b)["position"], 0)
        self.assertFalse(self.map.shift(b, "up"))

    def test_move_refuses_cycles(self):
        a = self.map.add_node("A")
        b = self.map.add_node("B", parent_id=a)
        self.assertFalse(self.map.move(a, b))
        self.assertTrue(self.map.move(b, None, 0))

    def test_delete_cascades_but_keeps_topics(self):
        self.map.import_outline(OUTLINE)
        n = self.by_text()
        lid = self.topic("Mohr's circle")
        self.map.link(n["Mohr's circle"]["id"], lid)
        self.assertEqual(self.map.delete_node(n["Mechanics of Materials"]["id"]), 6)
        self.assertNotIn("Mohr's circle", self.by_text())
        self.assertIsNotNone(self.repo.get_learning(lid))

    def test_inbox_items_stay_out_of_the_tree_until_placed(self):
        root = self.map.add_node("Applied Math")
        ib = self.map.add_node("Solutions of common ODEs", kind="inbox")
        tree = self.map.tree()
        self.assertIsNone(self.by_text(tree)["Solutions of common ODEs"]["agg"])
        self.map.move(ib, root)
        node = self.map.get_node(ib)
        self.assertEqual((node["kind"], node["parent_id"]), ("item", root))


class TestStatus(MapCase):
    def test_states_from_cards(self):
        self.map.import_outline(OUTLINE)
        n = self.by_text()
        solid = self.topic("Mohr", stability=60, reviewed_days_ago=1)      # R ≈ 0.99
        fading = self.topic("Buckling", stability=10, reviewed_days_ago=30)  # R ≈ 0.81
        self.map.link(n["Mohr's circle"]["id"], solid)
        self.map.link(n["Buckling failure"]["id"], fading)
        new = self.topic("Capacity")
        self.map.link(n["Cell capacity testing"]["id"], new)
        t = self.by_text()
        self.assertEqual(t["Mohr's circle"]["state"], "solid")
        self.assertEqual(t["Buckling failure"]["state"], "fading")
        self.assertEqual(t["Cell capacity testing"]["state"], "new")
        self.assertEqual(t["TTT/CCT diagrams"]["state"], "none")   # flagged, but no cards
        self.assertIsNone(t["Mechanics of Materials"]["state"])     # a heading
        agg = t["Mechanics of Materials"]["agg"]
        self.assertEqual(agg["counts"]["solid"], 1)
        self.assertEqual(agg["counts"]["fading"], 1)
        self.assertEqual(agg["counts"]["none"], 1)
        self.assertEqual(agg["total"], 3)
        self.assertIsNotNone(agg["last"])

    def test_flag_and_repeat_misses_make_it_shaky(self):
        a = self.map.add_node("Griffith cracks", flag=True)
        b = self.map.add_node("Lüders bands")
        la = self.topic("Griffith", stability=60, reviewed_days_ago=1)
        lb = self.topic("Luders", stability=60, reviewed_days_ago=1)
        self.repo.set_key_ideas(lb, ["upper yield point"])
        self.repo.db.execute("UPDATE key_ideas SET miss_streak = 2 WHERE learning_id = ?", (lb,))
        self.map.link(a, la)
        self.map.link(b, lb)
        t = self.by_text()
        self.assertEqual(t["Griffith cracks"]["state"], "shaky")
        self.assertEqual(t["Lüders bands"]["state"], "shaky")

    def test_branch_queue_only_serves_linked_topics(self):
        self.map.import_outline(OUTLINE)
        n = self.by_text()
        inside = self.topic("Mohr")
        outside = self.topic("Battery capacity")
        self.map.link(n["Mohr's circle"]["id"], inside)
        self.map.link(n["Cell capacity testing"]["id"], outside)
        ids = self.map.subtree_learning_ids(n["Mechanics of Materials"]["id"])
        self.assertEqual(ids, [inside])
        q = self.repo.get_due_questions(learning_ids=ids)
        self.assertEqual({x.learning_id for x in q}, {inside})
        self.assertEqual(self.repo.get_due_questions(learning_ids=[]), [])


class TestSuggest(MapCase):
    def test_word_overlap_pairs_unplaced_topics(self):
        self.map.import_outline(OUTLINE)
        lid = self.topic("Euler buckling failure of columns")
        self.topic("Something unrelated entirely")
        s = self.map.suggest()
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["learning_id"], lid)
        self.assertEqual(s[0]["path"][-1], "Buckling failure")
        self.map.link(s[0]["node_id"], lid)
        self.assertEqual(self.map.suggest(), [])   # placed topics drop out

    def test_people_are_never_offered(self):
        self.map.add_node("Buckling")
        lid = self.repo.create_learning("Buckling Bob", "met at the bay", subject="People")
        self.assertNotIn(lid, [s["learning_id"] for s in self.map.suggest()])



class TestStarterOutlines(unittest.TestCase):
    def test_bundled_outlines_parse_cleanly(self):
        from app.config import SEEDS_DIR
        files = sorted((SEEDS_DIR / "map").glob("*.txt"))
        self.assertTrue(files)
        for path in files:
            rows = parse_outline(path.read_text(encoding="utf-8"))
            self.assertGreater(len(rows), 20, path.name)
            self.assertEqual(rows[0]["depth"], 0)
            for prev, cur in zip(rows, rows[1:]):
                self.assertLessEqual(cur["depth"], prev["depth"] + 1, cur["text"])
            self.assertTrue(all(r["source"] for r in rows), "every item carries a source label")


if __name__ == "__main__":
    unittest.main()
