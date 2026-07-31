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


def test_recommend_skills_records_guidance_event_and_context(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    learning = store.capture_work_product(
        SkillLearning(
            title="Approval guard before hook edits",
            summary="Hook updates require scope verification and user hook trust.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="codex-scope-manager",
            guardrails=["Before changing hooks, verify the user-level destination and run /hooks."],
            reliability_impact="Prevents durable hook edits in the wrong Codex scope.",
            tags=["hooks", "scope"],
        ),
        create_drafts=False,
    ).learning

    recommendations = store.recommend_skills(
        "Need to update Codex hooks in the right scope",
        thread_id="thread-guidance",
    )
    bundle = store.get_thread_guidance_context(thread_id="thread-guidance")

    assert recommendations
    assert bundle.event.thread_id == "thread-guidance"
    assert learning.id in bundle.event.guidance_learning_ids
    assert "Before changing hooks, verify the user-level destination and run /hooks." in bundle.event.guardrails


def test_evaluate_guidance_adherence_detects_followed_ignored_and_violated(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    learning = store.capture_work_product(
        SkillLearning(
            title="Hook approval workflow",
            summary="Use codex-scope-manager and verify approval before changing hooks.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.PARTIAL,
            skill_name="codex-scope-manager",
            guardrails=["Before changing hooks, verify approval and run /hooks."],
            reliability_impact="Skipping hook approval causes untrusted durable behavior.",
            tags=["hooks", "approval"],
        ),
        create_drafts=False,
    ).learning
    store.recommend_skills("Change Codex hooks safely", thread_id="thread-audit")

    followed = store.evaluate_guidance_adherence(
        thread_id="thread-audit",
        action_summary="Used codex-scope-manager, verified approval, and ran /hooks.",
        used_skill_names=["codex-scope-manager"],
        used_learning_ids=[learning.id],
        checks_performed=["approval verified", "/hooks reviewed"],
    )
    ignored = store.evaluate_guidance_adherence(
        thread_id="thread-audit",
        action_summary="Implemented an unrelated display change.",
    )
    violated = store.evaluate_guidance_adherence(
        thread_id="thread-audit",
        action_summary="Changed hooks immediately without approval evidence.",
    )

    assert followed.status == "followed"
    assert ignored.status == "ignored"
    assert violated.status == "violated"
    assert violated.violations


def test_effectiveness_review_tracks_attributed_guidance_and_recurring_pitfalls(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    store.record_skill_run(
        SkillRun(
            skill_name="safe-workflow",
            task="Use the corrected workflow.",
            outcome=Outcome.WORKED,
            guidance_learning_ids=["learning.corrected"],
            pitfalls_avoided=["Skipped required approval"],
        )
    )
    store.record_skill_run(
        SkillRun(
            skill_name="safe-workflow",
            task="A later run repeated the pitfall.",
            outcome=Outcome.FAILED,
            failure_mode="Skipped required approval",
            guidance_learning_ids=["learning.corrected"],
        )
    )

    review = store.review_effectiveness()

    assert review.attributed_runs == 2
    assert review.guidance_worked == 1
    assert review.guidance_regressed == 1
    assert review.pitfalls_avoided == 1
    assert review.recurring_pitfalls == ["Skipped required approval"]
    assert review.schedule_mode == "hybrid"
    assert (tmp_path / "effectiveness_reviews.jsonl").exists()


def test_effectiveness_review_prefers_time_fallback_when_activity_is_quiet(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    store.initialize()
    store.review_effectiveness()

    review = store.review_effectiveness()

    assert review.new_learnings_since_review == 0
    assert review.new_runs_since_review == 0
    assert review.schedule_mode == "time_based"
    assert review.recommended_check_minutes == 360


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


def test_scan_learning_lineage_links_related_iterations(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    root = store.capture_work_product(
        SkillLearning(
            title="Project MCP config initializes browser tools",
            summary="Configure required Playwright MCP in project config for browser verification.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="codex-scope-manager",
            tags=["playwright", "mcp", "tool-catalog"],
            files_changed=["/home/god/Documents/Codex Workspace/DonutHole/.codex/config.toml"],
            guardrails=["Restart the session before claiming the tool catalog is available."],
        ),
        create_drafts=False,
    ).learning
    intermediate = store.capture_work_product(
        SkillLearning(
            title="Project MCP config does not control managed runner catalogs",
            summary="Roadex-managed turns require runner capability profile injection for Playwright MCP.",
            novelty=Novelty.FAILURE,
            outcome=Outcome.PARTIAL,
            skill_name="codex-scope-manager",
            tags=["roadex", "playwright", "mcp", "tool-catalog"],
            files_changed=["/home/god/Documents/Codex Workspace/Roadex/src/server/runnerCapabilityProfile.ts"],
        ),
        create_drafts=False,
    ).learning
    correction = store.capture_work_product(
        SkillLearning(
            title="Correct managed runner Playwright MCP profile",
            summary="Fix Roadex managed runner tool catalog by injecting bounded Playwright MCP.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="codex-scope-manager",
            tags=["roadex", "playwright", "mcp", "tool-catalog"],
            files_changed=["/home/god/Documents/Codex Workspace/Roadex/src/server/runnerCapabilityProfile.ts"],
            guardrails=["Verify from a new managed turn, not just a local CLI session."],
        ),
        create_drafts=False,
    ).learning

    dry_run = store.scan_learning_lineage(threshold=7.0, dry_run=True)
    applied = store.scan_learning_lineage(threshold=7.0, dry_run=False)
    updated_root = store.get_learning(root.id)
    updated_intermediate = store.get_learning(intermediate.id)
    updated_correction = store.get_learning(correction.id)

    assert dry_run.candidates >= 1
    assert dry_run.applied == 0
    assert applied.applied >= 1
    assert updated_root is not None
    assert updated_intermediate is not None
    assert updated_correction is not None
    assert correction.id in updated_intermediate.correction_learning_ids
    assert updated_correction.corrects_learning_ids
    assert "Verify from a new managed turn, not just a local CLI session." in store.propose_skill_update(
        "codex-scope-manager"
    ).suggested_guardrails


def test_recommend_skills_uses_linked_follow_on_terms(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    root = store.capture_work_product(
        SkillLearning(
            title="Project MCP startup",
            summary="Required project MCP configuration ensures tool catalog initialization.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="codex-scope-manager",
            tags=["mcp"],
        ),
        create_drafts=False,
    ).learning
    store.capture_work_product(
        SkillLearning(
            title="Managed runner Playwright correction",
            summary="Roadex managed runner catalogs need server-side Playwright profile injection.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="codex-scope-manager",
            corrects_learning_ids=[root.id],
            tags=["roadex", "playwright"],
        ),
        create_drafts=False,
    )

    recommendations = store.recommend_skills("roadex playwright managed runner profile", limit=3)

    assert recommendations
    assert recommendations[0].skill_name == "codex-scope-manager"


def test_lineage_scan_due_uses_new_learning_or_age_threshold(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    for index in range(2):
        store.capture_work_product(
            SkillLearning(
                title=f"Learning {index}",
                summary="A small captured learning for due-check testing.",
                novelty=Novelty.VARIANT,
                outcome=Outcome.WORKED,
                skill_name="skiller-mcp",
            ),
            create_drafts=False,
        )

    initial = store.lineage_scan_due(min_new_learnings=3, max_age_hours=24)
    store.scan_learning_lineage(dry_run=True)
    skipped = store.lineage_scan_due(min_new_learnings=3, max_age_hours=24)

    assert initial["due"] is True
    assert initial["reason"] == "no previous lineage scan"
    assert skipped["due"] is False
    assert skipped["new_learnings"] == 0


def test_scan_memory_records_links_existing_learning(tmp_path: Path) -> None:
    memory_root = tmp_path / "memories"
    memory_root.mkdir()
    (memory_root / "MEMORY.md").write_text(
        """# Task Group: Skiller hook diagnostics

## Reusable knowledge

- skiller-mcp should verify hook diagnostics before changing repeated-warning guards. Before closing the task, run the exact hook prompt through the installed hook and verify the MCP evidence path.
""",
        encoding="utf-8",
    )
    store = SkillerStore(tmp_path / "data")
    learning = store.capture_work_product(
        SkillLearning(
            title="Skiller hook diagnostics",
            summary="The skiller-mcp hook diagnostic workflow verifies repeated warning guards with exact hook prompts.",
            novelty=Novelty.GUARDRAIL,
            outcome=Outcome.WORKED,
            skill_name="skiller-mcp",
            tags=["hooks", "diagnostics"],
        ),
        create_drafts=False,
    ).learning

    dry_run = store.scan_memory_records(memory_root=str(memory_root), threshold=5.0, dry_run=True)
    applied = store.scan_memory_records(memory_root=str(memory_root), threshold=5.0, dry_run=False)
    updated = store.get_learning(learning.id)
    context = store.get_learning_memory_context(learning.id, memory_root=str(memory_root))

    assert dry_run.candidates == 1
    assert dry_run.linked == 0
    assert applied.linked == 1
    assert updated is not None
    assert updated.memory_record_ids
    assert context["memories"]
    assert context["missing_memory_record_ids"] == []


def test_scan_memory_records_creates_learning_from_skill_memory(tmp_path: Path) -> None:
    memory_root = tmp_path / "memories"
    memory_root.mkdir()
    (memory_root / "MEMORY.md").write_text(
        """# Task Group: Scope manager approval guardrail

## Reusable knowledge

- codex-scope-manager must keep hook updates in the right Codex scope. Before changing hooks, verify the user-level destination and tell the user to run /hooks after install.
""",
        encoding="utf-8",
    )
    skill_dir = tmp_path / "skills" / "codex-scope-manager"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: codex-scope-manager
description: Manage durable Codex hooks, skills, memories, and installation scopes.
---
""",
        encoding="utf-8",
    )
    store = SkillerStore(tmp_path / "data")
    store.refresh_skill_catalog([str(tmp_path / "skills")])

    result = store.scan_memory_records(memory_root=str(memory_root), threshold=5.0, dry_run=False)
    learnings = store.list_recent_learnings(skill_name="codex-scope-manager")

    assert result.created == 1
    assert learnings
    assert learnings[0].memory_record_ids
    assert "memory-derived" in learnings[0].tags


def test_overseer_guidance_requires_passed_security_review(tmp_path: Path) -> None:
    store = SkillerStore(tmp_path)
    blocked = store.record_overseer_guidance(
        title="Enable private search without review",
        recommendation="Enable private memory search before the security review.",
        security_review_status="pending",
        action="enable_private_memory_search",
    )
    passed = store.record_overseer_guidance(
        title="Raise scan limit after review",
        recommendation="A reviewed configuration change can raise the bounded scan limit.",
        security_review_status="passed",
        security_review_evidence=["Overseer Odo review passed for bounded config-only change."],
        action="set_memory_scan_limit",
        value="150",
    )

    result = store.apply_overseer_guidance()

    assert [item["id"] for item in result["blocked"]] == [blocked.id]
    assert [item["id"] for item in result["applied"]] == [passed.id]
    assert result["config"]["limit"] == 150
    assert result["config"]["include_private_search"] is False


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
