"""SQLite connection + schema.

Datetimes are stored as ISO-8601 TEXT (not via sqlite's implicit datetime
adapters, which are deprecated in modern Python) and parsed explicitly.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    reflection TEXT,                       -- elaboration captured during the chat
    subject TEXT,                          -- primary area / project (a note's "home")
    conversation TEXT,                     -- raw capture transcript (JSON)
    notes TEXT,                            -- free notes added over time
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id INTEGER NOT NULL REFERENCES learnings(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    card_type TEXT NOT NULL DEFAULT 'basic',  -- 'basic' | 'cloze'
    cloze_source TEXT,
    cloze_index INTEGER,

    stability REAL NOT NULL DEFAULT 0,
    difficulty REAL NOT NULL DEFAULT 0,
    state INTEGER NOT NULL DEFAULT 0,         -- fsrs.State
    lapses INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at TEXT,
    next_review_at TEXT,

    suspended INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,

    recall_text TEXT,                         -- what the user typed (free recall)
    confidence INTEGER,                       -- 1 guessing .. 3 sure
    ai_verdict TEXT,                          -- 'correct' | 'partial' | 'wrong'

    stability_before REAL, difficulty_before REAL, state_before INTEGER,
    next_review_before TEXT, lapses_before INTEGER, last_reviewed_before TEXT,
    stability_after REAL, difficulty_after REAL, state_after INTEGER,
    next_review_after TEXT, lapses_after INTEGER, interval_after INTEGER,
    elapsed_ms INTEGER
);

CREATE TABLE IF NOT EXISTS key_ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id INTEGER NOT NULL REFERENCES learnings(id) ON DELETE CASCADE,
    idea TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 0,                -- times recalled at review
    misses INTEGER NOT NULL DEFAULT 0,
    miss_streak INTEGER NOT NULL DEFAULT 0,         -- consecutive misses; 2 spawns a drill card
    drilled INTEGER NOT NULL DEFAULT 0,             -- a drill card was already created
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS learning_tags (
    learning_id INTEGER NOT NULL REFERENCES learnings(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (learning_id, tag_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_key_ideas_learning ON key_ideas(learning_id);
CREATE INDEX IF NOT EXISTS idx_questions_learning ON questions(learning_id);
CREATE INDEX IF NOT EXISTS idx_questions_next_review ON questions(next_review_at);
CREATE INDEX IF NOT EXISTS idx_reviews_question ON reviews(question_id);
CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(reviewed_at);
"""


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def from_iso(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip().replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.get_connection() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.commit()

    @staticmethod
    def _migrate(conn) -> None:
        """Idempotent, additive migrations for DBs created by older schemas."""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(learnings)")}
        if "subject" not in cols:
            conn.execute("ALTER TABLE learnings ADD COLUMN subject TEXT")
        if "conversation" not in cols:
            conn.execute("ALTER TABLE learnings ADD COLUMN conversation TEXT")
        if "notes" not in cols:
            conn.execute("ALTER TABLE learnings ADD COLUMN notes TEXT")
        rcols = {r["name"] for r in conn.execute("PRAGMA table_info(reviews)")}
        if "idea_results" not in rcols:
            # per-idea rubric outcomes for recall cards, JSON: [{"id":..,"result":"hit|partial|miss"}]
            conn.execute("ALTER TABLE reviews ADD COLUMN idea_results TEXT")

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def execute(self, query: str, params: tuple = ()) -> int:
        with self.get_connection() as conn:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(query, params).fetchone()

    def fetch_all(self, query: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(query, params).fetchall()


_database: Optional[Database] = None


def get_database() -> Database:
    global _database
    if _database is None:
        _database = Database()
        _database.initialize()
    return _database
