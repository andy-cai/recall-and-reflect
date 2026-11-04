"""The knowledge map: an editable outline of the areas you want to keep.

Each node can link to topics (learnings). A node's status is computed from its
topics' cards (FSRS retrievability, repeated misses), so the map can't go stale
the way a hand-highlighted outline does:

    none   no cards behind it yet
    new    cards exist but none reviewed yet
    shaky  recall chance < 60%, an idea missed twice running, or flagged by you
    fading recall chance 60–85%
    solid  recall chance ≥ 85%

Headings (nodes with children and no links of their own) carry no status; they
aggregate their subtree.
"""

import re
from collections import defaultdict
from datetime import datetime
from typing import Optional

from app.core.fsrs import retrievability
from app.db.database import Database, from_iso, get_database, to_iso

SOLID_R = 0.85
SHAKY_R = 0.60
STATES = ("solid", "fading", "shaky", "new", "none")

# Bullet glyphs OneNote / Word / Markdown put in front of outline lines.
_BULLET = re.compile(r"^(?:[-*+•◦▪▫■□○●◆◇►▸➢→·]|\d+[.)]|[a-zA-Z][.)](?=\s))\s*")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "and", "for", "with", "from", "into", "vs", "of", "to", "in", "on", "a", "an",
    "its", "how", "what", "why", "etc", "using", "via", "their", "basic", "basics", "more",
    "other", "different", "types", "type", "analysis", "theory", "methods", "method",
}


def _tokens(text: str) -> set[str]:
    out = set()
    for w in _WORD.findall((text or "").lower()):
        if len(w) < 3 or w in _STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def _dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def parse_outline(text: str) -> list[dict]:
    """Indented text -> [{depth, text, flag, source}].

    - Indentation (spaces or tabs) sets depth; bullet glyphs are stripped.
    - A line starting or ending with "!" is flagged "lacking understanding".
    - A line "## Label" is not a node: it sets the source label for what follows.
    """
    rows: list[dict] = []
    indents: list[int] = []
    source: Optional[str] = None
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        stripped = raw.lstrip(" \t")
        if stripped.startswith("## "):
            source = stripped[3:].strip() or None
            indents = []
            continue
        lead = raw[: len(raw) - len(stripped)]
        indent = sum(4 if c == "\t" else 1 for c in lead)
        body = _BULLET.sub("", stripped).strip()
        flag = False
        if body.startswith("!"):
            flag, body = True, body[1:].strip()
        if body.endswith(" !") or body.endswith("(!)"):
            flag, body = True, body.rstrip("!() ").strip()
        if not body:
            continue
        while indents and indents[-1] >= indent:
            indents.pop()
        depth = len(indents)
        indents.append(indent)
        rows.append({"depth": depth, "text": body, "flag": flag, "source": source})
    return rows


