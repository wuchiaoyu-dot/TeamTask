from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class TaskCandidate(BaseModel):
    task_title: str
    task_description: str | None = None
    project_name: str | None = None
    parent_task_title: str | None = None
    initiator: str
    assignee: str
    task_type: str | None = None
    workload_level: str | None = None
    deadline: date | None = None
    resource_keywords: list[str] = Field(default_factory=list)
    mentioned_resources: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class TaskCandidateExtraction(BaseModel):
    task_candidates: list[TaskCandidate] = Field(default_factory=list)
