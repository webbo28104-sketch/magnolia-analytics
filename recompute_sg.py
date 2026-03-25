#!/usr/bin/env python3
"""
Recompute strokes gained for all completed rounds using the current
PGA Tour / Broadie baseline tables.

Run from the project root:
    python recompute_sg.py               # update all rounds
    python recompute_sg.py --dry-run     # print values without writing
    python recompute_sg.py --clear-cache # also wipe stale Claude insights

Round SG values are stored in five new columns on the rounds table
(sg_off_tee, sg_approach, sg_atg, sg_putting, sg_total).  The Flask app
will create those columns automatically on startup via _run_column_migrations()
before this script updates them.

Safe-guards
-----------
- Raw scores, hole data, and handicap differentials are never touched.
- Each round is committed independently; a failure on one round does not
  roll back others.
- Progress is printed every BATCH_SIZE rounds and at completion.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models.round import Round
from app.utils.strokes_gained import (
    strokes_gained_putting,
    strokes_gained_off_tee,
    strokes_gained_approach,
    strokes_gained_around_green,
)

BATCH_SIZE = 50


def recompute(dry_run: bool = False, clear_cache: bool = False) -> None:
    app = create_app('production')

    with app.app_context():
        rounds = (
            Round.query
            .filter_by(status='complete')
            .order_by(Round.id)
            .all()
        )
        total = len(rounds)
        print(f"Found {total} complete round(s) to process.")
        if dry_run:
            print("DRY RUN — no writes will occur.\n")

        updated = skipped = errors = 0

        for i, round_ in enumerate(rounds, 1):
            try:
                holes = round_.holes.order_by('hole_number').all()

                if not holes:
                    print(f"  [{i:>4}/{total}] round {round_.id:>5} — no holes, skipping")
                    skipped += 1
                    continue

                # Build course_hole_map for OTT yardage lookups
                course_hole_map = {}
                if round_.tee_set_obj:
                    chs = sorted(round_.tee_set_obj.course_holes.all(), key=lambda ch: ch.id)
                    course_hole_map = {i + 1: ch for i, ch in enumerate(chs)}

                sg_putting_data = strokes_gained_putting(holes)
                sg_off_tee      = round(strokes_gained_off_tee(holes, course_hole_map), 3)
                sg_approach     = round(strokes_gained_approach(holes), 3)
                sg_atg          = round(strokes_gained_around_green(holes), 3)
                sg_putting_val  = round(sg_putting_data['total'], 3)
                sg_total        = round(sg_off_tee + sg_approach + sg_atg + sg_putting_val, 3)

                if dry_run:
                    print(
                        f"  [{i:>4}/{total}] round {round_.id:>5} "
                        f"({round_.date_played})  "
                        f"OTT={sg_off_tee:+.2f}  "
                        f"APP={sg_approach:+.2f}  "
                        f"ATG={sg_atg:+.2f}  "
                        f"PUTT={sg_putting_val:+.2f}  "
                        f"TOTAL={sg_total:+.2f}"
                    )
                else:
                    round_.sg_off_tee  = sg_off_tee
                    round_.sg_approach = sg_approach
                    round_.sg_atg      = sg_atg
                    round_.sg_putting  = sg_putting_val
                    round_.sg_total    = sg_total

                    if clear_cache and round_.report:
                        round_.report.insights_json  = None
                        round_.report.narrative_text = None

                    # Commit in batches for efficiency
                    if i % BATCH_SIZE == 0 or i == total:
                        db.session.commit()
                        print(f"  [{i:>4}/{total}] committed batch (last round id={round_.id})")

                updated += 1

            except Exception as exc:
                db.session.rollback()
                print(f"  [{i:>4}/{total}] round {round_.id:>5} — ERROR: {exc}")
                errors += 1

        if not dry_run:
            db.session.commit()  # ensure any remainder is flushed

        noun = "would update" if dry_run else "updated"
        print(f"\nDone.  {noun}={updated}  skipped={skipped}  errors={errors}")
        if clear_cache and not dry_run:
            print("Stale Claude insights cleared — they will regenerate on next report view.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Recompute strokes gained for all completed rounds.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print computed SG values without writing to the database.',
    )
    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help='Also clear cached Claude insights so they regenerate with correct SG values.',
    )
    args = parser.parse_args()
    recompute(dry_run=args.dry_run, clear_cache=args.clear_cache)
