#!/usr/bin/env python3
"""Timer-friendly Skiller AI-memory association scan wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skiller.storage import SkillerStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--memory-root", default="")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-new-records", type=int, default=5)
    parser.add_argument("--max-age-hours", type=int, default=24)
    parser.add_argument("--include-private-search", action="store_true")
    parser.add_argument("--private-query", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    store = SkillerStore(args.data_dir)
    guidance = store.apply_overseer_guidance()
    due = store.memory_scan_due(
        min_new_records=args.min_new_records,
        max_age_hours=args.max_age_hours,
        memory_root=args.memory_root,
    )
    scan = None
    if args.force or due["due"]:
        scan = store.scan_memory_records(
            memory_root=args.memory_root,
            include_private_search=args.include_private_search or None,
            private_queries=args.private_query,
            threshold=args.threshold,
            limit=args.limit,
            dry_run=not args.apply,
        ).model_dump(mode="json")
    print(json.dumps({"guidance": guidance, "memory_due": due, "memory_scan": scan}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
