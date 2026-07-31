from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class Novelty(str, Enum):
    NEW = "new"
    VARIANT = "variant"
    GUARDRAIL = "guardrail"
    FAILURE = "failure"


class Outcome(str, Enum):
    WORKED = "worked"
    FAILED = "failed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class SkillLearning(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    title: str = Field(min_length=3, max_length=160)
    summary: str = Field(min_length=10, max_length=4000)
    novelty: Novelty
    outcome: Outcome = Outcome.UNKNOWN
    skill_name: str | None = Field(default=None, max_length=120)
    task_context: str = Field(default="", max_length=4000)
    evidence: list[str] = Field(default_factory=list, max_length=25)
    files_changed: list[str] = Field(default_factory=list, max_length=100)
    reusable_steps: list[str] = Field(default_factory=list, max_length=50)
    guardrails: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=40)
    reliability_impact: str = Field(default="", max_length=2000)
    thread_ids: list[str] = Field(default_factory=list, max_length=20)
    root_learning_id: str = Field(default="", max_length=80)
    parent_learning_ids: list[str] = Field(default_factory=list, max_length=20)
    corrects_learning_ids: list[str] = Field(default_factory=list, max_length=20)
    child_learning_ids: list[str] = Field(default_factory=list, max_length=100)
    correction_learning_ids: list[str] = Field(default_factory=list, max_length=100)
    memory_record_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("skill_name")
    @classmethod
    def normalize_skill_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace(" ", "-")
        return normalized or None

    @field_validator(
        "evidence",
        "files_changed",
        "reusable_steps",
        "guardrails",
        "tags",
        "thread_ids",
        "parent_learning_ids",
        "corrects_learning_ids",
        "child_learning_ids",
        "correction_learning_ids",
        "memory_record_ids",
    )
    @classmethod
    def strip_lists(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))

    @field_validator("root_learning_id")
    @classmethod
    def strip_root_learning_id(cls, value: str) -> str:
        return value.strip()


class SkillRun(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    skill_name: str = Field(min_length=2, max_length=120)
    task: str = Field(min_length=3, max_length=2000)
    outcome: Outcome
    failure_mode: str = Field(default="", max_length=1000)
    checks_used: list[str] = Field(default_factory=list, max_length=40)
    notes: str = Field(default="", max_length=2000)
    guidance_learning_ids: list[str] = Field(default_factory=list, max_length=50)
    pitfalls_avoided: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("skill_name")
    @classmethod
    def normalize_skill_name(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @field_validator("checks_used", "guidance_learning_ids", "pitfalls_avoided")
    @classmethod
    def strip_checks(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class EffectivenessReview(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    runs_reviewed: int
    attributed_runs: int
    guidance_worked: int
    guidance_regressed: int
    pitfalls_avoided: int
    recurring_pitfalls: list[str] = Field(default_factory=list, max_length=50)
    unattributed_runs: int
    effectiveness: float | None = None
    schedule_mode: Literal["record_based", "time_based", "hybrid"]
    recommended_check_minutes: int
    recommended_new_learning_threshold: int
    recommended_max_age_hours: int
    new_learnings_since_review: int
    new_runs_since_review: int


class SkillCatalogEntry(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    source_path: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=40)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @field_validator("tags")
    @classmethod
    def strip_tags(cls, value: list[str]) -> list[str]:
        return [item.strip().lower() for item in value if item and item.strip()]


class CatalogRefreshResult(BaseModel):
    scanned_roots: list[str]
    imported: int
    skipped: int
    entries: list[SkillCatalogEntry]


class SkillPolicy(BaseModel):
    skill_name: str = Field(min_length=2, max_length=120)
    updatable: bool = True
    reason: str = Field(default="", max_length=2000)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("skill_name")
    @classmethod
    def normalize_skill_name(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")


class DraftArtifact(BaseModel):
    kind: Literal["skill", "memory"]
    path: str


class CaptureResult(BaseModel):
    learning: SkillLearning
    artifacts: list[DraftArtifact]
    message: str
    update_blocked: bool = False
    policy: SkillPolicy | None = None


class ReliabilitySummary(BaseModel):
    skill_name: str
    total_runs: int
    worked: int
    failed: int
    partial: int
    unknown: int
    reliability: float | None
    common_failure_modes: list[str]


class SkillRecommendation(BaseModel):
    skill_name: str
    score: float
    reason: str
    source: Literal["captured_learning", "catalog", "combined"] = "captured_learning"
    description: str = ""
    source_path: str = ""
    updatable: bool = True
    reliability: ReliabilitySummary | None = None


class SkillProfile(BaseModel):
    skill_name: str
    catalog_entry: SkillCatalogEntry | None = None
    policy: SkillPolicy | None = None
    learnings: list[SkillLearning]
    reliability: ReliabilitySummary
    suggested_guardrails: list[str]
    draft_paths: list[str]


class LineageLinkCandidate(BaseModel):
    parent_learning_id: str
    child_learning_id: str
    root_learning_id: str = ""
    score: float
    reasons: list[str] = Field(default_factory=list, max_length=20)
    applied: bool = False

    @field_validator("reasons")
    @classmethod
    def strip_reasons(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))


class LineageScanResult(BaseModel):
    scanned: int
    candidates: int
    applied: int
    threshold: float
    dry_run: bool
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    links: list[LineageLinkCandidate] = Field(default_factory=list, max_length=500)


class MemoryLinkCandidate(BaseModel):
    memory_record_id: str
    memory_source: str
    memory_title: str
    learning_id: str = ""
    skill_name: str = ""
    action: Literal["link", "create_learning"]
    score: float
    reasons: list[str] = Field(default_factory=list, max_length=20)
    applied: bool = False

    @field_validator("reasons")
    @classmethod
    def strip_reasons(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))


class MemoryScanResult(BaseModel):
    scanned_memories: int
    scanned_learnings: int
    candidates: int
    linked: int
    created: int
    threshold: float
    dry_run: bool
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    links: list[MemoryLinkCandidate] = Field(default_factory=list, max_length=500)


class OverseerGuidance(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: str = Field(default="overseer", max_length=120)
    title: str = Field(min_length=3, max_length=160)
    recommendation: str = Field(min_length=10, max_length=4000)
    security_review_status: Literal["pending", "passed", "failed"] = "pending"
    security_review_evidence: list[str] = Field(default_factory=list, max_length=25)
    action: Literal[
        "add_memory_query",
        "set_memory_scan_threshold",
        "set_memory_scan_limit",
        "enable_private_memory_search",
        "disable_private_memory_search",
        "note_only",
    ] = "note_only"
    value: str = Field(default="", max_length=1000)
    applied: bool = False
    applied_at: str = ""

    @field_validator("security_review_evidence")
    @classmethod
    def strip_evidence(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))


JsonDict = dict[str, Any]
