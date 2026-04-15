"""Pydantic v2 schema for structured LLM triage output."""
from typing import Optional
from pydantic import BaseModel, Field


class TriageOutput(BaseModel):
    """Structured triage decision produced by the LLM step."""

    duplicate_of: Optional[int] = Field(
        default=None,
        description="GitHub issue number of the duplicate, or null if not a duplicate",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Suggested label names to apply to the issue (max 5)",
    )
    relevant_files: list[str] = Field(
        default_factory=list,
        description="File paths most relevant to this issue (max 10)",
    )
    suggested_assignees: list[str] = Field(
        default_factory=list,
        description="GitHub usernames to suggest as assignees",
    )
    confidence: str = Field(
        default="medium",
        description="Confidence level: low | medium | high",
    )
    reasoning: str = Field(
        default="",
        description="2-4 sentence explanation of the triage decision",
    )
