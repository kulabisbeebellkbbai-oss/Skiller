from __future__ import annotations

import argparse
import json
from pathlib import Path

from .server import DEFAULT_HOST, DEFAULT_PORT, create_server
from .storage import SkillerStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skiller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Run the Skiller MCP server.")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--data-dir", type=Path, default=Path("data"))
    scan = subparsers.add_parser("scan-lineage", help="Scan learning records and infer related chains.")
    scan.add_argument("--data-dir", type=Path, default=Path("data"))
    scan.add_argument("--threshold", type=float, default=7.0)
    scan.add_argument("--limit", type=int, default=100)
    scan.add_argument("--apply", action="store_true", help="Persist inferred lineage links.")
    scan.add_argument("--min-new-learnings", type=int, default=10)
    scan.add_argument("--max-age-hours", type=int, default=24)
    scan.add_argument("--force", action="store_true", help="Run even if the periodic due check says to skip.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        server = create_server(data_dir=args.data_dir, host=args.host, port=args.port)
        server.run(transport="streamable-http")
    if args.command == "scan-lineage":
        store = SkillerStore(args.data_dir)
        due = store.lineage_scan_due(
            min_new_learnings=args.min_new_learnings,
            max_age_hours=args.max_age_hours,
        )
        if not args.force and not due["due"]:
            print(json.dumps({"skipped": True, "due": due}, indent=2))
            return
        result = store.scan_learning_lineage(
            threshold=args.threshold,
            limit=args.limit,
            dry_run=not args.apply,
        )
        print(json.dumps({"skipped": False, "due": due, "result": result.model_dump(mode="json")}, indent=2))


if __name__ == "__main__":
    main()
