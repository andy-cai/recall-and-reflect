# Recall & Reflect — notes for Claude Code

A local-first spaced-repetition app (FastAPI + SQLite + vanilla JS). The owner
studies with it; you help curate their data and develop the code.

## Touching the owner's data: use `tools/rr.py`, never the database

The data lives in `data/recall.db`. Don't open it with sqlite3, Python or any
other route. Go through `python tools/rr.py`, which:

- hides People and Private topics (they must never reach a cloud model, and
  you are one),
- replaces saved People names with `[name]`,
- logs every output to Settings › Sent to cloud,
- applies the app's rules on writes (one transaction, links kept, nothing
  half-applied).

You may **change the knowledge map**. Topics and cards are **read-only** to you.

```
python tools/rr.py map export --status      # whole map + state/recall/due per item
python tools/rr.py map export -o map.txt    # editable copy
python tools/rr.py map apply map.txt        # preview the diff (changes nothing)
python tools/rr.py map apply map.txt --yes  # apply; add --delete if items were removed
python tools/rr.py map weak -n 20           # weakest items first, then per-area totals
python tools/rr.py topics list [--unplaced] [--search WORDS]
python tools/rr.py topics show ID           # content, key ideas, where it sits in the map
```

### Map text format

```
## Degree                                   source label for the areas below
Mechanics of Materials {id:1}               top-level area
  Ductile failure {id:5 topics:12,40}       linked topic ids, exactly
    ! TTT / CCT diagrams {id:9}             "! " = flagged "lacking understanding"
    Paris law                               no marker = a new item
## @inbox                                   parked, not yet in the tree
MECH412 {id:200}
```

Two-space indents. Keep every `{id:N}` on its item when you rename or move it;
deleting the line deletes the item and everything under it. Text after `|` in a
marker (e.g. `| fading 72% · 3 due`) is display only. `[name]` and
`(untitled)` come back unchanged.

### How to make map changes

1. Export, edit the file, run `map apply` **without** `--yes`, and show the
   owner the preview.
2. Apply only after they agree. Use `--delete` only when they've seen the
   deletions in the preview.
3. Keep item labels short. Formulas and explanations belong in topics, not
   in the map.

Status per item is computed, not stored. It comes from FSRS recall chance of
the linked topics' cards: solid ≥ 85%, fading 60–85%, shaky < 60% (or an idea
missed twice running, or flagged), new = cards not yet reviewed, none = no
cards. Headings aggregate their subtree.

## Developing

- Run: `python run.py` (http://127.0.0.1:8765). Point it at a scratch DB with
  `RR_DB_PATH=/tmp/x.db` when testing; never use the owner's.
- Tests: `python -m unittest discover tests` (all must pass; CI runs 3.10 and 3.13).
- Layout: `app/db/` (schema, `repository.py`, `knowledge_map.py`),
  `app/api/` (routers), `app/services/` (local LLM, embeddings, cloud assist),
  `web/js/views/` (one module per screen), `web/js/knowledge.js` (map + atlas).
- Privacy is the product's main promise (README › Privacy). Any new path that
  sends data off the machine must refuse People/Private topics, redact People
  names, and log to `cloud_log`.
