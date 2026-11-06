"""Resume INIT-… rebuilds the latest human gate from local artefacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.programmes.meta_pm_programme import MetaPmProgrammeService
from src.business_services.hermes.runtime.navigator_service import HermesNavigatorService
from src.business_services.hermes.runtime.session_store import HermesSessionStoreService
from src.business_services.hermes.validation_report import impact_map_path
from src.infra_services.pm_workspace_service import (
    MetaInventory,
    hermes_post_pm_brief_path,
    prd_path,
)
from src.models.buzz_models import EventType
from src.models.hermes.session_models import (
    AWAITING_AUTHORIZATION,
    AWAITING_JUDGMENT,
    HermesProgrammeType,
)
from src.models.tenant_models import TenantContext
from tests.unit.test_workflow_catalogue import _mini_snapshot

_INIT = "INIT-RW-001"
_ROOM = "rw-ops"
_TENANT = TenantContext(
    slug="rw",
    org="drivestream-lab",
    meta_repo="rw-meta",
    meta_root="/tmp/rw-meta",
)

_POSTPM = """
# Hermes post-PM brief — INIT-RW-001

recommend: confirm

## bluf
Proceed — Criticals cleared.

## changed
- Metadata cleaned

## deferred
- none

## still_risky
- none

## example
A stranger finds the article on home.

## options
- confirm — proceed; Hermes runs impact-map next
- revise — hold and edit the PRD first
"""


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, Optional[int]] = {}

    async def get(self, key: str, as_json: bool = False) -> Any:
        raw = self.data.get(key)
        if raw is not None and as_json:
            return json.loads(raw)
        return raw

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        self.data[key] = value if isinstance(value, str) else json.dumps(value)
        self.ttls[key] = ttl
        return True

    async def delete(self, key: str) -> int:
        self.ttls.pop(key, None)
        return 1 if self.data.pop(key, None) is not None else 0


class _FakePoster:
    def __init__(self) -> None:
        self.posts: list[tuple[str, EventType, Optional[dict[str, Any]]]] = []

    async def post_status(
        self,
        room: str,
        body: str,
        event_type: EventType = EventType.PROGRESS,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        self.posts.append((body, event_type, payload))


class _FakeCatalogue:
    def __init__(self, snap: Any) -> None:
        self._snap = snap

    def snapshot(self) -> Any:
        return self._snap


def _files(**paths: str) -> MagicMock:
    workspace = MagicMock()

    def _read(_tenant: Any, path: str) -> str:
        return paths.get(path, "")

    workspace.read_local = MagicMock(side_effect=_read)
    found: set[str] = set()
    for path in paths:
        name = Path(path).name
        if path.startswith("prd/") and "/" not in path[4:] and name.startswith("INIT-"):
            found.add(name[: -len(".md")])
        if name.startswith("Impact-Map-"):
            found.add(name[len("Impact-Map-") :].replace(".md", ""))
        if name.endswith("-hermes-post-pm-brief.md"):
            found.add(name[: -len("-hermes-post-pm-brief.md")])
    workspace.inventory = MagicMock(
        return_value=MetaInventory(inits=sorted(found), think_paths=[], prd_paths=[])
    )
    return workspace


def _programme(
    tmp_path: Any, workspace: MagicMock
) -> tuple[MetaPmProgrammeService, _FakePoster, HermesSessionStoreService]:
    snap = _mini_snapshot(tmp_path)
    store = HermesSessionStoreService(redis=_FakeRedis())  # type: ignore[arg-type]
    poster = _FakePoster()
    nav = HermesNavigatorService(catalogue=_FakeCatalogue(snap))  # type: ignore[arg-type]
    svc = MetaPmProgrammeService(
        store=store,
        dispatch=MagicMock(),
        briefs=HermesBriefService(),
        navigator=nav,
        poster=poster,  # type: ignore[arg-type]
        workspace=workspace,  # type: ignore[arg-type]
        prompts=MagicMock(),
    )
    return svc, poster, store


async def test_resume_prefers_impact_map_authorize(tmp_path: Any) -> None:
    workspace = _files(
        **{
            prd_path(_INIT): "# PRD",
            hermes_post_pm_brief_path(_INIT): _POSTPM,
            impact_map_path(_INIT): "# Impact-Map",
        }
    )
    svc, poster, store = _programme(tmp_path, workspace)
    await svc.resume_programme(_TENANT, _ROOM, _INIT)
    session = await store.load("rw", _INIT)
    assert session is not None
    assert session.awaiting == AWAITING_AUTHORIZATION
    assert session.stage == "prd-pr-action"
    assert session.programme == HermesProgrammeType.META_PM
    assert any((p or {}).get("status") == "resume_authorize" for _, _, p in poster.posts if p)
    assert svc.list_resumable(_TENANT)[0]["gate"] == "authorize"


async def test_resume_reopens_post_pm_confirm(tmp_path: Any) -> None:
    workspace = _files(
        **{
            prd_path(_INIT): "# PRD",
            hermes_post_pm_brief_path(_INIT): _POSTPM,
        }
    )
    svc, poster, store = _programme(tmp_path, workspace)
    await svc.resume_programme(_TENANT, _ROOM, _INIT)
    session = await store.load("rw", _INIT)
    assert session is not None
    assert session.awaiting == AWAITING_JUDGMENT
    assert session.stage == "prd-impact-acceptance"
    assert session.open_brief is not None
    assert "confirm" in session.open_brief.reply_tokens
    assert any((p or {}).get("status") == "need_post_pm_confirm" for _, _, p in poster.posts if p)


async def test_resume_missing_prd_stalls(tmp_path: Any) -> None:
    workspace = _files()
    svc, poster, store = _programme(tmp_path, workspace)
    await svc.resume_programme(_TENANT, _ROOM, _INIT)
    assert await store.load("rw", _INIT) is None
    assert any((p or {}).get("status") == "resume_missing_prd" for _, _, p in poster.posts if p)
