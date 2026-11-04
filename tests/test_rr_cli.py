"""tools/rr.py: the shell interface Claude Code uses. Privacy gates + logging.

Run: python -m unittest tests.test_rr_cli
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from app.db.database import Database
from app.db.repository import Repository

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import rr  # noqa: E402


class CliCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = Database(Path(self._tmp.name) / "test.db")
        db.initialize()
        self.repo = Repository(db=db)
        self.public = self.repo.create_learning("Mohr's circle", "Ask Priya Sharma about it")
        self.person = self.repo.create_learning("Priya Sharma", "battery bay", subject="People")
        self.secret = self.repo.create_learning("Salary negotiation", "x", private=True)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = rr.main(list(argv), ctx=rr.Ctx(self.repo))
        return code, buf.getvalue()

    def test_people_and_private_never_listed_and_names_redacted(self):
        code, out = self.run_cli("topics", "list")
        self.assertEqual(code, 0)
        self.assertIn("Mohr's circle", out)
        self.assertNotIn("Salary", out)
        self.assertNotIn("Priya", out)
        self.assertIn("2 People/Private topic(s) not shown", out)
        code, out = self.run_cli("topics", "show", str(self.person))
        self.assertEqual(code, 4)
        self.assertNotIn("battery bay", out)
        code, out = self.run_cli("topics", "show", str(self.public))
        self.assertIn("Ask [name] about it", out)

    def test_every_output_is_logged(self):
        self.run_cli("topics", "list")
        self.run_cli("map", "export")
        log = self.repo.cloud_log_entries()
        self.assertEqual({e["action"] for e in log}, {"rr CLI: topics list", "rr CLI: map export"})
        self.assertTrue(all(e["model"] == rr.LOG_MODEL for e in log))

    def test_apply_previews_unless_yes(self):
        f = Path(self._tmp.name) / "map.txt"
        f.write_text("Mechanics\n  Mohr's circle {topics:%d}\n" % self.public, encoding="utf-8")
        code, out = self.run_cli("map", "apply", str(f))
        self.assertIn("Preview only", out)
        self.assertEqual(self.repo.db.fetch_one("SELECT COUNT(*) n FROM map_nodes")["n"], 0)
        code, out = self.run_cli("map", "apply", str(f), "--yes")
        self.assertIn("Applied", out)
        self.assertEqual(self.repo.db.fetch_one("SELECT COUNT(*) n FROM map_links")["n"], 1)


if __name__ == "__main__":
    unittest.main()
