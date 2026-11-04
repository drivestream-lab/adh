"""Typed projection of pinned Prayog workflow + skill index.

Node ids, purposes, forge actions, and skill ids are plain strings from YAML —
not frozen Python enums (ADR 0001).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ForgePolicyDocument(BaseModel):
    """Forge side-effects declared on a workflow node."""

    model_config = ConfigDict(extra="ignore")

    action: Optional[str] = Field(default=None, description="Forge action id from workflow YAML")
    draft: Optional[bool] = None
    commit_workspace: Optional[str] = Field(
        default=None,
        description="optional|required from skill nodes",
    )
    apply_labels: list[str] = Field(default_factory=list)
    remove_labels: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)


class WorkflowNodeDocument(BaseModel):
    """One node from workflow.yaml `nodes`."""

    model_config = ConfigDict(extra="ignore")

    node_id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1, description="skill|human-checkpoint|external-action|…")
    profile: Optional[str] = None
    dispatch: Optional[str] = Field(
        default=None,
        description="Absent → treat as manual per delivery-contract",
    )
    purpose: Optional[str] = None
    owner: Optional[str] = None
    provider: Optional[str] = None
    authorization: Optional[str] = None
    forge: Optional[ForgePolicyDocument] = None
    outcomes: dict[str, str] = Field(default_factory=dict)

    def effective_dispatch(self) -> str:
        raw = (self.dispatch or "").strip()
        return raw if raw else "manual"

    def is_human_checkpoint(self) -> bool:
        return self.type == "human-checkpoint"

    def is_skill(self) -> bool:
        return self.type == "skill"

    def is_external_action(self) -> bool:
        return self.type == "external-action"

    def is_terminal(self) -> bool:
        return self.type == "terminal"

    def requires_explicit_authorization(self) -> bool:
        return (self.authorization or "").strip() == "explicit"


class WorkflowDocument(BaseModel):
    """Root of prayog-skills/workflow.yaml."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    api_version: str = Field(default="", alias="apiVersion")
    kind: str = Field(default="")
    id: str = Field(default="")
    contract: str = Field(default="")
    entrypoints: dict[str, str] = Field(default_factory=dict)
    nodes: dict[str, WorkflowNodeDocument] = Field(default_factory=dict)


class SkillDescriptor(BaseModel):
    """Indexed from skills/**/SKILL.md frontmatter."""

    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(..., min_length=1)
    description: str = Field(default="")
    category: str = Field(default="", description="Parent folder under skills/")
    skill_md_path: str = Field(..., min_length=1)


class HarnessPinDocument(BaseModel):
    """Subset of .harness-pin.yaml needed for catalogue load."""

    model_config = ConfigDict(extra="ignore")

    profile: str = Field(default="")
    delivery_contract: str = Field(default="")
    agent_skills_ref: str = Field(
        default="",
        description="Pinned prayog-skills ref from agent_skills.ref",
    )


class CatalogueSnapshot(BaseModel):
    """Immutable load result for one process (or reload)."""

    model_config = ConfigDict(extra="forbid")

    pin: HarnessPinDocument
    workflow: WorkflowDocument
    skills: dict[str, SkillDescriptor] = Field(default_factory=dict)
    skills_root: str = Field(..., min_length=1)
    workflow_path: str = Field(..., min_length=1)

    def entrypoint(self, name: str) -> str:
        try:
            return self.workflow.entrypoints[name]
        except KeyError as exc:
            raise KeyError(f"unknown entrypoint {name!r}") from exc

    def node(self, node_id: str) -> WorkflowNodeDocument:
        try:
            return self.workflow.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown workflow node {node_id!r}") from exc

    def skill(self, skill_id: str) -> SkillDescriptor:
        key = skill_id.lstrip("/")
        try:
            return self.skills[key]
        except KeyError as exc:
            raise KeyError(f"unknown skill {skill_id!r}") from exc

    def human_checkpoints(self) -> list[WorkflowNodeDocument]:
        return [n for n in self.workflow.nodes.values() if n.is_human_checkpoint()]

    def skill_nodes(self) -> list[WorkflowNodeDocument]:
        return [n for n in self.workflow.nodes.values() if n.is_skill()]
