"""Orchestrator checkpoint: never merge; dummy spawn broadcasts."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.business_services.orchestrator_service import OrchestratorService
from src.exceptions.app_exceptions import ValidationError
from src.models.orchestrator_models import (
    AppRole,
    MergeRequest,
    PinCap,
    PinDocument,
    PinWave,
    RolesDocument,
    SpawnPolicy,
)


def _walker(tmp_path: Path) -> MagicMock:
    wave = PinWave(
        id="g0-dummy",
        role="backend",
        repo="adh",
        mode="ask",
        write=False,
        prompt="stop",
    )
    pin = PinDocument(
        initiative="INIT-ADH-000",
        allow_merge=False,
        checkpoint_stop=True,
        cap=PinCap(),
        next=wave,
    )
    app = AppRole(app_id=1, installation_id=2, pem="/tmp/x.pem", repos=["adh"])
    walker = MagicMock()
    walker.initialize = AsyncMock()
    walker.close = AsyncMock()
    walker.pin.return_value = pin
    walker.next_wave.return_value = wave
    walker.app_for_wave.return_value = ("adh-dev-backend", app)
    walker.repo_path.return_value = tmp_path
    walker.github_org.return_value = "drivestream-lab"
    walker.workspace_root.return_value = tmp_path
    walker.roles.return_value = RolesDocument(
        apps={"adh-dev-backend": app},
        spawn=SpawnPolicy(),
    )
    return walker


def test_merge_is_checkpoint_stop(tmp_path: Path) -> None:
    orch = OrchestratorService(
        _walker(tmp_path),
        MagicMock(initialize=AsyncMock(), close=AsyncMock()),
        MagicMock(initialize=AsyncMock(), close=AsyncMock()),
        MagicMock(initialize=AsyncMock(), close=AsyncMock()),
    )

    async def _run() -> None:
        with pytest.raises(ValidationError, match="checkpoint stop"):
            await orch.merge_wave(MergeRequest(pr_url="https://example.invalid/pr/1"))

    asyncio.run(_run())


def test_spawn_broadcasts_and_does_not_merge(tmp_path: Path) -> None:
    github = MagicMock()
    github.initialize = AsyncMock()
    github.close = AsyncMock()
    github.installation_token = AsyncMock(return_value=("tok", {"contents": "read"}))
    github.merge_forbidden.return_value = True
    cursor = MagicMock()
    cursor.initialize = AsyncMock()
    cursor.close = AsyncMock()
    cursor.run = AsyncMock(return_value=(0, "adh\n", "composer-2.5"))
    buzz = MagicMock()
    buzz.initialize = AsyncMock()
    buzz.close = AsyncMock()
    buzz.post_event = AsyncMock(return_value=uuid4())
    buzz.heartbeat = AsyncMock()
    walker = _walker(tmp_path)
    orch = OrchestratorService(walker, github, cursor, buzz)
    result = asyncio.run(orch.spawn_next())
    assert result.merged is False
    assert result.cannot_merge is True
    assert result.wave_id == "g0-dummy"
    assert result.exit_code == 0
    assert result.identity_handle == "adh.coder.adh"
    assert github.installation_token.await_count == 1
    assert cursor.run.await_count == 1
    assert buzz.post_event.await_count >= 4
    github.installation_token.assert_awaited_with(
        walker.app_for_wave.return_value[1],
        write=False,
        repositories=["adh"],
    )


def test_g0_kill_probes_and_checkpoint(tmp_path: Path) -> None:
    github = MagicMock()
    github.initialize = AsyncMock()
    github.close = AsyncMock()
    github.installation_token = AsyncMock(return_value=("tok", {"contents": "write"}))
    github.merge_forbidden.return_value = True
    github.probe_push = AsyncMock(return_value=403)
    github.latest_pr_number = AsyncMock(return_value=12)
    github.probe_merge = AsyncMock(return_value=403)
    github.ensure_kill_pr = AsyncMock()
    cursor = MagicMock()
    cursor.initialize = AsyncMock()
    cursor.close = AsyncMock()
    cursor.run = AsyncMock(return_value=(0, "opened pr\n", "composer-2.5"))
    buzz = MagicMock()
    buzz.initialize = AsyncMock()
    buzz.close = AsyncMock()
    buzz.post_event = AsyncMock(return_value=uuid4())
    buzz.heartbeat = AsyncMock()
    buzz.ensure_identity = AsyncMock()
    buzz.post_hermes_grade = AsyncMock()
    orch = OrchestratorService(_walker(tmp_path), github, cursor, buzz)
    orch._run_verify = AsyncMock(return_value=0)  # noqa: SLF001
    result = asyncio.run(orch.g0_kill())
    assert result.cannot_push_web is True
    assert result.web_probe_status == 403
    assert result.merge_probe_status == 403
    assert result.verify_exit == 0
    assert result.pr_url == "https://github.com/drivestream-lab/adh/pull/12"
    assert result.merged is False
    assert result.cannot_merge is True
    assert result.checkpoint is not None
    assert "checkpoint stop" in result.checkpoint
    github.ensure_kill_pr.assert_not_called()
    github.probe_push.assert_awaited_once()
    github.probe_merge.assert_awaited_once()
    buzz.post_hermes_grade.assert_awaited()
