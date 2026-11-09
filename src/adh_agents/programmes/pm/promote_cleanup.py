"""Deprecated — use ``adh_agents.collaboration.temp_papers``.

Kept as thin re-exports so older imports keep resolving. New call sites must use
``PurgeEvent`` / ``resolve_purge_paths`` (global purge strategy).
"""

from __future__ import annotations

from src.adh_agents.collaboration.temp_papers import (
    authoring_scratch_paths,
    is_authoring_scratch,
)

# Back-compat aliases
is_prepromote_scratch = is_authoring_scratch
scratch_paths_for_initiative = authoring_scratch_paths


def archive_prefix(initiative: str) -> str:
    """Deprecated: archive is retired — purge deletes in place."""
    return f"prd/reports/_archive/{initiative}"


def archive_dest(path: str, initiative: str) -> str:
    """Deprecated: do not archive; call ``resolve_purge_paths`` + purge instead."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return f"{archive_prefix(initiative)}/{name}"
