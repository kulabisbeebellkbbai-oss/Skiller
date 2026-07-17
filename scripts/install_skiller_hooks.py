#!/usr/bin/env python3
"""Install Skiller MCP service, skill, and hooks into the current Codex home."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODEX_HOME = Path.home() / ".codex"
HOOK_NAME = "skiller_mcp_guard.py"
SERVICE_NAME = "skiller-mcp.service"


def load_hooks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"hooks": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_suffix(path.suffix + f".{stamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def command_exists(hooks: list[dict[str, Any]], command: str) -> bool:
    return any(item.get("command") == command for item in hooks)


def merge_hook(config: dict[str, Any], event: str, command: str, status: str) -> None:
    hooks_root = config.setdefault("hooks", {})
    groups = hooks_root.setdefault(event, [])
    if not groups:
        groups.append({"hooks": []})
    group = groups[0]
    hook_list = group.setdefault("hooks", [])
    hook_list[:] = [item for item in hook_list if "skiller_mcp_guard.py" not in str(item.get("command", ""))]
    if not command_exists(hook_list, command):
        hook_list.append({
            "type": "command",
            "command": command,
            "timeout": 30,
            "statusMessage": status,
        })


def write_hooks(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def install_service(service_dir: Path, python_bin: Path, data_dir: Path) -> Path:
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / SERVICE_NAME
    service_text = f"""[Unit]
Description=Skiller MCP server

[Service]
Type=simple
WorkingDirectory={PROJECT_ROOT}
ExecStart="{python_bin}" -m skiller.cli serve --host 127.0.0.1 --port 8794 --data-dir "{data_dir}"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    service_path.write_text(service_text, encoding="utf-8")
    return service_path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-service", action="store_true")
    args = parser.parse_args()

    codex_home = args.codex_home.expanduser().resolve()
    hooks_dir = codex_home / "hooks"
    skills_dir = codex_home / "skills" / "skiller-mcp"
    hooks_json = codex_home / "hooks.json"
    hook_target = hooks_dir / HOOK_NAME
    python_bin = PROJECT_ROOT / ".venv" / "bin" / "python"
    data_dir = PROJECT_ROOT / "data"

    config = load_hooks(hooks_json)
    command_base = f"python3 {hook_target} --from-stdin"
    merge_hook(config, "UserPromptSubmit", f"{command_base} --preflight", "Checking Skiller MCP route")
    merge_hook(config, "Stop", f"{command_base} --stop-check", "Checking Skiller MCP evidence")

    service_path = Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME

    if args.dry_run:
        print(json.dumps({
            "codex_home": str(codex_home),
            "hook_target": str(hook_target),
            "skill_target": str(skills_dir),
            "hooks_json": str(hooks_json),
            "service_path": str(service_path),
            "would_install_service": not args.skip_service,
        }, indent=2))
        return 0

    hooks_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / "scripts" / HOOK_NAME, hook_target)
    hook_target.chmod(0o755)
    if skills_dir.exists():
        shutil.rmtree(skills_dir)
    shutil.copytree(PROJECT_ROOT / ".codex" / "skills" / "skiller-mcp", skills_dir)

    backup_path = backup(hooks_json)
    write_hooks(hooks_json, config)

    service_result = None
    if not args.skip_service:
        install_service(service_path.parent, python_bin, data_dir)
        service_result = {
            "daemon_reload": run(["systemctl", "--user", "daemon-reload"]).returncode,
            "enable": run(["systemctl", "--user", "enable", "--now", SERVICE_NAME]).returncode,
        }

    print(json.dumps({
        "installed_hook": str(hook_target),
        "installed_skill": str(skills_dir),
        "hooks_json": str(hooks_json),
        "backup": str(backup_path) if backup_path else None,
        "service": str(service_path) if not args.skip_service else None,
        "service_result": service_result,
        "review": "Run /hooks and trust the changed Skiller hook entries.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
