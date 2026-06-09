"""Local embeddings for topics (Ollama nomic-embed-text).

Powers related-concepts, contrast-card suggestions, semantic search, capture
connection chips, and duplicate detection. Vectors live in SQLite next to the
notes; everything is computed on-device. Every call degrades gracefully: if
the embed model is missing, callers just see empty results.
"""

import hashlib
import json
import math
from datetime import datetime
from typing import Optional

from app.config import EMBED_MODEL, OLLAMA_BASE_URL, OLLAMA_CONNECT_TIMEOUT, OLLAMA_TIMEOUT
from app.db.database import Database, get_database, to_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    learning_id INTEGER PRIMARY KEY REFERENCES learnings(id) ON DELETE CASCADE,
    vector TEXT NOT NULL,          -- JSON array of floats
    text_hash TEXT NOT NULL,       -- sha1 of the embedded text; stale when it differs
    updated_at TEXT NOT NULL
);
"""


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _text_for(title: str, content: str) -> str:
    return f"{title}\n{(content or '')[:1500]}".strip()


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class EmbeddingService:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
        with self.db.get_connection() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    # ---------- model ----------

    def model_available(self) -> bool:
        try:
            import httpx
            with httpx.Client(timeout=OLLAMA_CONNECT_TIMEOUT) as client:
                resp = client.get(f"{OLLAMA_BASE_URL}/api/tags")
                resp.raise_for_status()
                names = [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            return False
        return any(n.split(":")[0] == EMBED_MODEL for n in names)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch; returns [] on any failure (callers degrade gracefully)."""
        if not texts:
            return []
        try:
            import httpx
            with httpx.Client(timeout=OLLAMA_TIMEOUT) as client:
                resp = client.post(
                    f"{OLLAMA_BASE_URL}/api/embed",
                    json={"model": EMBED_MODEL, "input": texts},
                )
                resp.raise_for_status()
                vectors = resp.json().get("embeddings", [])
        except Exception:
            return []
        return vectors if len(vectors) == len(texts) else []

    # ---------- storage ----------

    def store(self, learning_id: int, vector: list[float], text_hash: str) -> None:
        self.db.execute(
            "INSERT INTO embeddings (learning_id, vector, text_hash, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(learning_id) DO UPDATE SET "
            "vector = excluded.vector, text_hash = excluded.text_hash, "
            "updated_at = excluded.updated_at",
            (learning_id, json.dumps(vector), text_hash, to_iso(datetime.now())),
        )

    def get_vector(self, learning_id: int) -> Optional[list[float]]:
        row = self.db.fetch_one(
            "SELECT vector FROM embeddings WHERE learning_id = ?", (learning_id,))
        return json.loads(row["vector"]) if row else None

    def all_vectors(self, exclude: Optional[int] = None) -> list[tuple[int, list[float]]]:
        rows = self.db.fetch_all(
            "SELECT e.learning_id, e.vector FROM embeddings e "
            "JOIN learnings l ON l.id = e.learning_id WHERE l.is_active = 1")
        return [(r["learning_id"], json.loads(r["vector"]))
                for r in rows if r["learning_id"] != exclude]

    # ---------- maintenance ----------

    def ensure(self, learning_id: int, title: str, content: str) -> bool:
        """Embed (or re-embed) one topic if its text changed. Returns success."""
        text = _text_for(title, content)
        h = _hash(text)
        row = self.db.fetch_one(
            "SELECT text_hash FROM embeddings WHERE learning_id = ?", (learning_id,))
        if row and row["text_hash"] == h:
            return True
        vectors = self.embed_texts([text])
        if not vectors:
            return False
        self.store(learning_id, vectors[0], h)
        return True

    def backfill(self, batch: int = 24) -> int:
        """Embed up to `batch` topics that have no (or stale) vectors."""
        rows = self.db.fetch_all(
            """
            SELECT l.id, l.title, l.content, e.text_hash
            FROM learnings l LEFT JOIN embeddings e ON e.learning_id = l.id
            WHERE l.is_active = 1
            ORDER BY (e.learning_id IS NULL) DESC, l.created_at DESC
            """)
        todo = []
        for r in rows:
            text = _text_for(r["title"], r["content"])
            if r["text_hash"] != _hash(text):
                todo.append((r["id"], text))
            if len(todo) >= batch:
                break
        if not todo:
            return 0
        vectors = self.embed_texts([t for _, t in todo])
        if not vectors:
            return 0
        for (lid, text), vec in zip(todo, vectors):
            self.store(lid, vec, _hash(text))
        return len(todo)

    # ---------- queries ----------

    def nearest(self, learning_id: int, k: int = 5, floor: float = 0.55) -> list[dict]:
        vec = self.get_vector(learning_id)
        if not vec:
            return []
        scored = [(lid, cosine(vec, v)) for lid, v in self.all_vectors(exclude=learning_id)]
        scored = [(lid, s) for lid, s in scored if s >= floor]
        scored.sort(key=lambda x: -x[1])
        return [{"learning_id": lid, "score": round(s, 3)} for lid, s in scored[:k]]

    def nearest_to_text(self, text: str, k: int = 5, floor: float = 0.5,
                        exclude: Optional[int] = None) -> list[dict]:
        vectors = self.embed_texts([text[:1500]])
        if not vectors:
            return []
        vec = vectors[0]
        scored = [(lid, cosine(vec, v)) for lid, v in self.all_vectors(exclude=exclude)]
        scored = [(lid, s) for lid, s in scored if s >= floor]
        scored.sort(key=lambda x: -x[1])
        return [{"learning_id": lid, "score": round(s, 3)} for lid, s in scored[:k]]


_service: Optional[EmbeddingService] = None


def get_embeddings() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
