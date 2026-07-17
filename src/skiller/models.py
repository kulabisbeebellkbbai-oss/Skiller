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

    @field_validator("skill_name")
    @classmethod
    def normalize_skill_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().replace(" ", "-")
        return normalized or None

    @field_validator("evidence", "files_changed", "reusable_steps", "guardrails", "tags")
    @classmethod
    def strip_lists(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class SkillRun(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    skill_name: str = Field(min_length=2, max_length=120)
    task: str = Field(min_length=3, max_length=2000)
    outcome: Outcome
    failure_mode: str = Field(default="", max_length=1000)
    checks_used: list[str] = Field(default_factory=list, max_length=40)
    notes: str = Field(default="", max_length=2000)

    @field_validator("skill_name")
    @classmethod
    def normalize_skill_name(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")

    @field_validator("checks_used")
    @classmethod
    def strip_checks(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class DraftArtifact(BaseModel):
    kind: Literal["skill", "memory"]
    path: str


class CaptureResult(BaseModel):
    learning: SkillLearning
    artifacts: list[DraftArtifact]
    message: str


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
    reliability: ReliabilitySummary | None = None


class SkillProfile(BaseModel):
    skill_name: str
    learnings: list[SkillLearning]
    reliability: ReliabilitySummary
    suggested_guardrails: list[str]
    draft_paths: list[str]


JsonDict = dict[str, Any]

