"""C1 Coder spine — settings, ready-set, handoff emit/idempotency, claim smoke."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adh_agents.baton.models import Baton, BatonStatus
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.programmes.coder.programme import CoderWaveProgramme
from src.adh_agents.programmes.coder.ready_set import ready_repos, ready_waves
from src.adh_agents.programmes.coder.roles import coder_role_for_repo, is_coder_role
from src.adh_agents.programmes.dev.coder_handoff import DevCoderHandoff
from src.adh_agents.programmes.dev.workmanifest_board import parse_board_manifest
from src.adh_agents.settings import CoderAgentSettings


_MIN_PLAN = """
## 9. WorkManifest

```yaml
apiVersion: prayog/v1
kind: WorkManifest
initiative: INIT-X-1
target:
  org: example
  project: Board
defaults:
  labels: [INIT-X-1]
epic:
  id: EPIC
  repo: api
  title: epic title
  body: epic body
work:
  - id: W0
    repo: api
    title: wave0
    depends_on: []
    tasks:
      - id: TASK-W0-01
        implements: [REQ-01]
        depends_on: []
  - id: W1
    repo: web
    title: wave1
    depends_on: [W0]
    tasks:
      - id: TASK-W1-01
        implements: [REQ-02]
        depends_on: []
  - id: W2
    repo: api
    title: wave2
    depends_on: []
    tasks:
      - id: TASK-W2-01
        implements: [REQ-03]
        depends_on: []
```
"""


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def set_if_absent(self, key: str, value: Any, ttl: int) -> bool:
        if key in self._data:
            return False
        self._data[key] = value if isinstance(value, str) else str(value)
        return True

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        self._data[key] = value if isinstance(value, str) else str(value)
        return True

    async def get(self, key: str, as_json: bool = False) -> Any:
        return self._data.get(key)

    async def keys(self, pattern: str) -> list[str]:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._data if k.startswith(prefix)]
        return [k for k in self._data if k == pattern]


def test_coder_settings_max_parallel_default() -> None:
    settings = CoderAgentSettings(max_parallel_coders=3)
    assert settings.role_id == "adh.coder"
    assert settings.max_parallel_coders == 3
    assert CoderAgentSettings.PREFIX == "ADH_CODER"


def test_coder_role_helpers() -> None:
    assert coder_role_for_repo("org/realworld-api") == "adh.coder.realworld-api"
    assert is_coder_role("adh.coder")
    assert is_coder_role("adh.coder.api")
    assert not is_coder_role("adh.dev")


def test_ready_set_depends_on() -> None:
    m = parse_board_manifest(_MIN_PLAN)
    assert [w.wave_id for w in ready_waves(m)] == ["W0", "W2"]
    assert ready_repos(m) == ("api",)
    assert ready_repos(m, done_wave_ids=frozenset({"W0"})) == ("web", "api")


def test_forge_acl_coder_prefix() -> None:
    assert forge_allowed("adh.coder", "open_draft_pr")
    assert forge_allowed("adh.coder.realworld-api", "update_board_status")
    assert not forge_allowed("adh.coder", "prd_merge")


def test_list_pending_for_coder_prefix() -> None:
    store = RedisBatonStore.__new__(RedisBatonStore)
    store._redis = _FakeRedis()  # type: ignore[assignment]
    store._prefix = "adh:baton"

    a = Baton(
        type="coder.wave",
        from_role="adh.dev",
        to_role="adh.coder.api",
        tenant="realworld",
        ops_room="engg-init-x-1",
        initiative="INIT-X-1",
        idempotency_key="coder.wave:realworld:INIT-X-1:api:seed",
    )
    b = Baton(
        type="coder.wave",
        from_role="adh.dev",
        to_role="adh.coder.web",
        tenant="realworld",
        ops_room="engg-init-x-1",
        initiative="INIT-X-1",
        idempotency_key="coder.wave:realworld:INIT-X-1:web:seed",
    )
    other = Baton(
        type="dev.engg_think",
        from_role="adh.pe",
        to_role="adh.dev",
        tenant="realworld",
        ops_room="engg-init-x-1",
        initiative="INIT-X-1",
        idempotency_key="dev.engg_think:realworld:INIT-X-1:pr",
    )
    asyncio.run(store.create_pending(a, ttl=60))
    asyncio.run(store.create_pending(b, ttl=60))
    asyncio.run(store.create_pending(other, ttl=60))

    pending = asyncio.run(
        store.list_pending_for(
            tenant="realworld", to_role_prefix="adh.coder", baton_type="coder.wave"
        )
    )
    assert len(pending) == 2
    roles = {p.to_role for p in pending}
    assert roles == {"adh.coder.api", "adh.coder.web"}


@pytest.mark.asyncio
async def test_dev_coder_handoff_emit_idempotent(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_MIN_PLAN, encoding="utf-8")

    buzz = MagicMock()
    buzz.post_message = AsyncMock()
    buzz.ensure_member = AsyncMock()
    buzz.create_identity = AsyncMock(side_effect=Exception("dup"))

    store = RedisBatonStore.__new__(RedisBatonStore)
    store._redis = _FakeRedis()  # type: ignore[assignment]
    store._prefix = "adh:baton"

    poster = MagicMock()
    poster.post_status = AsyncMock()
    workspace = MagicMock()
    workspace.read_local = MagicMock(return_value="")

    handoff = DevCoderHandoff.__new__(DevCoderHandoff)
    handoff._buzz = buzz
    handoff._batons = store
    handoff._poster = poster
    handoff._workspace = workspace
    handoff._dev_settings = MagicMock(baton_ttl_seconds=60)
    handoff._coder_settings = MagicMock(max_parallel_coders=3)
    handoff._lead = "nikd10x"
    handoff.logger = MagicMock()
    handoff.role_id = "adh.dev"

    tenant = MagicMock()
    tenant.slug = "realworld"
    tenant.ops_room = "realworld-ops"

    first = await handoff.handoff_to_coder(
        tenant,
        initiative="INIT-X-1",
        engg_room="engg-init-x-1",
        plan_path=plan,
        board_seed_marker="create_board_tickets:INIT-X-1",
    )
    assert len(first) == 1
    assert first[0].to_role == "adh.coder.api"
    assert first[0].type == "coder.wave"

    second = await handoff.handoff_to_coder(
        tenant,
        initiative="INIT-X-1",
        engg_room="engg-init-x-1",
        plan_path=plan,
        board_seed_marker="create_board_tickets:INIT-X-1",
    )
    assert len(second) == 1
    assert second[0].id == first[0].id


@pytest.mark.asyncio
async def test_coder_programme_claim_smoke() -> None:
    store = RedisBatonStore.__new__(RedisBatonStore)
    store._redis = _FakeRedis()  # type: ignore[assignment]
    store._prefix = "adh:baton"

    baton = Baton(
        type="coder.wave",
        from_role="adh.dev",
        to_role="adh.coder.api",
        tenant="realworld",
        ops_room="engg-init-x-1",
        initiative="INIT-X-1",
        idempotency_key="coder.wave:realworld:INIT-X-1:api:seed",
        payload={"repo": "api", "wave_ids": ["W0", "W2"]},
    )
    await store.create_pending(baton, ttl=60)

    work_store = MagicMock()
    work_store.save = AsyncMock()
    poster = MagicMock()
    poster.post_status = AsyncMock()
    tenants = MagicMock()
    tenant = MagicMock()
    tenant.slug = "realworld"
    tenant.ops_room = "realworld-ops"
    tenants.by_slug = MagicMock(return_value=tenant)

    leases = MagicMock()
    leases.try_acquire = AsyncMock(
        return_value=MagicMock(
            acquired=True, key="adh:coder:lease:realworld:api", holder="adh.coder"
        )
    )
    leases.release = AsyncMock(return_value=True)

    programme = CoderWaveProgramme.__new__(CoderWaveProgramme)
    programme._store = work_store
    programme._batons = store
    programme._poster = poster
    programme._tenants = tenants
    programme._leases = leases
    programme._forge = MagicMock()
    programme._workspace = MagicMock()
    programme._settings = MagicMock(baton_ttl_seconds=60, max_parallel_coders=3)
    programme.role_id = "adh.coder"
    programme.logger = MagicMock()
    programme._continue_wave = AsyncMock()  # type: ignore[method-assign]

    rollup = await programme.handle_baton(baton, room="engg-init-x-1")
    assert rollup.status == BatonStatus.DONE
    assert "api" in (rollup.summary or "")
    work_store.save.assert_awaited()
    poster.post_status.assert_awaited()
    leases.try_acquire.assert_awaited()
    programme._continue_wave.assert_awaited()

    loaded = await store.get(
        tenant="realworld", idempotency_key="coder.wave:realworld:INIT-X-1:api:seed"
    )
    assert loaded is not None
    assert loaded.status == BatonStatus.DONE
    # claim() writes claimed_by on the stored copy; mark_running/done reuse the
    # caller baton object (same pattern as Dev) — status DONE is the C1 signal.


@pytest.mark.asyncio
async def test_repo_lease_nx_and_clip() -> None:
    from src.adh_agents.programmes.coder.repo_lease import CoderRepoLeaseStore

    class _R(_FakeRedis):
        async def delete(self, key: str) -> int:
            self._data.pop(key, None)
            return 1

    redis = _R()
    leases = CoderRepoLeaseStore.__new__(CoderRepoLeaseStore)
    leases._redis = redis  # type: ignore[assignment]
    leases._prefix = "adh:coder:lease"

    a = await leases.try_acquire(tenant="realworld", repo="api", holder="adh.coder", ttl_seconds=60)
    assert a.acquired
    b = await leases.try_acquire(tenant="realworld", repo="api", holder="other", ttl_seconds=60)
    assert not b.acquired
    same = await leases.try_acquire(
        tenant="realworld", repo="api", holder="adh.coder", ttl_seconds=60
    )
    assert same.acquired and same.reason == "renewed"

    clipped = await leases.clip_ready(["api", "web", "edge"], tenant="realworld", max_parallel=2)
    # api held → only web (+edge if slot); held=1, cap=2 → 1 slot
    assert clipped == ["web"]
    await leases.try_acquire(tenant="realworld", repo="web", holder="adh.coder", ttl_seconds=60)
    assert await leases.clip_ready(["api", "web", "edge"], tenant="realworld", max_parallel=2) == []


def test_pick_wave_issue_url_and_parse() -> None:
    from src.adh_agents.programmes.coder.forge_ops import parse_issue_url, pick_wave_issue_url
    from src.infra_services.github_app_service import _status_option_names

    urls = [
        "https://github.com/org/api/issues/1",
        "https://github.com/org/api/issues/2",
        "https://github.com/org/web/issues/3",
    ]
    assert pick_wave_issue_url(urls, wave_id="W0", wave_index=0).endswith("/2")
    assert pick_wave_issue_url(urls, wave_id="W1", wave_index=1).endswith("/3")
    org, repo, num = parse_issue_url(urls[1])
    assert org == "org" and repo == "api" and num == 2
    assert "in progress" in _status_option_names("in_progress")
    assert "done" in _status_option_names("done")
