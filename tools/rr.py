"""rr — read your Recall & Reflect data and edit the knowledge map from a shell.

Built for Claude Code (and you): plain-text in, plain-text out, the app's own
rules on every write. Works whether or not the app is running.

    python tools/rr.py map export [--status] [-o FILE]   the map as indented text
    python tools/rr.py map apply FILE [--yes] [--delete]  make the map match FILE
    python tools/rr.py map weak [-n 15]                   weakest items, with paths
    python tools/rr.py topics list [--unplaced] [--search WORDS]
    python tools/rr.py topics show ID

`map apply` previews by default and changes nothing; --yes applies, and
--delete is also required when the file drops existing items.

Privacy: this tool's output may be read by a cloud model (that's the point of
running it under Claude Code), so it follows the same gates as cloud assist —
People and Private topics are never listed or shown, saved People names are
replaced with [name], and every output is recorded in Settings › Sent to cloud
as "rr CLI". Only the map is writable; topics and cards are read-only here.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.fsrs import retrievability                          # noqa: E402
from app.db.database import from_iso                              # noqa: E402
from app.db.knowledge_map import MapStore                         # noqa: E402
from app.db.repository import Repository                          # noqa: E402
from app.services.cloud import redact_people                      # noqa: E402

LOG_MODEL = "rr CLI (external tool)"


class Ctx:
    def __init__(self, repo: Repository | None = None):
        self.repo = repo or Repository()
        self.map = MapStore(self.repo.db)
        self.names = self.repo.people_names()
        self.redacted = 0

    def redact(self, text: str) -> str:
        out, n = redact_people(text or "", self.names)
        self.redacted += n
        return out

    def emit(self, action: str, text: str, out=None) -> None:
        """Print (or write) output and record that it left the app."""
        if out:
            Path(out).write_text(text, encoding="utf-8")
            print(f"wrote {out} ({len(text)} chars)")
        else:
            sys.stdout.write(text if text.endswith("\n") else text + "\n")
        self.repo.log_cloud(f"rr CLI: {action}", LOG_MODEL, len(text), self.redacted, True)


def _hidden_ids(repo: Repository) -> set[int]:
    rows = repo.db.fetch_all(
        "SELECT id FROM learnings WHERE private = 1 OR LOWER(TRIM(COALESCE(subject,''))) = 'people'")
    return {r["id"] for r in rows}


def _recall(repo: Repository) -> dict[int, tuple[int, float | None]]:
    """learning_id -> (card count, mean recall chance of reviewed cards)."""
    now = datetime.now()
    acc: dict[int, list] = {}
    for r in repo.db.fetch_all(
            "SELECT learning_id, state, stability, last_reviewed_at FROM questions WHERE suspended = 0"):
        a = acc.setdefault(r["learning_id"], [0, []])
        a[0] += 1
        last = from_iso(r["last_reviewed_at"])
        if r["state"] >= 1 and r["stability"] > 0 and last:
            a[1].append(retrievability(r["stability"], max(0.0, (now - last).total_seconds() / 86400)))
    return {k: (v[0], sum(v[1]) / len(v[1]) if v[1] else None) for k, v in acc.items()}


# ---------- map ----------

def map_export(ctx: Ctx, args) -> int:
    text = ctx.map.export_text(status=args.status, redact=ctx.redact)
    ctx.emit("map export", text, args.output)
    return 0


def map_apply(ctx: Ctx, args) -> int:
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    plan = ctx.map.plan_apply(text, redact=ctx.redact)
    if plan["errors"]:
        print("Not applied. Fix these first:")
        for e in plan["errors"]:
            print("  ✕ " + e)
        return 2
    if not plan["changes"] and not plan["deletes"]:
        print("No changes.")
        return 0
    for c in plan["changes"]:
        print("  " + c)
    for d in plan["deletes"]:
        print("  " + d + "  (linked topics stay in the Library)")
    if not args.yes:
        print(f"\nPreview only: {len(plan['changes'])} change(s), {len(plan['deletes'])} deletion(s). "
              "Re-run with --yes to apply" + (" (and --delete to allow deletions)." if plan["deletes"] else "."))
        return 0
    if plan["deletes"] and not args.delete:
        print("\nNot applied: the file drops existing items. Re-run with --yes --delete if that's intended.")
        return 3
    res = ctx.map.apply_text(text, allow_delete=args.delete, redact=ctx.redact)
    print(f"\nApplied: {res['changes']} change(s), {res['deleted']} item(s) deleted.")
    return 0


def map_weak(ctx: Ctx, args) -> int:
    tree = ctx.map.tree()
    by_id = {n["id"]: n for n in tree["nodes"]}

    def path(n):
        out, cur, g = [], n, 0
        while cur and g < 64:
            out.append(ctx.redact(cur["text"]))
            cur = by_id.get(cur["parent_id"])
            g += 1
        return " › ".join(reversed(out))

    order = {"shaky": 0, "fading": 1, "none": 2, "new": 3, "solid": 4}
    items = [n for n in tree["nodes"] if n["state"] and n["kind"] == "item"]
    items.sort(key=lambda n: (not n["flag"], order[n["state"]], n["r"] if n["r"] is not None else 2))
    lines = [f"{'state':7} {'recall':>6}  item (id)"]
    for n in items[: args.n]:
        r = f"{round(n['r'] * 100)}%" if n["r"] is not None else "-"
        lines.append(f"{n['state'] + ('!' if n['flag'] else ''):7} {r:>6}  {path(n)} (id:{n['id']})")
    roots = [n for n in tree["nodes"] if n["parent_id"] is None and n["kind"] == "item" and n.get("agg")]
    lines.append("")
    lines.append("areas: " + "; ".join(
        f"{ctx.redact(n['text'])} {n['agg']['counts']['solid']}/{n['agg']['total']} solid, "
        f"{n['agg']['counts']['none']} uncovered, {n['agg']['due']} due" for n in roots))
    ctx.emit("map weak", "\n".join(lines))
    return 0


# ---------- topics (read-only) ----------

def topics_list(ctx: Ctx, args) -> int:
    hidden = _hidden_ids(ctx.repo)
    placed = {r["learning_id"] for r in ctx.repo.db.fetch_all("SELECT DISTINCT learning_id FROM map_links")}
    stats = _recall(ctx.repo)
    rows = ctx.repo.db.fetch_all(
        "SELECT id, title, subject FROM learnings WHERE is_active = 1 ORDER BY subject COLLATE NOCASE, title")
    words = [w.lower() for w in (args.search or "").split()]
    lines = [f"{'id':>5}  {'cards':>5}  {'recall':>6}  {'map':3}  subject / title"]
    shown = 0
    for r in rows:
        if r["id"] in hidden or (args.unplaced and r["id"] in placed):
            continue
        hay = f"{r['title']} {r['subject'] or ''}".lower()
        if words and not all(w in hay for w in words):
            continue
        cards, rec = stats.get(r["id"], (0, None))
        lines.append(f"{r['id']:>5}  {cards:>5}  {(str(round(rec * 100)) + '%') if rec is not None else '-':>6}  "
                     f"{'yes' if r['id'] in placed else 'no':3}  {ctx.redact(r['subject'] or '-')} / {ctx.redact(r['title'])}")
        shown += 1
    lines.append(f"\n{shown} topic(s)" + (f"; {len(hidden)} People/Private topic(s) not shown" if hidden else ""))
    ctx.emit("topics list", "\n".join(lines))
    return 0


def topics_show(ctx: Ctx, args) -> int:
    if args.id in _hidden_ids(ctx.repo):
        print("That topic is People or Private: it stays on this machine and isn't shown here.")
        return 4
    learning = ctx.repo.get_learning(args.id)
    if not learning or not learning.is_active:
        print(f"No topic {args.id}.")
        return 1
    cards, rec = _recall(ctx.repo).get(args.id, (0, None))
    ideas = ctx.repo.get_key_ideas(args.id)
    nodes = ctx.map.nodes_for_learning(args.id)
    out = [f"# {ctx.redact(learning.title)}  (id {args.id})",
           f"subject: {ctx.redact(learning.subject or '-')}   cards: {cards}   recall: "
           + (f"{round(rec * 100)}%" if rec is not None else "not reviewed yet"),
           "map: " + ("; ".join(" › ".join(ctx.redact(p) for p in n["path"]) + f" (id:{n['id']})" for n in nodes)
                      if nodes else "not placed"),
           "", ctx.redact(learning.content or "")]
    if ideas:
        out += ["", "key ideas:"] + [f"  - {ctx.redact(i['idea'])}" for i in ideas]
    ctx.emit("topics show", "\n".join(out))
    return 0


def main(argv=None, ctx: Ctx | None = None) -> int:
    p = argparse.ArgumentParser(prog="rr", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="group", required=True)

    m = sub.add_parser("map", help="the knowledge map").add_subparsers(dest="cmd", required=True)
    e = m.add_parser("export", help="print the map as editable text")
    e.add_argument("--status", action="store_true", help="annotate items with state, recall and due counts")
    e.add_argument("-o", "--output", help="write to a file instead of stdout")
    e.set_defaults(fn=map_export)
    a = m.add_parser("apply", help="make the map match an edited export (previews unless --yes)")
    a.add_argument("file", help="edited export, or - for stdin")
    a.add_argument("--yes", action="store_true", help="apply the changes")
    a.add_argument("--delete", action="store_true", help="allow deleting items missing from the file")
    a.set_defaults(fn=map_apply)
    w = m.add_parser("weak", help="weakest items first, with their paths")
    w.add_argument("-n", type=int, default=15)
    w.set_defaults(fn=map_weak)

    t = sub.add_parser("topics", help="your topics (read-only)").add_subparsers(dest="cmd", required=True)
    tl = t.add_parser("list", help="id, cards, recall, placed?, subject / title")
    tl.add_argument("--unplaced", action="store_true", help="only topics not in the map")
    tl.add_argument("--search", help="words that must all appear in title or subject")
    tl.set_defaults(fn=topics_list)
    ts = t.add_parser("show", help="one topic: content, key ideas, where it sits in the map")
    ts.add_argument("id", type=int)
    ts.set_defaults(fn=topics_show)

    args = p.parse_args(argv)
    return args.fn(ctx or Ctx(), args)


if __name__ == "__main__":
    sys.exit(main())
