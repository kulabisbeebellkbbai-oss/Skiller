from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from .models import (
    CaptureResult,
    CatalogRefreshResult,
    Outcome,
    SkillCatalogEntry,
    SkillLearning,
    SkillPolicy,
    SkillProfile,
    SkillRecommendation,
    SkillRun,
)
from .storage import SkillerStore


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8794


def create_server(data_dir: Path | None = None, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> FastMCP:
    if host != "127.0.0.1":
        raise ValueError("Skiller must bind to 127.0.0.1 unless a separate approved gateway plan exists.")

    store = SkillerStore(data_dir or Path(os.environ.get("SKILLER_DATA_DIR", "data")))
    store.initialize()
    mcp = FastMCP(
        "skiller",
        instructions=(
            "Capture reusable skill learnings, draft skill and memory artifacts, "
            "track reliability outcomes, and recommend relevant skills."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request):
        return JSONResponse({"status": "ok", "service": "skiller", "data_dir": str(store.data_dir)})

    @mcp.tool()
    def capture_work_product(
        title: str,
        summary: str,
        novelty: str,
        outcome: str = "unknown",
        skill_name: str | None = None,
        task_context: str = "",
        evidence: list[str] | None = None,
        files_changed: list[str] | None = None,
        reusable_steps: list[str] | None = None,
        guardrails: list[str] | None = None,
        tags: list[str] | None = None,
        reliability_impact: str = "",
        create_drafts: bool = True,
        user_approved_update: bool = False,
    ) -> CaptureResult:
        """Record a new, variant, guardrail, or failure learning and optionally draft skill/memory files."""
        learning = SkillLearning(
            title=title,
            summary=summary,
            novelty=novelty,
            outcome=outcome,
            skill_name=skill_name,
            task_context=task_context,
            evidence=evidence or [],
            files_changed=files_changed or [],
            reusable_steps=reusable_steps or [],
            guardrails=guardrails or [],
            tags=tags or [],
            reliability_impact=reliability_impact,
        )
        return store.capture_work_product(
            learning,
            create_drafts=create_drafts,
            user_approved_update=user_approved_update,
        )

    @mcp.tool()
    def record_skill_run(
        skill_name: str,
        task: str,
        outcome: str,
        failure_mode: str = "",
        checks_used: list[str] | None = None,
        notes: str = "",
    ):
        """Append reliability evidence for one skill invocation and return the updated summary."""
        run = SkillRun(
            skill_name=skill_name,
            task=task,
            outcome=Outcome(outcome),
            failure_mode=failure_mode,
            checks_used=checks_used or [],
            notes=notes,
        )
        return store.record_skill_run(run)

    @mcp.tool()
    def recommend_skills(task_description: str, limit: int = 5) -> list[SkillRecommendation]:
        """Rank captured skills that appear relevant to a future task."""
        return store.recommend_skills(task_description, limit=limit)

    @mcp.tool()
    def propose_skill_update(skill_name: str, user_approved_update: bool = False) -> SkillProfile:
        """Summarize recent variants and failures that should become skill guardrails."""
        return store.propose_skill_update(skill_name, user_approved_update=user_approved_update)

    @mcp.tool()
    def list_recent_learnings(limit: int = 10, skill_name: str | None = None) -> list[SkillLearning]:
        """List recent captured learnings, optionally filtered to one skill."""
        return store.list_recent_learnings(limit=limit, skill_name=skill_name)

    @mcp.tool()
    def get_skill_profile(skill_name: str) -> SkillProfile:
        """Return captured learnings, reliability, suggested guardrails, and draft paths for a skill."""
        return store.get_skill_profile(skill_name)

    @mcp.tool()
    def refresh_skill_catalog(root_paths: list[str] | None = None) -> CatalogRefreshResult:
        """Scan SKILL.md files into Skiller's recommendation catalog."""
        return store.refresh_skill_catalog(root_paths=root_paths)

    @mcp.tool()
    def list_skill_catalog(limit: int = 50, query: str = "") -> list[SkillCatalogEntry]:
        """List indexed skills, optionally filtered by query terms."""
        return store.list_skill_catalog(limit=limit, query=query)

    @mcp.tool()
    def set_skill_update_policy(skill_name: str, updatable: bool, reason: str = "") -> SkillPolicy:
        """Mark whether Skiller may draft updates for a skill without explicit user approval."""
        return store.set_skill_policy(skill_name=skill_name, updatable=updatable, reason=reason)

    @mcp.tool()
    def list_skill_update_policies() -> list[SkillPolicy]:
        """List skills with explicit update policies."""
        return store.list_skill_policies()

    return mcp
