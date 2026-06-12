"""Starter curriculum: load the seed decks and import or remove them.

One source of truth for both front doors — the CLI (tools/seed_curriculum.py)
and Settings → Starter curriculum. Topics are matched by title, the same key
import uses to skip existing ones, so removal is exactly the mirror of import:
user-created topics are never touched, and seed topics the user renamed no
longer match and are kept.
"""

import json

from app.config import SEEDS_DIR
from app.db.repository import Repository


def load_decks() -> list[dict]:
    decks = []
    for path in sorted(SEEDS_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                deck = json.load(f)
        except (OSError, ValueError):
            continue
        deck["_file"] = path.name
        decks.append(deck)
    return decks


def import_decks(repo: Repository, decks: list[dict], dry_run: bool = False,
                 verbose: bool = True) -> tuple[int, int, int]:
    """Create seed topics that don't exist yet. Returns (created, cards, skipped)."""
    existing = {
        r["title"].strip().lower()
        for r in repo.db.fetch_all("SELECT title FROM learnings WHERE is_active = 1")
    }
    total_created = total_skipped = total_cards = 0
    for deck in decks:
        created = skipped = cards = 0
        for t in deck.get("topics", []):
            title = t["title"].strip()
            if title.lower() in existing:
                skipped += 1
                continue
            if not dry_run:
                lid = repo.create_learning(
                    title=title,
                    content=t.get("content", "").strip(),
                    subject=t.get("subject") or None,
                    tags=t.get("tags", []),
                )
                ideas = [i for i in t.get("key_ideas", []) if i.strip()]
                if ideas:
                    repo.set_key_ideas(lid, ideas)
                repo.create_recall_card(lid, title, t.get("content", ""),
                                        prompt=t.get("recall_prompt"))
                cards += 1
                for c in t.get("cards", []):
                    q, a = c.get("question", "").strip(), c.get("answer", "").strip()
                    if q and a:
                        repo.create_question(lid, q, a)
                        cards += 1
            existing.add(title.lower())
            created += 1
        if verbose:
            label = deck.get("deck", deck["_file"])
            print(f"  {label}: {created} new topics, {skipped} already present"
                  + ("" if dry_run else f", {cards} cards"))
        total_created += created
        total_skipped += skipped
        total_cards += cards
    return total_created, total_cards, total_skipped


def remove_decks(repo: Repository, decks: list[dict], apply: bool = False,
                 verbose: bool = True) -> tuple[int, int]:
    """Delete active topics whose titles match the seed files (the import key).

    Preview unless apply=True. Returns (matched topics, recorded reviews).
    Deletion cascades to cards, key ideas, tags and review history.
    """
    rows = repo.db.fetch_all(
        """
        SELECT l.id, l.title, COUNT(r.id) AS reviews
        FROM learnings l
        LEFT JOIN questions q ON q.learning_id = l.id
        LEFT JOIN reviews r ON r.question_id = q.id
        WHERE l.is_active = 1
        GROUP BY l.id
        """)
    by_title = {r["title"].strip().lower(): r for r in rows}

    total_topics = total_reviews = 0
    for deck in decks:
        matches = [by_title[key] for key in
                   (t["title"].strip().lower() for t in deck.get("topics", []))
                   if key in by_title]
        label = deck.get("deck", deck["_file"])
        n_reviews = sum(m["reviews"] for m in matches)
        if verbose:
            if matches:
                print(f"  {label}: {len(matches)} topics"
                      + (f", {n_reviews} reviews recorded" if n_reviews else ""))
            else:
                print(f"  {label}: nothing to remove")
        if apply:
            for m in matches:
                repo.delete_learning(m["id"])
        total_topics += len(matches)
        total_reviews += n_reviews
    return total_topics, total_reviews
