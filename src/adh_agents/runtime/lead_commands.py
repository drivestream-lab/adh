"""Lead command matching — phrase lists today; agentic hole for later.

Default: exact / prefix phrase match via ``normalize_reply``-style families.
``classify_lead_command_agentic`` is the reserved extension point (not wired).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence

from src.adh_agents.collaboration.human_replies import normalize_reply
from src.infra_services.litellm_service import LiteLLMService


class LeadCommand(str, Enum):
    """Canonical Lead ops commands (extend as roles hire)."""

    ENGG_GO = "engg go"
    HIRE_ENGG = "hire engg"
    RESUME = "resume"
    TRAJ = "traj"
    REWIND = "rewind"
    ARCHIVE_TASK = "archive task"
    DELETE_TASK = "delete task"
    KEEP_OPEN = "keep open"


# Phrase families → canonical command (Lead body lowercased contains / aliases).
_PHRASE_FAMILIES: dict[LeadCommand, tuple[str, ...]] = {
    LeadCommand.ENGG_GO: ("engg go",),
    LeadCommand.HIRE_ENGG: ("hire engg", "hire dev", "@adh.dev", "engg think"),
    LeadCommand.RESUME: ("resume",),
    LeadCommand.TRAJ: ("traj", "trajectory", "show trajectory"),
    LeadCommand.REWIND: ("rewind",),
    LeadCommand.ARCHIVE_TASK: ("archive task", "archive"),
    LeadCommand.DELETE_TASK: ("delete task", "delete"),
    LeadCommand.KEEP_OPEN: ("keep open", "keep"),
}


def match_lead_command(
    body: str,
    *,
    allowed: Sequence[LeadCommand] | None = None,
) -> Optional[LeadCommand]:
    """Phrase-list match. Prefer longest phrase hit; no regex; not agentic."""
    text = (body or "").strip()
    if not text:
        return None
    lowered = text.lower()
    candidates = list(allowed) if allowed is not None else list(LeadCommand)
    # Longest phrase first so "archive task" wins over "archive".
    ranked: list[tuple[int, LeadCommand]] = []
    for cmd in candidates:
        phrases = _PHRASE_FAMILIES.get(cmd, (cmd.value,))
        for phrase in phrases:
            p = phrase.lower()
            if lowered == p or lowered.startswith(p + " ") or f" {p} " in f" {lowered} ":
                ranked.append((len(p), cmd))
                break
            # Also accept normalize_reply when body is exactly an alias line.
            if normalize_reply(text, list(phrases)) is not None:
                ranked.append((len(p), cmd))
                break
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


async def classify_lead_command_agentic(
    litellm: LiteLLMService,
    body: str,
    *,
    allowed: Sequence[LeadCommand] | None = None,
) -> Optional[LeadCommand]:
    """Reserved hole — agentic Lead command classify.

    Not enabled yet. Callers must use ``match_lead_command`` until this is
    product-approved. Keeping the signature stable for future hires.
    """
    del litellm, body, allowed
    return None
