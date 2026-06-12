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
didn't rename are removed along with their cards and review history. The same
actions live in the app under Settings → Starter curriculum; the shared logic
is app/services/seeds.py.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db.repository import Repository                          # noqa: E402
from app.services.seeds import import_decks, load_decks, remove_decks  # noqa: E402


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
