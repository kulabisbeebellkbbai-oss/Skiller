#!/usr/bin/env python3
"""Review Skiller effectiveness and run lineage maintenance when adaptively due."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skiller.storage import SkillerStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--threshold", type=float, default=15.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    store = SkillerStore(args.data_dir)
    review = store.review_effectiveness()
    due = store.lineage_scan_due(
        min_new_learnings=review.recommended_new_learning_threshold,
        max_age_hours=review.recommended_max_age_hours,
    )
    scan = None
    if due["due"]:
        scan = store.scan_learning_lineage(
            threshold=args.threshold,
            limit=args.limit,
            dry_run=not args.apply,
        ).model_dump(mode="json")
    print(
        json.dumps(
            {
                "review": review.model_dump(mode="json"),
                "lineage_due": due,
                "lineage_scan": scan,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
