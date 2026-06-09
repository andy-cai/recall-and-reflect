"""Import the curated curriculum decks from seeds/ into the local database.

Idempotent: topics whose titles already exist are skipped, so you can re-run
after editing seed files or adding new decks. New cards ease into review via
the normal new-per-day cap — nothing floods tomorrow's queue.

    python tools/seed_curriculum.py            # import everything
    python tools/seed_curriculum.py --dry-run  # show what would be created
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = parser.parse_args()

    repo = Repository()
    existing = {
        r["title"].strip().lower()
        for r in repo.db.fetch_all("SELECT title FROM learnings WHERE is_active = 1")
    }

    total_created = total_skipped = total_cards = 0
    for deck in load_decks():
        created = skipped = cards = 0
        for t in deck.get("topics", []):
            title = t["title"].strip()
            if title.lower() in existing:
                skipped += 1
                continue
            if not args.dry_run:
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
        label = deck.get("deck", deck["_file"])
        print(f"  {label}: {created} new topics, {skipped} already present"
              + ("" if args.dry_run else f", {cards} cards"))
        total_created += created
        total_skipped += skipped
        total_cards += cards

    verb = "Would create" if args.dry_run else "Created"
    print(f"\n{verb} {total_created} topics ({total_cards} cards); {total_skipped} skipped as existing.")
    if total_created and not args.dry_run:
        new_per_day = repo.get_new_per_day()
        print(f"They ease into review at your new-per-day cap ({new_per_day}/day — adjustable in Settings).")
        print("Tip: focus a subject on the Today screen to pull its topics forward.")


if __name__ == "__main__":
    main()
