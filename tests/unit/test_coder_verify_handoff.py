"""Coder → Verify handoff baton shape."""

from __future__ import annotations

from typing import Any, cast

import pytest

from src.adh_agents.baton.models import Baton
from src.adh_agents.programmes.coder.verify_handoff import CoderVerifyHandoff
from src.models.tenant_models import TenantContext


class _FakeBatons:
    def __init__(self) -> None:
        self.last: Baton | None = None

    async def create_pending(self, baton: Baton, ttl: int = 0):  # noqa: ANN201
        del ttl
        self.last = baton
        return baton, True


class _FakeBuzz:
    async def ensure_member(self, *_a, **_k) -> None:
        return None

    async def post_message(self, *_a, **_k) -> None:
        return None


class _FakePoster:
    async def post_status(self, *_a, **_k) -> None:
        return None


@pytest.mark.asyncio
async def test_emit_verify_wave_baton_shape() -> None:
    batons = _FakeBatons()
    handoff = cast(Any, CoderVerifyHandoff.__new__(CoderVerifyHandoff))
    handoff._buzz = _FakeBuzz()
    handoff._batons = batons
    handoff._poster = _FakePoster()
    from src.adh_agents.settings import CoderAgentSettings, VerifyAgentSettings

    handoff._coder = CoderAgentSettings()
    handoff._verify = VerifyAgentSettings()
    handoff.role_id = "adh.coder"
    handoff.logger = type("L", (), {"exception": staticmethod(lambda *a, **k: None)})()

    tenant = TenantContext(
        slug="realworld",
        org="drivestream-lab",
        meta_repo="realworld-meta",
        meta_root="/tmp/realworld-meta",
        ops_room="realworld-ops",
        init_prefix="INIT-REALWORLD",
        integration_branch="develop",
    )
    stored = await handoff.emit_verify_wave(
        tenant,
        initiative="INIT-REALWORLD-001",
        engg_room="engg-init-realworld-001",
        repo="realworld-api",
        wave_id="W1",
        pr_url="https://example/pr/1",
        round_n=2,
    )
    assert stored.type == "verify.wave"
    assert stored.to_role == "adh.verify"
    assert stored.payload["repo"] == "realworld-api"
    assert stored.payload["wave_id"] == "W1"
    assert stored.payload["collab_round"] == 2
    assert stored.payload["compose_dir"] == "realworld-local"
    assert "r2" in stored.idempotency_key
