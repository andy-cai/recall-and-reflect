"""All database access. apply_review() owns the FSRS state transition."""

from datetime import datetime, timedelta
from typing import Optional

from app.config import DEFAULT_DAILY_TARGET, DEFAULT_DESIRED_RETENTION, DEFAULT_NEW_PER_DAY
from app.core.fsrs import CardState, Rating, ScheduleResult, State, retrievability, schedule
from app.db.database import Database, from_iso, get_database, to_iso
from app.db.models import Learning, Question


class Repository:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    # ---------- row mappers ----------

    @staticmethod
    def _question(row) -> Question:
        return Question(
            id=row["id"],
            learning_id=row["learning_id"],
            question=row["question"],
            answer=row["answer"],
            card_type=row["card_type"],
            cloze_source=row["cloze_source"],
            cloze_index=row["cloze_index"],
            stability=row["stability"],
            difficulty=row["difficulty"],
            state=row["state"],
            lapses=row["lapses"],
            last_reviewed_at=from_iso(row["last_reviewed_at"]),
            next_review_at=from_iso(row["next_review_at"]),
            suspended=bool(row["suspended"]),
            created_at=from_iso(row["created_at"]),
        )

    def _learning(self, row) -> Learning:
        return Learning(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            reflection=row["reflection"],
            subject=row["subject"],
            conversation=row["conversation"],
            notes=row["notes"],
            created_at=from_iso(row["created_at"]),
            is_active=bool(row["is_active"]),
            tags=self.get_tags_for_learning(row["id"]),
        )

    # ---------- learnings ----------

    def create_learning(
        self, title: str, content: str, reflection: Optional[str] = None,
        subject: Optional[str] = None, tags: Optional[list[str]] = None,
        conversation: Optional[str] = None,
    ) -> int:
        now = to_iso(datetime.now())
        lid = self.db.execute(
            "INSERT INTO learnings (title, content, reflection, subject, conversation, created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (title, content, reflection, (subject or None), (conversation or None), now),
        )
        if tags:
            self.set_learning_tags(lid, tags)
        return lid

    def create_recall_card(self, learning_id: int, title: str, content: str) -> int:
        """The default 'free recall' prompt for a topic — recall it in your own words."""
        question = f"Recall everything you can about: {title}"
        return self.create_question(
            learning_id=learning_id, question=question,
            answer=(content or "").strip(), card_type="recall",
        )

    def set_notes(self, learning_id: int, notes: Optional[str]) -> None:
        self.db.execute("UPDATE learnings SET notes = ? WHERE id = ?",
                        ((notes or None), learning_id))

    def set_card_due(self, question_id: int, next_at: datetime) -> None:
        """Pre-schedule a (still-new) card's first appearance — used to ease in bulk topics."""
        self.db.execute("UPDATE questions SET next_review_at = ? WHERE id = ?",
                        (to_iso(next_at), question_id))

    def get_learning(self, learning_id: int) -> Optional[Learning]:
        row = self.db.fetch_one("SELECT * FROM learnings WHERE id = ?", (learning_id,))
        return self._learning(row) if row else None

    def list_learnings(
        self, search: str = "", tag: Optional[str] = None, limit: int = 500
    ) -> list[dict]:
        clauses = ["l.is_active = 1"]
        params: list = []
        if search:
            clauses.append("(l.title LIKE ? OR l.content LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]
        if tag:
            clauses.append(
                "l.id IN (SELECT lt.learning_id FROM learning_tags lt "
                "JOIN tags t ON t.id = lt.tag_id WHERE t.name = ? COLLATE NOCASE)"
            )
            params.append(tag)
        where = " AND ".join(clauses)
        rows = self.db.fetch_all(
            f"""
            SELECT l.*,
                   (SELECT COUNT(*) FROM questions q WHERE q.learning_id = l.id) AS card_count,
                   (SELECT COUNT(*) FROM questions q WHERE q.learning_id = l.id
                        AND q.suspended = 0
                        AND (q.next_review_at IS NULL OR q.next_review_at <= ?)) AS due_count
            FROM learnings l
            WHERE {where}
            ORDER BY l.created_at DESC
            LIMIT ?
            """,
            (to_iso(datetime.now()), *params, limit),
        )
        out = []
        for row in rows:
            learning = self._learning(row)
            out.append({
                "learning": learning,
                "card_count": row["card_count"],
                "due_count": row["due_count"],
            })
        return out

    def update_learning(
        self, learning_id: int, title: str, content: str,
        reflection: Optional[str] = None, subject: Optional[str] = None,
        tags: Optional[list[str]] = None, notes: Optional[str] = None,
    ) -> None:
        self.db.execute(
            "UPDATE learnings SET title = ?, content = ?, reflection = ?, subject = ?, notes = ? WHERE id = ?",
            (title, content, reflection, (subject or None), (notes or None), learning_id),
        )
        if tags is not None:
            self.set_learning_tags(learning_id, tags)

    def set_subject(self, learning_id: int, subject: Optional[str]) -> None:
        self.db.execute(
            "UPDATE learnings SET subject = ? WHERE id = ?",
            ((subject or None), learning_id),
        )

    def delete_learning(self, learning_id: int) -> None:
        self.db.execute("DELETE FROM learnings WHERE id = ?", (learning_id,))

    # ---------- subjects ----------

    def subjects_summary(self) -> list[dict]:
        rows = self.db.fetch_all(
            """
            SELECT COALESCE(NULLIF(TRIM(l.subject), ''), '') AS subj,
                   COUNT(DISTINCT l.id) AS learnings,
                   COUNT(q.id) AS cards,
                   SUM(CASE WHEN q.suspended = 0
                         AND (q.next_review_at IS NULL OR q.next_review_at <= ?)
                       THEN 1 ELSE 0 END) AS due
            FROM learnings l
            LEFT JOIN questions q ON q.learning_id = l.id
            WHERE l.is_active = 1
            GROUP BY subj
            ORDER BY (subj = '') ASC, learnings DESC, subj COLLATE NOCASE
            """,
            (to_iso(datetime.now()),),
        )
        return [{"name": r["subj"], "learnings": r["learnings"],
                 "cards": r["cards"] or 0, "due": r["due"] or 0} for r in rows]

    def subject_names(self) -> list[str]:
        rows = self.db.fetch_all(
            "SELECT DISTINCT subject FROM learnings WHERE is_active = 1 "
            "AND subject IS NOT NULL AND TRIM(subject) <> '' ORDER BY subject COLLATE NOCASE"
        )
        return [r["subject"] for r in rows]

    def uncategorized_learnings(self) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT id, title, content FROM learnings WHERE is_active = 1 "
            "AND (subject IS NULL OR TRIM(subject) = '') ORDER BY created_at DESC"
        )
        return [{"id": r["id"], "title": r["title"], "content": r["content"]} for r in rows]

    # ---------- tags ----------

    def set_learning_tags(self, learning_id: int, tags: list[str]) -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM learning_tags WHERE learning_id = ?", (learning_id,))
            for name in {t.strip() for t in tags if t.strip()}:
                conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
                tag_id = conn.execute(
                    "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
                ).fetchone()["id"]
                conn.execute(
                    "INSERT OR IGNORE INTO learning_tags (learning_id, tag_id) VALUES (?, ?)",
                    (learning_id, tag_id),
                )
            conn.commit()

    def get_tags_for_learning(self, learning_id: int) -> list[str]:
        rows = self.db.fetch_all(
            "SELECT t.name FROM tags t JOIN learning_tags lt ON lt.tag_id = t.id "
            "WHERE lt.learning_id = ? ORDER BY t.name",
            (learning_id,),
        )
        return [r["name"] for r in rows]

    def all_tags(self) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT t.name, COUNT(lt.learning_id) AS n FROM tags t "
            "LEFT JOIN learning_tags lt ON lt.tag_id = t.id "
            "GROUP BY t.id ORDER BY n DESC, t.name"
        )
        return [{"name": r["name"], "count": r["n"]} for r in rows]

    # ---------- questions (cards) ----------

    def create_question(
        self, learning_id: int, question: str, answer: str, card_type: str = "basic",
        cloze_source: Optional[str] = None, cloze_index: Optional[int] = None,
    ) -> int:
        return self.db.execute(
            "INSERT INTO questions (learning_id, question, answer, card_type, "
            "cloze_source, cloze_index, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (learning_id, question, answer, card_type, cloze_source, cloze_index,
             to_iso(datetime.now())),
        )

    def get_question(self, question_id: int) -> Optional[Question]:
        row = self.db.fetch_one("SELECT * FROM questions WHERE id = ?", (question_id,))
        return self._question(row) if row else None

    def get_questions_for_learning(self, learning_id: int) -> list[Question]:
        rows = self.db.fetch_all(
            "SELECT * FROM questions WHERE learning_id = ? ORDER BY id", (learning_id,)
        )
        return [self._question(r) for r in rows]

    def update_question(self, question_id: int, question: str, answer: str) -> None:
        self.db.execute(
            "UPDATE questions SET question = ?, answer = ? WHERE id = ?",
            (question, answer, question_id),
        )

    def delete_question(self, question_id: int) -> None:
        self.db.execute("DELETE FROM questions WHERE id = ?", (question_id,))

    def set_suspended(self, question_id: int, suspended: bool) -> None:
        self.db.execute(
            "UPDATE questions SET suspended = ? WHERE id = ?",
            (1 if suspended else 0, question_id),
        )

    # ---------- review queue ----------

    def get_due_questions(
        self, limit: int = 200, tag: Optional[str] = None,
        learning_id: Optional[int] = None, subject: Optional[str] = None,
    ) -> list[Question]:
        """Build the review queue.

        Beyond filtering to due cards, the queue is *shaped*:
        - most-at-risk first (lowest current retrievability), new cards after;
        - at most one card per learning per fetch, so sessions interleave topics
          instead of running siblings back-to-back (the first sibling's answer
          would prime the rest);
        - new-card introductions are throttled by the new-per-day setting.
        Topic-scoped practice (learning_id) skips the shaping — you asked for
        exactly these cards.
        """
        now = datetime.now()
        clauses = [
            "q.suspended = 0",
            "l.is_active = 1",
            "(q.next_review_at IS NULL OR q.next_review_at <= ?)",
        ]
        params: list = [to_iso(now)]
        if subject is not None:
            if subject == "":
                clauses.append("(l.subject IS NULL OR TRIM(l.subject) = '')")
            else:
                clauses.append("l.subject = ? COLLATE NOCASE")
                params.append(subject)
        if tag:
            clauses.append(
                "q.learning_id IN (SELECT lt.learning_id FROM learning_tags lt "
                "JOIN tags t ON t.id = lt.tag_id WHERE t.name = ? COLLATE NOCASE)"
            )
            params.append(tag)
        if learning_id:
            clauses.append("q.learning_id = ?")
            params.append(learning_id)
        where = " AND ".join(clauses)
        rows = self.db.fetch_all(
            f"""
            SELECT q.* FROM questions q JOIN learnings l ON l.id = q.learning_id
            WHERE {where}
            ORDER BY q.next_review_at IS NULL, q.next_review_at ASC, q.id
            LIMIT 1000
            """,
            tuple(params),
        )
        pool = [self._question(r) for r in rows]
        if learning_id:
            return pool[:limit]

        def risk(q: Question) -> tuple:
            if q.state == int(State.NEW) or q.stability <= 0:
                return (1, 0.0)
            elapsed = 0.0
            if q.last_reviewed_at is not None:
                elapsed = (now - q.last_reviewed_at).total_seconds() / 86400
            return (0, retrievability(q.stability, elapsed))

        new_budget = max(0, self.get_new_per_day() - self.new_cards_today())
        seen_learnings: set[int] = set()
        out: list[Question] = []
        for q in sorted(pool, key=risk):
            if q.learning_id in seen_learnings:
                continue
            if q.state == int(State.NEW):
                if new_budget <= 0:
                    continue
                new_budget -= 1
            seen_learnings.add(q.learning_id)
            out.append(q)
            if len(out) >= limit:
                break
        return out

    def new_cards_today(self) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM reviews WHERE state_before = 0 "
            "AND date(reviewed_at) = date('now','localtime')"
        )
        return row["n"] if row else 0

    def at_risk_cards(self, n: int = 3) -> list[dict]:
        """The due cards closest to being forgotten (lowest retrievability),
        for the Today screen's 'about to slip' list."""
        now = datetime.now()
        rows = self.db.fetch_all(
            """
            SELECT q.id, q.question, q.card_type, q.stability, q.last_reviewed_at,
                   l.title, l.id AS lid
            FROM questions q JOIN learnings l ON l.id = q.learning_id
            WHERE q.suspended = 0 AND l.is_active = 1 AND q.state >= 1
              AND q.stability > 0 AND q.next_review_at IS NOT NULL
              AND q.next_review_at <= ?
            """,
            (to_iso(now),),
        )
        scored = []
        for r in rows:
            last = from_iso(r["last_reviewed_at"])
            elapsed = (now - last).total_seconds() / 86400 if last else 0.0
            scored.append({
                "question_id": r["id"],
                "learning_id": r["lid"],
                "label": r["title"] if r["card_type"] == "recall" else r["question"],
                "retrievability": round(retrievability(r["stability"], elapsed), 2),
            })
        scored.sort(key=lambda x: x["retrievability"])
        return scored[:n]

    def get_due_count(self) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM questions q JOIN learnings l ON l.id = q.learning_id "
            "WHERE q.suspended = 0 AND l.is_active = 1 "
            "AND (q.next_review_at IS NULL OR q.next_review_at <= ?)",
            (to_iso(datetime.now()),),
        )
        return row["n"] if row else 0

    # ---------- applying a review (FSRS transition) ----------

    def apply_review(
        self, q: Question, rating: int, recall_text: Optional[str] = None,
        confidence: Optional[int] = None, ai_verdict: Optional[str] = None,
        elapsed_ms: Optional[int] = None, bury_siblings: bool = True,
    ) -> ScheduleResult:
        now = datetime.now()
        card = CardState(
            state=State(q.state), stability=q.stability, difficulty=q.difficulty,
            lapses=q.lapses, last_reviewed_at=q.last_reviewed_at,
        )
        retention = self.get_desired_retention()
        # Hypercorrection follow-up: a confident miss is highly correctable, but the
        # correction itself decays — bring this card back a bit sooner than usual.
        if confidence == 3 and ai_verdict == "wrong":
            retention = min(0.97, retention + 0.04)
        result = schedule(card, Rating(rating), now, retention)

        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE questions SET stability = ?, difficulty = ?, state = ?, "
                "lapses = ?, last_reviewed_at = ?, next_review_at = ? WHERE id = ?",
                (result.stability, result.difficulty, int(result.state), result.lapses,
                 to_iso(now), to_iso(result.next_review_at), q.id),
            )
            conn.execute(
                """
                INSERT INTO reviews (
                    question_id, rating, reviewed_at, recall_text, confidence, ai_verdict,
                    stability_before, difficulty_before, state_before, next_review_before,
                    lapses_before, last_reviewed_before,
                    stability_after, difficulty_after, state_after, next_review_after,
                    lapses_after, interval_after, elapsed_ms
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    q.id, rating, to_iso(now), recall_text, confidence, ai_verdict,
                    q.stability, q.difficulty, q.state, to_iso(q.next_review_at),
                    q.lapses, to_iso(q.last_reviewed_at),
                    result.stability, result.difficulty, int(result.state),
                    to_iso(result.next_review_at), result.lapses, result.interval_days,
                    elapsed_ms,
                ),
            )
            conn.commit()
        if bury_siblings:
            self._bury_siblings(q, now)
        return result

    def _bury_siblings(self, q: Question, now: datetime) -> None:
        """Push the learning's other due cards to tomorrow morning so siblings
        never run in the same session (the first answer primes the rest)."""
        tomorrow = (now + timedelta(days=1)).replace(hour=4, minute=0, second=0, microsecond=0)
        self.db.execute(
            "UPDATE questions SET next_review_at = ? WHERE learning_id = ? AND id != ? "
            "AND suspended = 0 AND (next_review_at IS NULL OR next_review_at <= ?)",
            (to_iso(tomorrow), q.learning_id, q.id, to_iso(now)),
        )

    def undo_last_review(self) -> Optional[int]:
        row = self.db.fetch_one("SELECT * FROM reviews ORDER BY id DESC LIMIT 1")
        if not row:
            return None
        qid = row["question_id"]
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE questions SET stability = ?, difficulty = ?, state = ?, "
                "lapses = ?, next_review_at = ?, last_reviewed_at = ? WHERE id = ?",
                (row["stability_before"], row["difficulty_before"], row["state_before"],
                 row["lapses_before"], row["next_review_before"],
                 row["last_reviewed_before"], qid),
            )
            conn.execute("DELETE FROM reviews WHERE id = ?", (row["id"],))
            conn.commit()
        return qid

    # ---------- stats ----------

    def reviews_today(self) -> int:
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS n FROM reviews WHERE date(reviewed_at) = date('now','localtime')"
        )
        return row["n"] if row else 0

    def total_counts(self) -> dict:
        learnings = self.db.fetch_one("SELECT COUNT(*) AS n FROM learnings WHERE is_active=1")["n"]
        cards = self.db.fetch_one("SELECT COUNT(*) AS n FROM questions")["n"]
        reviews = self.db.fetch_one("SELECT COUNT(*) AS n FROM reviews")["n"]
        return {"learnings": learnings, "cards": cards, "reviews": reviews}

    def reviews_by_day(self, days: int = 365) -> dict[str, int]:
        start = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.db.fetch_all(
            "SELECT date(reviewed_at) AS d, COUNT(*) AS n FROM reviews "
            "WHERE reviewed_at >= ? GROUP BY d ORDER BY d",
            (start,),
        )
        return {r["d"]: r["n"] for r in rows}

    def activity_by_day(self, days: int = 365) -> dict[str, int]:
        """Reviews + captures per day. The habit is 'engage with memory' —
        a day spent reflecting counts as showing up, not as a dead day."""
        out = dict(self.reviews_by_day(days))
        start = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.db.fetch_all(
            "SELECT date(created_at) AS d, COUNT(*) AS n FROM learnings "
            "WHERE created_at >= ? GROUP BY d ORDER BY d",
            (start,),
        )
        for r in rows:
            out[r["d"]] = out.get(r["d"], 0) + r["n"]
        return out

    def retention_rate(self, days: int = 30) -> Optional[float]:
        """Fraction of mature-ish reviews (card was already in REVIEW state) passed."""
        start = (datetime.now() - timedelta(days=days)).isoformat()
        row = self.db.fetch_one(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN rating > 1 THEN 1 ELSE 0 END) AS passed "
            "FROM reviews WHERE reviewed_at >= ? AND state_before = 2",
            (start,),
        )
        if not row or not row["total"]:
            return None
        return row["passed"] / row["total"]

    def maturity_breakdown(self) -> dict[str, int]:
        rows = self.db.fetch_all("SELECT state, stability FROM questions WHERE suspended = 0")
        out = {"new": 0, "learning": 0, "young": 0, "mature": 0}
        for r in rows:
            st = r["state"]
            if st == State.NEW:
                out["new"] += 1
            elif st in (State.LEARNING, State.RELEARNING):
                out["learning"] += 1
            elif (r["stability"] or 0) >= 21:
                out["mature"] += 1
            else:
                out["young"] += 1
        return out

    def due_forecast(self, days: int = 14) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT date(next_review_at) AS d, COUNT(*) AS n FROM questions "
            "WHERE suspended = 0 AND next_review_at IS NOT NULL "
            "AND date(next_review_at) <= date('now','localtime','+' || ? || ' days') "
            "GROUP BY d ORDER BY d",
            (days,),
        )
        return [{"date": r["d"], "count": r["n"]} for r in rows]

    # ---------- settings ----------

    def get_setting(self, key: str, default=None):
        row = self.db.fetch_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def get_daily_target(self) -> int:
        try:
            return int(self.get_setting("daily_target", DEFAULT_DAILY_TARGET))
        except (TypeError, ValueError):
            return DEFAULT_DAILY_TARGET

    def get_desired_retention(self) -> float:
        try:
            return float(self.get_setting("desired_retention", DEFAULT_DESIRED_RETENTION))
        except (TypeError, ValueError):
            return DEFAULT_DESIRED_RETENTION

    def get_new_per_day(self) -> int:
        try:
            return int(self.get_setting("new_per_day", DEFAULT_NEW_PER_DAY))
        except (TypeError, ValueError):
            return DEFAULT_NEW_PER_DAY
