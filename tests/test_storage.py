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


def test_capture_correction_backfills_original_learning_lineage(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    original = store.capture_work_product(
        SkillLearning(
            title="Project MCP config was scoped too narrowly",
            summary="A local project MCP config did not affect managed runner tool catalogs.",
            novelty=Novelty.FAILURE,
            outcome=Outcome.PARTIAL,
            skill_name="codex-scope-manager",
            guardrails=["Do not use local CLI smoke as managed-runner proof."],
        ),
        create_drafts=False,
    ).learning
    correction = store.capture_work_product(
        SkillLearning(
            title="Managed runner profile carries Playwright",
            summary="Inject the required Playwright MCP into the managed runner capability profile.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="codex-scope-manager",
            corrects_learning_ids=[original.id],
            thread_ids=["thread-1"],
            guardrails=["Verify from a managed turn before closing the task."],
        ),
        create_drafts=False,
    ).learning

    updated_original = store.get_learning(original.id)
    lineage = store.get_learning_lineage(original.id)
    correction_lineage = store.get_learning_lineage(correction.id)
    profile = store.propose_skill_update("codex-scope-manager")

    assert updated_original is not None
    assert updated_original.correction_learning_ids == [correction.id]
    assert updated_original.child_learning_ids == [correction.id]
    assert updated_original.thread_ids == ["thread-1"]
    assert correction.root_learning_id == original.id
    assert correction.parent_learning_ids == [original.id]
    assert lineage["corrections"] == [correction]
    assert correction_lineage["root"] == updated_original
    assert "Verify from a managed turn before closing the task." in profile.suggested_guardrails


def test_link_learning_correction_repairs_existing_records(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    original = store.capture_work_product(
        SkillLearning(
            title="Original workflow failed",
            summary="The first process captured an incomplete implementation path.",
            novelty=Novelty.FAILURE,
            outcome=Outcome.FAILED,
            skill_name="skiller-mcp",
        ),
        create_drafts=False,
    ).learning
    correction = store.capture_work_product(
        SkillLearning(
            title="Follow-on correction worked",
            summary="The second process fixed the missing step.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="skiller-mcp",
        ),
        create_drafts=False,
    ).learning

    linked = store.link_learning_correction(
        correction.id,
        [original.id],
        thread_id="thread-2",
        root_learning_id=original.id,
    )
    updated_original = store.get_learning(original.id)
    updated_correction = store.get_learning(correction.id)

    assert [item.id for item in linked] == [correction.id, original.id]
    assert updated_original is not None
    assert updated_correction is not None
    assert updated_original.correction_learning_ids == [correction.id]
    assert updated_original.thread_ids == ["thread-2"]
    assert updated_correction.corrects_learning_ids == [original.id]
    assert updated_correction.root_learning_id == original.id
    assert updated_correction.thread_ids == ["thread-2"]


def test_non_updatable_skill_blocks_draft_without_user_approval(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    policy = store.set_skill_policy("critical-skill", updatable=False, reason="Requires maintainer review.")

    result = store.capture_work_product(
        SkillLearning(
            title="Critical skill update",
            summary="This learning should be captured but not drafted without approval.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="critical-skill",
        )
    )

    assert policy.updatable is False
    assert result.update_blocked is True
    assert result.policy is not None
    assert result.policy.skill_name == "critical-skill"
    assert result.artifacts == []
    assert not list((tmp_path / "drafts").glob("*/skill/critical-skill/SKILL.md"))


def test_non_updatable_skill_allows_draft_with_user_approval(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    store.set_skill_policy("critical-skill", updatable=False, reason="Requires maintainer review.")

    result = store.capture_work_product(
        SkillLearning(
            title="Critical skill approved update",
            summary="This learning can draft because explicit user approval was provided.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="critical-skill",
        ),
        user_approved_update=True,
    )

    assert result.update_blocked is False
    assert {artifact.kind for artifact in result.artifacts} == {"skill", "memory"}


def test_propose_skill_update_hides_guardrails_for_protected_skill_without_approval(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    store.set_skill_policy("critical-skill", updatable=False, reason="Requires maintainer review.")
    store.capture_work_product(
        SkillLearning(
            title="Critical failure guardrail",
            summary="A protected skill failure should not become an update proposal automatically.",
            novelty=Novelty.FAILURE,
            outcome=Outcome.FAILED,
            skill_name="critical-skill",
            guardrails=["Do not change this without approval."],
        ),
        create_drafts=False,
    )

    blocked = store.propose_skill_update("critical-skill")
    approved = store.propose_skill_update("critical-skill", user_approved_update=True)

    assert blocked.policy is not None
    assert blocked.policy.updatable is False
    assert blocked.suggested_guardrails == []
    assert approved.suggested_guardrails == ["Do not change this without approval."]


def test_server_rejects_non_loopback_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        create_server(data_dir=tmp_path, host="0.0.0.0")
