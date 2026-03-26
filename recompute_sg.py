#!/usr/bin/env python3
"""
Recompute and store all derived stats for every completed round.

Uses the shared compute_all_stats() utility in app/utils/round_stats.py,
which covers the same ground as the submission route — ensuring stored
values are always consistent with what the app computes on submission.

Stats updated
─────────────
  total_score / total_putts / gir_count / fairways_hit /
  fairways_available / penalties          (basic totals from hole data)

  sg_off_tee / sg_approach / sg_atg /
  sg_putting / sg_total                   (Strokes Gained — Broadie methodology)

  algo_version                            (set to CURRENT_ALGO_VERSION on success)

Stats NOT touched
─────────────────
  hc_differential  (handicap — depends on course rating/slope, not recomputed here)
  Raw hole data, scores, user data — never modified

Usage
─────
  python recompute_sg.py               # update all complete rounds
  python recompute_sg.py --stale-only  # only rounds with outdated algo_version
  python recompute_sg.py --dry-run     # print values without writing
  python recompute_sg.py --stale-only --dry-run
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models.round import Round
from app.utils.round_stats import compute_all_stats, CURRENT_ALGO_VERSION

BATCH_SIZE = 50


def recompute(dry_run: bool = False, stale_only: bool = False) -> None:
    app = create_app('production')

    with app.app_context():
        query = Round.query.filter_by(status='complete').order_by(Round.id)

        if stale_only:
            query = query.filter(
                db.or_(
                    Round.algo_version.is_(None),
                    Round.algo_version < CURRENT_ALGO_VERSION,
                )
            )

        rounds = query.all()
        total  = len(rounds)
        mode   = 'STALE-ONLY' if stale_only else 'ALL'
        print(f'Found {total} complete round(s) to process ({mode}).')
        if dry_run:
            print('DRY RUN — no writes will occur.\n')

        updated = skipped = errors = 0

        for i, round_ in enumerate(rounds, 1):
            try:
                # Peek at hole data for the dry-run display without triggering
                # the full compute (we call compute_all_stats after)
                holes = round_.holes.order_by('hole_number').all()

                if not holes:
                    print(f'  [{i:>4}/{total}] round {round_.id:>5} — no holes, skipping')
                    skipped += 1
                    continue

                if dry_run:
                    # Build a temporary view of what compute_all_stats would store
                    from app.utils.round_stats import build_course_hole_map
                    from app.utils.strokes_gained import (
                        strokes_gained_putting,
                        strokes_gained_off_tee,
                        strokes_gained_approach,
                        strokes_gained_around_green,
                    )
                    chm     = build_course_hole_map(round_)
                    sg_putt = strokes_gained_putting(holes)
                    sg_ott  = strokes_gained_off_tee(holes, chm)
                    sg_app  = strokes_gained_approach(holes)
                    sg_atg  = strokes_gained_around_green(holes)
                    sg_tot  = sg_ott + sg_app + sg_atg + sg_putt['total']
                    gir     = sum(1 for h in holes if h.gir)
                    fw_h    = [h for h in holes if h.par in (4, 5)]
                    fw_hit  = sum(1 for h in fw_h if h.tee_shot == 'fairway')
                    putts   = sum(h.putts for h in holes if h.putts is not None)
                    print(
                        f'  [{i:>4}/{total}] round {round_.id:>5} '
                        f'({round_.date_played})  '
                        f'v{round_.algo_version or "?"}->v{CURRENT_ALGO_VERSION}  '
                        f'GIR={gir}  FW={fw_hit}/{len(fw_h)}  Putts={putts}  '
                        f'OTT={sg_ott:+.2f}  APP={sg_app:+.2f}  '
                        f'ATG={sg_atg:+.2f}  PUTT={sg_putt["total"]:+.2f}  '
                        f'TOTAL={sg_tot:+.2f}'
                    )
                else:
                    ok = compute_all_stats(round_)
                    if not ok:
                        skipped += 1
                        continue

                    if i % BATCH_SIZE == 0 or i == total:
                        db.session.commit()
                        print(f'  [{i:>4}/{total}] committed batch (last round id={round_.id})')

                updated += 1

            except Exception as exc:
                db.session.rollback()
                print(f'  [{i:>4}/{total}] round {round_.id:>5} — ERROR: {exc}')
                errors += 1

        if not dry_run:
            db.session.commit()

        noun = 'would update' if dry_run else 'updated'
        print(f'\nDone.  {noun}={updated}  skipped={skipped}  errors={errors}')
        if not dry_run and updated:
            print(f'All processed rounds now at algo_version={CURRENT_ALGO_VERSION}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Recompute all derived stats for completed rounds.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print computed values without writing to the database.',
    )
    parser.add_argument(
        '--stale-only',
        action='store_true',
        help='Only process rounds where algo_version < CURRENT_ALGO_VERSION.',
    )
    args = parser.parse_args()
    recompute(dry_run=args.dry_run, stale_only=args.stale_only)
