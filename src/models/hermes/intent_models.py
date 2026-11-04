"""Understanding / judgment DTOs. Ids are catalogue strings, not enums."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class IntentCandidate(BaseModel):
    """A possible binding of Lead speech to a catalogue node / action."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(..., min_length=1, description="workflow node id")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = Field(default="")
    missing_slots: list[str] = Field(
        default_factory=list,
        description="e.g. initiative — dig before execute",
    )
    slots: dict[str, str] = Field(default_factory=dict)


class ClarifyRequest(BaseModel):
    """Conversational dig for missing slots."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1)
    missing_slots: list[str] = Field(default_factory=list)
    candidates: list[IntentCandidate] = Field(default_factory=list)


class JudgmentRequest(BaseModel):
    """Open brief awaiting Lead judgment (tokens come from the brief, not a global enum)."""

    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(default="", description="checkpoint purpose from catalogue")
    node_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    example: str = Field(default="")
    options: list[str] = Field(default_factory=list)
    recommend: str = Field(default="")
    recommend_why: str = Field(
        default="",
        description="Legacy alias of bluf (kept for Redis session back-compat)",
    )
    bluf: str = Field(default="", description="Bottom line — decision + stakes")
    card_kind: str = Field(
        default="",
        description="promote | postpm — selects Buzz section labels",
    )
    locking: list[str] = Field(
        default_factory=list,
        description="Promote: buying. Post-PM: changed since promote.",
    )
    not_locking: list[str] = Field(
        default_factory=list,
        description="Promote: not buying. Post-PM: deferred.",
    )
    revise_if: list[str] = Field(
        default_factory=list,
        description="Promote: pick another if. Post-PM: still risky.",
    )
    reply_tokens: list[str] = Field(
        default_factory=list,
        description="Exact tokens Lead may reply; sourced from this brief",
    )
    artefact_path: Optional[str] = None


class AuthorizedAction(BaseModel):
    """Lead-authorized execute target (skill or external-action)."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(..., min_length=1)
    action_kind: str = Field(..., min_length=1, description="skill|external-action")
    forge_action: Optional[str] = None
    initiative: Optional[str] = None
    authorization_token: str = Field(
        default="",
        description="Lead phrase that authorized (e.g. go ahead)",
    )
