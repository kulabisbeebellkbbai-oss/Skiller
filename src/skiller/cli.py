from __future__ import annotations

import argparse
from pathlib import Path

from .server import DEFAULT_HOST, DEFAULT_PORT, create_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skiller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Run the Skiller MCP server.")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--data-dir", type=Path, default=Path("data"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        server = create_server(data_dir=args.data_dir, host=args.host, port=args.port)
        server.run(transport="streamable-http")


if __name__ == "__main__":
    main()

