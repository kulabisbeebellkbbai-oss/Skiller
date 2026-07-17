from __future__ import annotations

from pathlib import Path

import pytest

from skiller.models import Novelty, Outcome, SkillLearning, SkillRun
from skiller.server import create_server
from skiller.storage import SkillerStore


def test_capture_work_product_records_learning_and_writes_drafts(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    result = store.capture_work_product(
        SkillLearning(
            title="Verified MCP server loopback setup",
            summary="Use the MCP SDK FastMCP server with a loopback-only Streamable HTTP endpoint.",
            novelty=Novelty.NEW,
            outcome=Outcome.WORKED,
            skill_name="mcp-server-creator",
            task_context="Creating a local MCP service for Codex.",
            evidence=["pytest passed"],
            reusable_steps=["Bind FastMCP to 127.0.0.1", "Expose /mcp and /health"],
            guardrails=["Reject non-loopback host binds"],
            tags=["mcp", "loopback"],
            reliability_impact="Prevents unsafe wildcard binds.",
        )
    )

    assert result.learning.skill_name == "mcp-server-creator"
    assert {artifact.kind for artifact in result.artifacts} == {"skill", "memory"}
    for artifact in result.artifacts:
        assert Path(artifact.path).exists()
    assert "Reject non-loopback" in Path(result.artifacts[0].path).read_text(encoding="utf-8")


def test_recommend_skills_uses_learning_terms_and_reliability(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    store.capture_work_product(
        SkillLearning(
            title="Flash verified device inventory",
            summary="Before flashing ESP32 firmware, probe the board identity and update inventory.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="flash-verified-device-inventory",
            tags=["esp32", "firmware", "inventory"],
        ),
        create_drafts=False,
    )
    store.record_skill_run(
        SkillRun(
            skill_name="flash-verified-device-inventory",
            task="Flash ESP32 firmware after checking MAC address.",
            outcome=Outcome.WORKED,
        )
    )

    recommendations = store.recommend_skills("Need to flash esp32 firmware and record inventory", limit=3)

    assert recommendations
    assert recommendations[0].skill_name == "flash-verified-device-inventory"
    assert recommendations[0].reliability is not None
    assert recommendations[0].reliability.reliability == 1.0


def test_refresh_skill_catalog_indexes_existing_skills(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "markitdown-mcp"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: markitdown-mcp
description: Convert PDF, DOCX, and other documents to Markdown through the local MCP server.
---

# MarkItDown MCP

Use for PDF and document conversion.
""",
        encoding="utf-8",
    )
    store = SkillerStore(tmp_path / "data")

    result = store.refresh_skill_catalog([str(tmp_path / "skills")])
    recommendations = store.recommend_skills("convert a pdf document to markdown", limit=3)

    assert result.imported == 1
    assert recommendations
    assert recommendations[0].skill_name == "markitdown-mcp"
    assert recommendations[0].source == "catalog"
    assert recommendations[0].source_path.endswith("SKILL.md")


def test_propose_skill_update_surfaces_failed_guardrails(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    store.capture_work_product(
        SkillLearning(
            title="MCP client smoke failed without initialized data dir",
            summary="The server should initialize data paths before registering tools.",
            novelty=Novelty.FAILURE,
            outcome=Outcome.FAILED,
            skill_name="skiller-mcp",
            guardrails=["Initialize the store before accepting MCP tool calls."],
            reliability_impact="Avoid first-run failures on empty checkouts.",
        ),
        create_drafts=False,
    )

    profile = store.propose_skill_update("skiller-mcp")

    assert "Initialize the store before accepting MCP tool calls." in profile.suggested_guardrails
    assert "Avoid first-run failures on empty checkouts." in profile.suggested_guardrails


def test_server_rejects_non_loopback_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_server(data_dir=tmp_path, host="0.0.0.0")
