#!/usr/bin/env python3
"""Timer-friendly Skiller learning lineage scan wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skiller.storage import SkillerStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--threshold", type=float, default=7.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--min-new-learnings", type=int, default=10)
    parser.add_argument("--max-age-hours", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    store = SkillerStore(args.data_dir)
    due = store.lineage_scan_due(
        min_new_learnings=args.min_new_learnings,
        max_age_hours=args.max_age_hours,
    )
    if not args.force and not due["due"]:
        print(json.dumps({"skipped": True, "due": due}, indent=2))
        return 0

    result = store.scan_learning_lineage(
        threshold=args.threshold,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(json.dumps({"skipped": False, "due": due, "result": result.model_dump(mode="json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
