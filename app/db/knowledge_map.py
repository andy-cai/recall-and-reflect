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

import math
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


_MARKER = re.compile(r"\s*\{([^{}]*)\}\s*$")
INBOX_HEADER = "@inbox"
UNTITLED = "(untitled)"


def _split_marker(body: str) -> tuple[str, Optional[int], Optional[list[int]]]:
    """Pull a trailing "{id:12 topics:3,4 | status}" marker off a line.

    Braces that don't hold id:/topics: (TeX like {x}) are left as text.
    """
    m = _MARKER.search(body)
    if not m:
        return body, None, None
    inner = m.group(1).split("|", 1)[0].strip()
    if not inner and "|" not in m.group(1):
        return body, None, None
    node_id, topics, ok = None, None, True
    for part in inner.split():
        if part.startswith("id:") and part[3:].isdigit():
            node_id = int(part[3:])
        elif part.startswith("topics:"):
            ids = [x for x in part[7:].split(",") if x.strip()]
            if all(x.strip().isdigit() for x in ids):
                topics = [int(x) for x in ids]
            else:
                ok = False
        else:
            ok = False
    if not ok:
        return body, None, None
    return body[: m.start()].rstrip(), node_id, topics


def parse_outline(text: str, markers: bool = False) -> list[dict]:
    """Indented text -> [{depth, text, flag, source}] (+ {id, topics, kind} with markers).

    - Indentation (spaces or tabs) sets depth; bullet glyphs are stripped.
    - A line starting with "!" (or ending with " !" / "(!)") is flagged.
    - A line "## Label" is not a node: it sets the source label for what
      follows ("## -" clears it). With markers, "## @inbox" starts the inbox,
      "# " lines are comments, and a trailing {id:N topics:a,b} marker ties
      the line to an existing item and its linked topics.
    """
    rows: list[dict] = []
    indents: list[int] = []
    source: Optional[str] = None
    inbox = False
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        stripped = raw.lstrip(" \t")
        if markers and (stripped == "#" or stripped.startswith("# ")):
            continue
        if stripped.startswith("## "):
            label = stripped[3:].strip()
            if markers and label == INBOX_HEADER:
                inbox = True
            else:
                inbox = False
                source = None if label in ("", "-") else label
            indents = []
            continue
        lead = raw[: len(raw) - len(stripped)]
        indent = sum(4 if c == "\t" else 1 for c in lead)
        body = _BULLET.sub("", stripped).strip()
        node_id, topics = None, None
        if markers:
            body, node_id, topics = _split_marker(body)
        flag = False
        if body.startswith("!"):
            flag, body = True, body[1:].strip()
        if body.endswith(" !"):
            flag, body = True, body[:-2].rstrip()
        elif body.endswith("(!)"):
            flag, body = True, body[:-3].rstrip()
        if not body:
            continue
        while indents and indents[-1] >= indent:
            indents.pop()
        depth = len(indents)
        indents.append(indent)
        row = {"depth": depth, "text": body, "flag": flag, "source": source}
        if markers:
            row.update({"id": node_id, "topics": topics, "kind": "inbox" if inbox else "item",
                        "indent": indent})
        rows.append(row)
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

    # ---------- text round-trip (for editors and Claude Code) ----------

    def export_text(self, status: bool = False, redact=None) -> str:
        """The whole map as indented text with {id:N topics:a,b} markers.

        Edit it and feed it back through plan_apply()/apply_text(). With
        status, each marker also carries "| state pct · N due" (ignored on
        the way back in). `redact` (text -> text) scrubs what is shown; a line
        that comes back still redacted keeps its original text.
        """
        tree = self.tree() if status else None
        info = {n["id"]: n for n in tree["nodes"]} if tree else {}
        nodes = self._nodes()
        links: dict[int, list[int]] = defaultdict(list)
        for r in self.db.fetch_all("SELECT node_id, learning_id FROM map_links ORDER BY learning_id"):
            links[r["node_id"]].append(r["learning_id"])
        kids: dict[Optional[int], list[dict]] = defaultdict(list)
        inbox = []
        for n in nodes:
            (inbox if n["kind"] == "inbox" else kids[n["parent_id"]]).append(n)
        show = redact or (lambda t: t)

        def line(n: dict, depth: int) -> str:
            parts = [f"id:{n['id']}"]
            if links.get(n["id"]):
                parts.append("topics:" + ",".join(str(x) for x in links[n["id"]]))
            marker = " ".join(parts)
            if status and n["id"] in info:
                i = info[n["id"]]
                bits = []
                if i["state"]:
                    bits.append(i["state"] + (f" {round(i['r'] * 100)}%" if i["r"] is not None else ""))
                elif i.get("agg") and i["agg"]["total"]:
                    c = i["agg"]["counts"]
                    bits.append(" ".join(f"{c[k]} {k}" for k in STATES if c[k]))
                due = (i.get("agg") or {}).get("due") or i["due"]
                if due:
                    bits.append(f"{due} due")
                if bits:
                    marker += " | " + " · ".join(bits)
            text = show(n["text"]) or UNTITLED
            return "  " * depth + ("! " if n["flag"] else "") + text + " {" + marker + "}"

        out = ["# Recall & Reflect knowledge map. Edit, then: python tools/rr.py map apply FILE",
               "# Keep each {id:N} marker on its item; a line without one is a new item.",
               "# topics: lists exactly the linked topic ids. Indent two spaces per level.",
               "# '! ' flags an item. '## Label' sets the source for the areas below it;",
               "# '## @inbox' holds unplaced items. Text after '|' in a marker is ignored."]
        current = object()

        def walk(parent: Optional[int], depth: int) -> None:
            for n in kids.get(parent, []):
                out.append(line(n, depth))
                walk(n["id"], depth + 1)

        for root in kids.get(None, []):
            if root["source"] != current:
                current = root["source"]
                out.append("## " + (current or "-"))
            out.append(line(root, 0))
            walk(root["id"], 1)
        if inbox:
            out.append("## " + INBOX_HEADER)
            out += [line(n, 0) for n in inbox]
        return "\n".join(out) + "\n"

    def plan_apply(self, text: str, redact=None) -> dict:
        """Diff edited map text against the database. Changes nothing.

        Returns {errors, changes, deletes, rows}: `changes` and `deletes` are
        human-readable lines; apply_text() executes the same plan.
        """
        rows = parse_outline(text, markers=True)
        nodes = {n["id"]: n for n in self._nodes()}
        links: dict[int, set[int]] = defaultdict(set)
        for r in self.db.fetch_all("SELECT node_id, learning_id FROM map_links"):
            links[r["node_id"]].add(r["learning_id"])
        active = {r["id"] for r in self.db.fetch_all("SELECT id FROM learnings WHERE is_active = 1")}
        show = redact or (lambda t: t)
        errors, changes = [], []
        seen: set[int] = set()
        stack: list[int] = []
        for i, row in enumerate(rows):
            if row["kind"] == "inbox":
                if row["depth"] or row.get("indent"):
                    errors.append(f"inbox items can't be nested: {row['text']!r}")
                row["parent"] = None
                stack = []
            else:
                depth = min(row["depth"], len(stack))
                stack = stack[:depth]
                row["parent"] = stack[-1] if stack else None   # index into rows
                stack.append(i)
            nid = row["id"]
            if nid is not None:
                if nid not in nodes:
                    errors.append(f"unknown id:{nid} ({row['text']!r}); drop the marker to add it as new")
                elif nid in seen:
                    errors.append(f"id:{nid} appears twice")
                seen.add(nid)
                if nid in nodes and row["text"] in (show(nodes[nid]["text"]), UNTITLED) \
                        and (show(nodes[nid]["text"]) or UNTITLED) == row["text"]:
                    row["text"] = nodes[nid]["text"]          # came back redacted/untitled: keep the original
            bad = [t for t in (row["topics"] or []) if t not in active]
            if bad:
                errors.append(f"unknown topic id(s) {bad} on {row['text']!r}")

        def label(i: Optional[int]) -> str:
            return "the top level" if i is None else repr(rows[i]["text"])

        for row in rows:
            nid, where = row["id"], label(row["parent"])
            if nid is None or nid not in nodes:
                kind = "the inbox" if row["kind"] == "inbox" else where
                changes.append(f"add {row['text']!r} to {kind}" if row["kind"] == "inbox" or row["parent"] is None
                               else f"add {row['text']!r} under {where}")
                continue
            old = nodes[nid]
            if row["text"] != old["text"]:
                changes.append(f"rename id:{nid} {old['text']!r} -> {row['text']!r}")
            if row["flag"] != bool(old["flag"]):
                changes.append(f"{'flag' if row['flag'] else 'unflag'} id:{nid} {row['text']!r}")
            old_parent = old["parent_id"]
            new_parent = None if row["parent"] is None else rows[row["parent"]]["id"]
            if row["kind"] != old["kind"]:
                changes.append(f"{'park' if row['kind'] == 'inbox' else 'place'} id:{nid} {row['text']!r}"
                               + ("" if row["kind"] == "inbox" else f" under {where}"))
            elif row["kind"] == "item" and (new_parent != old_parent or (new_parent is None and row["parent"] is not None)):
                changes.append(f"move id:{nid} {row['text']!r} under {where}")
            if row["parent"] is None and row["kind"] == "item" and row["source"] != old["source"]:
                changes.append(f"source of id:{nid} {row['text']!r}: {old['source'] or '-'} -> {row['source'] or '-'}")
            want, have = set(row["topics"] or []), links.get(nid, set())
            for t in sorted(want - have):
                changes.append(f"link topic {t} to id:{nid} {row['text']!r}")
            for t in sorted(have - want):
                changes.append(f"unlink topic {t} from id:{nid} {row['text']!r}")
        for row in rows:
            if (row["id"] is None or row["id"] not in nodes) and row["topics"]:
                changes.append(f"link topic(s) {row['topics']} to new {row['text']!r}")

        gone = [nid for nid in nodes if nid not in seen]
        gone_set = set(gone)
        deletes = []
        for nid in gone:                     # report only the top of each removed subtree
            if nodes[nid]["parent_id"] in gone_set:
                continue
            below = len([x for x in self.subtree_ids(nid) if x in gone_set]) - 1
            deletes.append(f"delete id:{nid} {nodes[nid]['text']!r}" + (f" (+{below} under it)" if below else ""))
        return {"errors": errors, "changes": changes, "deletes": deletes, "rows": rows,
                "gone": gone}

    def apply_text(self, text: str, allow_delete: bool = False, redact=None) -> dict:
        """Make the database match edited map text, in one transaction."""
        plan = self.plan_apply(text, redact=redact)
        if plan["errors"]:
            raise ValueError("; ".join(plan["errors"]))
        if plan["gone"] and not allow_delete:
            raise ValueError(f"{len(plan['deletes'])} item(s) would be deleted; "
                             "pass allow_delete to confirm")
        rows = plan["rows"]
        now = to_iso(datetime.now())
        with self.db.get_connection() as conn:
            pos: dict[tuple, int] = defaultdict(int)
            for row in rows:
                parent_id = None if row["parent"] is None else rows[row["parent"]]["_id"]
                key = (row["kind"], parent_id)
                position = pos[key]
                pos[key] += 1
                if row["id"] is None:
                    cur = conn.execute(
                        "INSERT INTO map_nodes (parent_id, position, text, kind, source, flag, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (parent_id, position, row["text"], row["kind"], row["source"],
                         1 if row["flag"] else 0, now))
                    row["_id"] = cur.lastrowid
                else:
                    row["_id"] = row["id"]
                    conn.execute(
                        "UPDATE map_nodes SET parent_id = ?, position = ?, text = ?, kind = ?, "
                        "source = ?, flag = ? WHERE id = ?",
                        (parent_id, position, row["text"], row["kind"], row["source"],
                         1 if row["flag"] else 0, row["id"]))
                want = sorted(set(row["topics"] or []))
                marks = ",".join("?" * len(want)) or "NULL"
                conn.execute(f"DELETE FROM map_links WHERE node_id = ? AND learning_id NOT IN ({marks})",
                             (row["_id"], *want))
                for t in want:
                    conn.execute("INSERT OR IGNORE INTO map_links (node_id, learning_id) VALUES (?, ?)",
                                 (row["_id"], t))
            if plan["gone"]:
                marks = ",".join("?" * len(plan["gone"]))
                conn.execute(f"DELETE FROM map_nodes WHERE id IN ({marks})", tuple(plan["gone"]))
            conn.commit()
        return {"changes": len(plan["changes"]), "deleted": len(plan["gone"])}

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
        """Pair unplaced topics with their best map node (plus runners-up).

        Scores: word overlap (Dice on content words) between the topic title
        and the node; cosine similarity when an embed model is running
        (`vectors` = learning_id -> vector, `embed` = texts -> vectors). The
        topic's subject then has to agree with where the node sits: sharing a
        word with the node's ancestors earns a small bonus, sharing none cuts
        the score, so "Pack thermal management" (Battery) doesn't land on
        "Thermal strains" (Mechanics). Suggestions only; the person confirms.
        """
        nodes = self._leafish()
        topics = self.unplaced_learnings(limit=400)
        if not nodes or not topics:
            return []
        by_id = {n["id"]: n for n in self._nodes()}

        def ancestors(n: dict) -> list[dict]:
            out, cur, guard = [], by_id.get(n["parent_id"]), 0
            while cur and guard < 64:
                out.append(cur)
                cur = by_id.get(cur["parent_id"])
                guard += 1
            return out

        def ctx(n: dict) -> str:
            parent = by_id.get(n["parent_id"])
            return f"{parent['text']} — {n['text']}" if parent else n["text"]

        node_tokens = {n["id"]: _tokens(n["text"]) for n in nodes}
        # where a node lives: its ancestors' words (not its own, or "fluid
        # dynamics" would claim every Dynamics topic)
        home_tokens = {n["id"]: set().union(set(), *[_tokens(a["text"]) for a in ancestors(n)])
                       for n in nodes}
        # rare words carry the match; "testing" or "design" alone shouldn't
        df: dict[str, int] = defaultdict(int)
        for toks in node_tokens.values():
            for w in toks:
                df[w] += 1
        n_nodes = len(nodes)

        def weight(w: str) -> float:
            return math.log(1 + n_nodes / (1 + df.get(w, 0)))

        def wdice(a: set[str], b: set[str]) -> float:
            if not a or not b:
                return 0.0
            return 2 * sum(weight(w) for w in a & b) / (sum(map(weight, a)) + sum(map(weight, b)))
        node_vecs: dict[int, list[float]] = {}
        if vectors and embed:
            try:
                vecs = embed([ctx(n) for n in nodes])
                node_vecs = {n["id"]: v for n, v in zip(nodes, vecs or []) if v}
            except Exception:
                node_vecs = {}

        from app.services.embeddings import cosine  # local import: no cycle at module load
        subjects = {r["id"]: r["subject"] for r in self.db.fetch_all(
            "SELECT id, subject FROM learnings WHERE is_active = 1")}
        out = []
        for t in topics:
            tt = _tokens(t["title"])
            st = _tokens(subjects.get(t["id"]) or "")
            tv = (vectors or {}).get(t["id"])
            scored = []
            for n in nodes:
                s, via = wdice(tt, node_tokens[n["id"]]), "words"
                nv = node_vecs.get(n["id"]) if tv else None
                if nv:
                    c = cosine(tv, nv)
                    # put both scales on one footing: a strong embedding match
                    # (≥ emb_floor) outranks a weak word match
                    scaled = 0.4 + (c - emb_floor) * 2 if c >= emb_floor else 0.0
                    if scaled > s:
                        s, via = scaled, "meaning"
                if s <= 0:
                    continue
                if st:
                    s = s + 0.1 if st & home_tokens[n["id"]] else s * 0.6
                scored.append((round(min(s, 1.0), 2), via, n))
            scored.sort(key=lambda x: -x[0])
            good = [x for x in scored if x[0] >= floor]
            if not good:
                continue
            best_s, via, best = good[0]
            out.append({"learning_id": t["id"], "title": t["title"],
                        "node_id": best["id"], "path": self.path(best["id"]),
                        "score": best_s, "via": via,
                        "alternatives": [{"node_id": n["id"], "path": self.path(n["id"]), "score": sc}
                                         for sc, _, n in good[1:3]]})
        out.sort(key=lambda s: -s["score"])
        return out
