"""Import — or remove — the curated curriculum decks from seeds/.

Importing is idempotent: topics whose titles already exist are skipped, so you
can re-run after editing seed files or adding new decks. New cards ease into
review via the normal new-per-day cap — nothing floods tomorrow's queue.

    python tools/seed_curriculum.py            # import everything
    python tools/seed_curriculum.py --dry-run  # show what would be created

Removal is the mirror image, matched the same way (by title). It previews by
default — including how much review history you'd lose — and only deletes
with --yes:

    python tools/seed_curriculum.py --remove        # preview what would go
    python tools/seed_curriculum.py --remove --yes  # actually delete

Topics you renamed no longer match and are left alone; topics you edited but
didn't rename are removed along with their cards and review history.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db.repository import Repository  # noqa: E402

SEED_DIR = ROOT / "seeds"


def load_decks() -> list[dict]:
    decks = []
    for path in sorted(SEED_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            deck = json.load(f)
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="import: report only; write nothing")
    parser.add_argument("--remove", action="store_true",
                        help="remove seed topics (matched by title) instead of importing")
    parser.add_argument("--yes", action="store_true",
                        help="with --remove: actually delete (default is a preview)")
    args = parser.parse_args()
    if args.yes and not args.remove:
        parser.error("--yes only makes sense with --remove")
    if args.remove and args.dry_run:
        parser.error("--remove already previews by default; combine it with --yes to delete")

    repo = Repository()
    decks = load_decks()

    if args.remove:
        topics, reviews = remove_decks(repo, decks, apply=args.yes)
        verb = "Removed" if args.yes else "Would remove"
        print(f"\n{verb} {topics} topics"
              + (f" and {reviews} recorded reviews" if reviews else "") + ".")
        if topics and not args.yes:
            print("Nothing was deleted. Re-run with --yes to delete.")
            print("Topics you have renamed no longer match and will be kept.")
        return

    created, cards, skipped = import_decks(repo, decks, dry_run=args.dry_run)
    verb = "Would create" if args.dry_run else "Created"
    print(f"\n{verb} {created} topics ({cards} cards); {skipped} skipped as existing.")
    if created and not args.dry_run:
        new_per_day = repo.get_new_per_day()
        print(f"They ease into review at your new-per-day cap ({new_per_day}/day — adjustable in Settings).")
        print("Tip: focus a subject on the Today screen to pull its topics forward.")


if __name__ == "__main__":
    main()