class MapStore:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()

    # ---------- reads ----------

    def _nodes(self) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT id, parent_id, position, text, kind, source, flag FROM map_nodes "
            "ORDER BY position, id")
        return [dict(r) for r in rows]

    def get_node(self, node_id: int) -> Optional[dict]:
        r = self.db.fetch_one("SELECT * FROM map_nodes WHERE id = ?", (node_id,))
        return dict(r) if r else None

    def subtree_ids(self, node_id: int) -> list[int]:
        rows = self.db.fetch_all(
            """WITH RECURSIVE sub(id) AS (
                 SELECT ? UNION ALL
                 SELECT n.id FROM map_nodes n JOIN sub ON n.parent_id = sub.id)
               SELECT id FROM sub""", (node_id,))
        return [r["id"] for r in rows]

    def subtree_learning_ids(self, node_id: int) -> list[int]:
        ids = self.subtree_ids(node_id)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self.db.fetch_all(
            f"SELECT DISTINCT ml.learning_id FROM map_links ml JOIN learnings l "
            f"ON l.id = ml.learning_id WHERE l.is_active = 1 AND ml.node_id IN ({marks})",
            tuple(ids))
        return [r["learning_id"] for r in rows]

    def path(self, node_id: int) -> list[str]:
        by_id = {n["id"]: n for n in self._nodes()}
        out, cur, guard = [], by_id.get(node_id), 0
        while cur and guard < 64:
            out.append(cur["text"])
            cur = by_id.get(cur["parent_id"])
            guard += 1
        return list(reversed(out))

    def nodes_for_learning(self, learning_id: int) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT node_id FROM map_links WHERE learning_id = ?", (learning_id,))
        return [{"id": r["node_id"], "path": self.path(r["node_id"])} for r in rows]

    def tree(self, now: Optional[datetime] = None) -> dict:
        """Every node with its own status and its subtree's aggregate.

        Returned flat (parent_id + position) so the client can fold it however
        it likes; aggregates are computed here so they stay testable.
        """
        now = now or datetime.now()
        nodes = self._nodes()
        links: dict[int, list[int]] = defaultdict(list)
        for r in self.db.fetch_all(
                "SELECT ml.node_id, ml.learning_id FROM map_links ml JOIN learnings l "
                "ON l.id = ml.learning_id WHERE l.is_active = 1"):
            links[r["node_id"]].append(r["learning_id"])

        linked = {lid for ls in links.values() for lid in ls}
        per_learning: dict[int, dict] = {lid: {"rs": [], "cards": 0, "due": 0, "last": None}
                                         for lid in linked}
        titles: dict[int, str] = {}
        shaky_ideas: set[int] = set()
        if linked:
            marks = ",".join("?" * len(linked))
            ids = tuple(linked)
            for r in self.db.fetch_all(
                    f"SELECT id, title FROM learnings WHERE id IN ({marks})", ids):
                titles[r["id"]] = r["title"]
            for r in self.db.fetch_all(
                    f"SELECT learning_id, state, stability, last_reviewed_at, next_review_at "
                    f"FROM questions WHERE suspended = 0 AND learning_id IN ({marks})", ids):
                agg = per_learning[r["learning_id"]]
                agg["cards"] += 1
                nxt = from_iso(r["next_review_at"])
                if nxt is None or nxt <= now:
                    agg["due"] += 1
                last = from_iso(r["last_reviewed_at"])
                if r["state"] >= 1 and r["stability"] > 0 and last is not None:
                    elapsed = max(0.0, (now - last).total_seconds() / 86400)
                    agg["rs"].append(retrievability(r["stability"], elapsed))
                    if agg["last"] is None or last > agg["last"]:
                        agg["last"] = last
            for r in self.db.fetch_all(
                    f"SELECT DISTINCT learning_id FROM key_ideas WHERE miss_streak >= 2 "
                    f"AND learning_id IN ({marks})", ids):
                shaky_ideas.add(r["learning_id"])

        children: dict[Optional[int], list[int]] = defaultdict(list)
        for n in nodes:
            if n["kind"] == "item":
                children[n["parent_id"]].append(n["id"])

        out: dict[int, dict] = {}
        for n in nodes:
            lids = links.get(n["id"], [])
            rs, cards, due, last = [], 0, 0, None
            for lid in lids:
                a = per_learning[lid]
                rs += a["rs"]
                cards += a["cards"]
                due += a["due"]
                if a["last"] and (last is None or a["last"] > last):
                    last = a["last"]
            r = sum(rs) / len(rs) if rs else None
            has_kids = bool(children.get(n["id"]))
            if not lids and has_kids:
                state = None                      # a heading: aggregates only
            elif cards == 0:
                state = "none"
            elif r is None:
                state = "shaky" if n["flag"] else "new"
            elif n["flag"] or r < SHAKY_R or any(l in shaky_ideas for l in lids):
                state = "shaky"
            elif r < SOLID_R:
                state = "fading"
            else:
                state = "solid"
            out[n["id"]] = {
                **n, "flag": bool(n["flag"]), "learning_ids": lids,
                "state": state, "r": round(r, 3) if r is not None else None,
                "cards": cards, "due": due, "last": last,
            }

        # aggregate bottom-up (post-order over the item tree)
        def walk(nid: int) -> tuple[dict, Optional[datetime], int]:
            node = out[nid]
            counts = {s: 0 for s in STATES}
            if node["state"]:
                counts[node["state"]] += 1
            last, due = node["last"], node["due"]
            for cid in children.get(nid, []):
                c_counts, c_last, c_due = walk(cid)
                for s in STATES:
                    counts[s] += c_counts[s]
                if c_last and (last is None or c_last > last):
                    last = c_last
                due += c_due
            node["agg"] = {"counts": counts, "total": sum(counts.values()),
                           "last": to_iso(last), "due": due}
            return counts, last, due

        for rid in children.get(None, []):
            walk(rid)
        for node in out.values():
            node["last"] = to_iso(node["last"])
            node.setdefault("agg", None)
        return {"nodes": list(out.values()), "titles": {str(k): v for k, v in titles.items()},
                "sources": sorted({n["source"] for n in nodes if n["source"]}, key=str.lower)}

    # ---------- writes ----------

    def _siblings(self, conn, parent_id: Optional[int], kind: str = "item") -> list[int]:
        if parent_id is None:
            rows = conn.execute(
                "SELECT id FROM map_nodes WHERE parent_id IS NULL AND kind = ? "
                "ORDER BY position, id", (kind,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM map_nodes WHERE parent_id = ? ORDER BY position, id",
                (parent_id,)).fetchall()
        return [r["id"] for r in rows]

    @staticmethod
    def _write_order(conn, ids: list[int]) -> None:
        for i, nid in enumerate(ids):
            conn.execute("UPDATE map_nodes SET position = ? WHERE id = ?", (i, nid))

    def add_node(self, text: str, parent_id: Optional[int] = None,
                 after_id: Optional[int] = None, kind: str = "item",
                 source: Optional[str] = None, flag: bool = False) -> int:
        text = (text or "").strip()
        kind = "inbox" if kind == "inbox" else "item"
        with self.db.get_connection() as conn:
            if after_id is not None:
                row = conn.execute("SELECT parent_id, kind, source FROM map_nodes WHERE id = ?",
                                   (after_id,)).fetchone()
                if row:
                    parent_id, kind = row["parent_id"], row["kind"]
                    source = source if source is not None else row["source"]
            if kind == "inbox":
                parent_id = None
            if parent_id is not None and source is None:
                row = conn.execute("SELECT source FROM map_nodes WHERE id = ?",
                                   (parent_id,)).fetchone()
                source = row["source"] if row else None
            sibs = self._siblings(conn, parent_id, kind)
            cur = conn.execute(
                "INSERT INTO map_nodes (parent_id, position, text, kind, source, flag, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (parent_id, len(sibs), text, kind, source, 1 if flag else 0,
                 to_iso(datetime.now())))
            nid = cur.lastrowid
            if after_id is not None and after_id in sibs:
                sibs.insert(sibs.index(after_id) + 1, nid)
                self._write_order(conn, sibs)
            conn.commit()
            return nid

    def update_node(self, node_id: int, text: Optional[str] = None,
                    flag: Optional[bool] = None, source: Optional[str] = None) -> None:
        sets, params = [], []
        if text is not None:
            sets.append("text = ?"); params.append(text.strip())
        if flag is not None:
            sets.append("flag = ?"); params.append(1 if flag else 0)
        if source is not None:
            sets.append("source = ?"); params.append(source.strip() or None)
        if sets:
            self.db.execute(f"UPDATE map_nodes SET {', '.join(sets)} WHERE id = ?",
                            (*params, node_id))

    def delete_node(self, node_id: int) -> int:
        """Delete a node and everything under it. Topics are untouched."""
        n = len(self.subtree_ids(node_id))
        self.db.execute("DELETE FROM map_nodes WHERE id = ?", (node_id,))
        return n

    def move(self, node_id: int, parent_id: Optional[int], index: Optional[int] = None) -> bool:
        """Re-parent (or reorder) a node; refuses to move a node under itself."""
        if parent_id is not None and parent_id in self.subtree_ids(node_id):
            return False
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT parent_id, kind FROM map_nodes WHERE id = ?",
                               (node_id,)).fetchone()
            if not row:
                return False
            old = self._siblings(conn, row["parent_id"], row["kind"])
            if node_id in old:
                old.remove(node_id)
                self._write_order(conn, old)
            src = None
            if parent_id is not None:
                prow = conn.execute("SELECT source FROM map_nodes WHERE id = ?",
                                    (parent_id,)).fetchone()
                src = prow["source"] if prow else None
            conn.execute("UPDATE map_nodes SET parent_id = ?, kind = 'item', "
                         "source = COALESCE(?, source) WHERE id = ?", (parent_id, src, node_id))
            sibs = [s for s in self._siblings(conn, parent_id, "item") if s != node_id]
            at = len(sibs) if index is None else max(0, min(index, len(sibs)))
            sibs.insert(at, node_id)
            self._write_order(conn, sibs)
            conn.commit()
            return True

    def shift(self, node_id: int, op: str) -> bool:
        """Keyboard outline ops: indent, outdent, up, down."""
        node = self.get_node(node_id)
        if not node or node["kind"] != "item":
            return False
        with self.db.get_connection() as conn:
            sibs = self._siblings(conn, node["parent_id"], "item")
        i = sibs.index(node_id)
        if op == "indent":
            return i > 0 and self.move(node_id, sibs[i - 1], None)
        if op == "outdent":
            parent = self.get_node(node["parent_id"]) if node["parent_id"] else None
            if not parent:
                return False
            with self.db.get_connection() as conn:
                psibs = self._siblings(conn, parent["parent_id"], "item")
            return self.move(node_id, parent["parent_id"], psibs.index(parent["id"]) + 1)
        if op in ("up", "down"):
            j = i - 1 if op == "up" else i + 1
            if not 0 <= j < len(sibs):
                return False
            sibs[i], sibs[j] = sibs[j], sibs[i]
            with self.db.get_connection() as conn:
                self._write_order(conn, sibs)
                conn.commit()
            return True
        return False

    def link(self, node_id: int, learning_id: int) -> None:
        self.db.execute("INSERT OR IGNORE INTO map_links (node_id, learning_id) VALUES (?, ?)",
                        (node_id, learning_id))

    def unlink(self, node_id: int, learning_id: int) -> None:
        self.db.execute("DELETE FROM map_links WHERE node_id = ? AND learning_id = ?",
                        (node_id, learning_id))

    def import_outline(self, text: str, parent_id: Optional[int] = None) -> int:
        """Append an indented outline under parent_id (or at the root)."""
        rows = parse_outline(text)
        stack: list[int] = []          # stack[d] = id of the latest node at depth d
        n = 0
        for row in rows:
            depth = min(row["depth"], len(stack))
            stack = stack[:depth]
            parent = stack[-1] if stack else parent_id
            nid = self.add_node(row["text"], parent_id=parent, source=row["source"],
                                flag=row["flag"])
            stack.append(nid)
            n += 1
        return n

    # ---------- matching (topics <-> nodes) ----------

    def _leafish(self) -> list[dict]:
        """Nodes that can carry topics: leaves, plus any node already linked."""
        nodes = [n for n in self._nodes() if n["kind"] == "item"]
        parents = {n["parent_id"] for n in nodes}
        linked = {r["node_id"] for r in self.db.fetch_all("SELECT DISTINCT node_id FROM map_links")}
        return [n for n in nodes if n["id"] not in parents or n["id"] in linked]

    def unplaced_learnings(self, limit: int = 50) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT id, title, subject FROM learnings WHERE is_active = 1 "
            "AND LOWER(TRIM(COALESCE(subject,''))) <> 'people' "
            "AND id NOT IN (SELECT learning_id FROM map_links) "
            "ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def suggest(self, vectors: Optional[dict] = None, embed=None,
                floor: float = 0.4, emb_floor: float = 0.72) -> list[dict]:
        """Pair unplaced topics with their best map node.

        Word overlap (Dice on content words) always; embeddings when an embed
        model is running (`vectors` = learning_id -> vector, `embed` = texts ->
        vectors). Suggestions only — the person confirms each one.
        """
        nodes = self._leafish()
        topics = self.unplaced_learnings(limit=400)
        if not nodes or not topics:
            return []
        by_id = {n["id"]: n for n in self._nodes()}

        def ctx(n: dict) -> str:
            parent = by_id.get(n["parent_id"])
            return f"{parent['text']} — {n['text']}" if parent else n["text"]

        node_tokens = {n["id"]: _tokens(n["text"]) for n in nodes}
        node_vecs: dict[int, list[float]] = {}
        if vectors and embed:
            try:
                vecs = embed([ctx(n) for n in nodes])
                node_vecs = {n["id"]: v for n, v in zip(nodes, vecs or []) if v}
            except Exception:
                node_vecs = {}

        from app.services.embeddings import cosine  # local import: no cycle at module load
        out = []
        for t in topics:
            tt = _tokens(t["title"])
            best, best_score, via = None, 0.0, "words"
            for n in nodes:
                s = _dice(tt, node_tokens[n["id"]])
                if s > best_score:
                    best, best_score, via = n, s, "words"
            tv = (vectors or {}).get(t["id"])
            if tv and node_vecs:
                for n in nodes:
                    nv = node_vecs.get(n["id"])
                    if not nv:
                        continue
                    s = cosine(tv, nv)
                    # put both scales on one footing: a strong embedding match
                    # (≥ emb_floor) outranks a weak word match
                    scaled = 0.4 + (s - emb_floor) * 2 if s >= emb_floor else 0.0
                    if scaled > best_score:
                        best, best_score, via = n, scaled, "meaning"
            if best is not None and best_score >= floor:
                out.append({"learning_id": t["id"], "title": t["title"],
                            "node_id": best["id"], "path": self.path(best["id"]),
                            "score": round(best_score, 2), "via": via})
        out.sort(key=lambda s: -s["score"])
        return out
