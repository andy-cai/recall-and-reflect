"""Privacy hardening + living person cards.

Covers: the People-name redaction pass, the cloud audit log, the per-topic
private flag (and its People invariants), person updates/associations, the
.env loader, the refine endpoint's cloud gate, and the LLM retry ladder
(empty-response and think-rejection). No network, no Ollama.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.config import load_dotenv
from app.db.database import Database
from app.db.repository import Repository
from app.services.cloud import CloudAssist, redact_people
from app.services.llm import LLMService, OllamaError, SubjectGuess, prompt_catalog


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db = Database(Path(self._tmp.name) / "test.db")
        db.initialize()
        self.repo = Repository(db=db)

    def tearDown(self):
        self._tmp.cleanup()


class TestRedaction(unittest.TestCase):
    def test_full_name_then_parts(self):
        text, n = redact_people("Priya Sharma found it; Priya fixed it.", ["Priya Sharma"])
        self.assertEqual(text, "[name] found it; [name] fixed it.")
        self.assertEqual(n, 2)

    def test_word_boundaries(self):
        # 'Priyanka' must survive a 'Priya' redaction
        text, n = redact_people("Priyanka and Priya disagree.", ["Priya Verma"])
        self.assertEqual(text, "Priyanka and [name] disagree.")
        self.assertEqual(n, 1)

    def test_case_sensitive_so_will_is_safe(self):
        text, n = redact_people("It will work; ask Will.", ["Will Chen"])
        self.assertEqual(text, "It will work; ask [name].")
        self.assertEqual(n, 1)

    def test_eponyms_not_in_people_are_untouched(self):
        s = "Hall-Petch and von Mises stay; $\\sigma_y$ too."
        text, n = redact_people(s, ["Priya Sharma"])
        self.assertEqual(text, s)
        self.assertEqual(n, 0)

    def test_short_fragments_skipped_but_full_name_replaced(self):
        text, n = redact_people("Al fixed the al dente bug. Al Wu signed off.", ["Al Wu"])
        self.assertIn("[name] signed off", text)      # full name replaced
        self.assertIn("Al fixed", text)               # 2-char fragment left alone
        self.assertEqual(n, 1)

    def test_possessive(self):
        text, n = redact_people("Priya's pack design.", ["Priya Sharma"])
        self.assertEqual(text, "[name]'s pack design.")
        self.assertEqual(n, 1)

    def test_empty_inputs(self):
        self.assertEqual(redact_people("", ["A B"]), ("", 0))
        self.assertEqual(redact_people("text", []), ("text", 0))


class TestCloudPrepareAndLog(RepoCase):
    def test_prepare_redacts_and_counts(self):
        cloud = CloudAssist()
        with mock.patch.object(CloudAssist, "_people_names", return_value=["Priya Sharma"]):
            contents = [{"role": "user", "parts": [{"text": "Priya Sharma suggested tin whiskers."}]}]
            out, chars, redacted = cloud._prepare(contents)
        self.assertEqual(out[0]["parts"][0]["text"], "[name] suggested tin whiskers.")
        self.assertEqual(redacted, 1)
        self.assertEqual(chars, len("[name] suggested tin whiskers."))

    def test_log_roundtrip_and_clear(self):
        self.repo.log_cloud("card rewrite", "gemini-2.5-flash", 412, 1, ok=True)
        self.repo.log_cloud("key ideas", "gemini-2.5-flash", 99, 0, ok=False, detail="rate limit")
        entries = self.repo.cloud_log_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["action"], "key ideas")   # newest first
        self.assertEqual(entries[0]["ok"], 0)
        self.assertEqual(entries[1]["redacted"], 1)
        self.assertEqual(self.repo.clear_cloud_log(), 2)
        self.assertEqual(self.repo.cloud_log_entries(), [])


class TestPrivateFlag(RepoCase):
    def test_people_are_private_by_construction(self):
        lid = self.repo.create_learning("Priya Sharma", "battery bay", subject="People")
        self.assertTrue(self.repo.get_learning(lid).private)

    def test_subject_change_to_people_sets_private(self):
        lid = self.repo.create_learning("Knee surgeon", "notes")
        self.assertFalse(self.repo.get_learning(lid).private)
        self.repo.set_subject(lid, "People")
        self.assertTrue(self.repo.get_learning(lid).private)

    def test_update_learning_can_set_and_clear(self):
        lid = self.repo.create_learning("Salary notes", "numbers")
        self.repo.update_learning(lid, "Salary notes", "numbers", private=True)
        self.assertTrue(self.repo.get_learning(lid).private)
        self.repo.update_learning(lid, "Salary notes", "numbers", private=False)
        self.assertFalse(self.repo.get_learning(lid).private)

    def test_people_names_lists_only_people(self):
        self.repo.create_learning("Priya Sharma", "x", subject="People")
        self.repo.create_learning("Hall-Petch relation", "x", subject="Mechanics")
        self.assertEqual(self.repo.people_names(), ["Priya Sharma"])

    def test_refine_endpoint_refuses_private_topics(self):
        from app.api import learnings as api_learnings
        lid = self.repo.create_learning("Salary notes", "numbers", private=True)
        qid = self.repo.create_question(lid, "q", "a")
        with mock.patch.object(api_learnings, "Repository", return_value=self.repo):
            resp = api_learnings.refine_card(qid, api_learnings.RefineReq(use_cloud=True))
        self.assertEqual(resp.status_code, 403)

    def test_refine_endpoint_refuses_people(self):
        from app.api import learnings as api_learnings
        lid = self.repo.create_learning("Priya Sharma", "story", subject="People")
        qid = self.repo.create_question(lid, "q", "a")
        with mock.patch.object(api_learnings, "Repository", return_value=self.repo):
            resp = api_learnings.refine_card(qid, api_learnings.RefineReq(use_cloud=True))
        self.assertEqual(resp.status_code, 403)


class TestLivingPersonCards(RepoCase):
    def _person(self):
        lid = self.repo.create_learning("Priya Sharma", "MFE battery bay\nFound the short",
                                        subject="People")
        qid = self.repo.create_question(
            lid, "MFE battery bay. Found the short. Who?",
            "Priya Sharma\nFound the short\n🧷 Your association: prying open the pack")
        return lid, qid

    def test_person_update_appends_dated_line_everywhere(self):
        lid, qid = self._person()
        self.repo.append_person_update(lid, "moved to the firmware team")
        learning = self.repo.get_learning(lid)
        card = self.repo.get_question(qid)
        self.assertRegex(learning.content, r"\n\d{4}-\d{2}-\d{2}: moved to the firmware team$")
        self.assertRegex(card.answer, r"\n\d{4}-\d{2}-\d{2}: moved to the firmware team$")

    def test_association_rework_replaces_old_line_and_pin_emoji(self):
        lid, qid = self._person()
        self.repo.set_person_association(lid, "Priya = prying the pack open")
        card = self.repo.get_question(qid)
        self.assertNotIn("🧷", card.answer)
        self.assertEqual(card.answer.count("Your association:"), 1)
        self.assertTrue(card.answer.endswith("Your association: Priya = prying the pack open"))
        self.assertEqual(self.repo.get_learning(lid).notes, "Priya = prying the pack open")

    def test_association_added_when_absent(self):
        lid = self.repo.create_learning("Sam Ode", "met at the fab", subject="People")
        qid = self.repo.create_question(lid, "Fab tour. Who?", "Sam Ode\nmet at the fab")
        self.repo.set_person_association(lid, "Ode = an ode to cleanrooms")
        self.assertTrue(self.repo.get_question(qid).answer.endswith(
            "Your association: Ode = an ode to cleanrooms"))


class TestDotenv(unittest.TestCase):
    def test_sets_missing_never_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text('# comment\nRR_TEST_NEW="abc123"\nRR_TEST_SET=changed\nbroken line\n',
                           encoding="utf-8")
            with mock.patch.dict("os.environ", {"RR_TEST_SET": "original"}, clear=False):
                load_dotenv(env)
                import os
                self.assertEqual(os.environ.get("RR_TEST_NEW"), "abc123")   # quotes stripped
                self.assertEqual(os.environ.get("RR_TEST_SET"), "original")  # env wins
        import os
        os.environ.pop("RR_TEST_NEW", None)

    def test_missing_file_is_fine(self):
        load_dotenv(Path("/nonexistent/.env"))   # must not raise

    def test_windows_encodings(self):
        """Notepad writes a UTF-8 BOM; PowerShell's `>` writes UTF-16.
        Both must still yield the key (and never crash startup)."""
        import os
        cases = {
            "RR_TEST_BOM": "GEMINI_TEST=bomval\n".encode("utf-8-sig"),
            "RR_TEST_U16": "GEMINI_TEST=u16val\n".encode("utf-16"),        # BOM'd, PS 5.1
            "RR_TEST_U16LE": "GEMINI_TEST=leval\n".encode("utf-16-le"),    # BOM-less
        }
        for label, raw in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                env = Path(tmp) / ".env"
                env.write_bytes(raw)
                os.environ.pop("GEMINI_TEST", None)
                load_dotenv(env)
                self.assertTrue(os.environ.get("GEMINI_TEST"), label)
        os.environ.pop("GEMINI_TEST", None)


class TestLLMRetryLadder(unittest.TestCase):
    """_complete_json must rescue capped calls: empty responses retry uncapped,
    and a rejected think option retries without it."""

    def setUp(self):
        self.llm = LLMService()
        self.msgs = [{"role": "user", "content": "x"}]

    def test_empty_response_retries_uncapped(self):
        calls = []

        def fake_once(model, messages, schema, temperature, num_predict, think=None):
            calls.append((num_predict, think))
            if num_predict:
                raise OllamaError("Empty response from model (possibly truncated by the token cap).")
            return SubjectGuess(subject="Mechanics")

        with mock.patch.object(LLMService, "resolve_model", return_value="m"), \
             mock.patch.object(LLMService, "_complete_json_once", side_effect=fake_once):
            out = self.llm._complete_json(self.msgs, SubjectGuess, num_predict=400, think=False)
        self.assertEqual(out.subject, "Mechanics")
        self.assertEqual(calls, [(400, False), (0, False)])   # retried uncapped, think kept

    def test_parse_failure_still_retries_uncapped(self):
        calls = []

        def fake_once(model, messages, schema, temperature, num_predict, think=None):
            calls.append(num_predict)
            if num_predict:
                raise OllamaError("Could not parse structured output (model output may be truncated).")
            return SubjectGuess(subject="ok")

        with mock.patch.object(LLMService, "resolve_model", return_value="m"), \
             mock.patch.object(LLMService, "_complete_json_once", side_effect=fake_once):
            self.llm._complete_json(self.msgs, SubjectGuess, num_predict=700)
        self.assertEqual(calls, [700, 0])

    def test_think_rejection_retries_without_think(self):
        calls = []

        def fake_once(model, messages, schema, temperature, num_predict, think=None):
            calls.append(think)
            if think is not None:
                raise OllamaError('Ollama request failed: "m" does not support thinking')
            return SubjectGuess(subject="ok")

        with mock.patch.object(LLMService, "resolve_model", return_value="m"), \
             mock.patch.object(LLMService, "_complete_json_once", side_effect=fake_once):
            self.llm._complete_json(self.msgs, SubjectGuess, num_predict=60, think=False)
        self.assertEqual(calls, [False, None])

    def test_other_errors_propagate(self):
        with mock.patch.object(LLMService, "resolve_model", return_value="m"), \
             mock.patch.object(LLMService, "_complete_json_once",
                               side_effect=OllamaError("connection refused")):
            with self.assertRaises(OllamaError):
                self.llm._complete_json(self.msgs, SubjectGuess, num_predict=400)


class TestPromptCatalog(unittest.TestCase):
    def test_catalog_is_complete_and_consistent(self):
        cat = prompt_catalog()
        ids = [p["id"] for p in cat]
        self.assertEqual(len(ids), len(set(ids)))
        for p in cat:
            self.assertTrue(p["system"].strip(), p["id"])
            self.assertIn(p["runs"], ("main", "fast"))
            self.assertIn(p["reasoning"], ("off", "default"))
        # grading never goes to the cloud
        for pid in ("grade", "rubric_grade"):
            entry = next(p for p in cat if p["id"] == pid)
            self.assertFalse(entry["cloud"])

    def test_sketch_clause_reached_the_prompts(self):
        cat = {p["id"]: p["system"] for p in prompt_catalog()}
        self.assertIn("Sketch", cat["cards"])
        self.assertIn("SKETCH", cat["rubric_grade"])
        self.assertIn("sketch task", cat["drill"])


if __name__ == "__main__":
    unittest.main()
