"""Pin walker is deterministic and refuses identity/repo mismatches."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.configs.base_settings import BaseSettings
from src.exceptions.app_exceptions import ValidationError

from src.infra_services.pin_walker_service import (
    PinWalkerService,
    app_slug_for_role,
    parse_pin,
)
from src.models.orchestrator_models import PinWave


def test_parse_pin_next_wave() -> None:
    pin = parse_pin(
        {
            "initiative": "INIT-ADH-000",
            "allow_merge": False,
            "checkpoint_stop": True,
            "next": {
                "id": "g0-dummy",
                "role": "backend",
                "repo": "adh",
                "mode": "ask",
                "write": False,
                "prompt": "stop",
            },
        }
    )
    assert pin.next is not None
    assert pin.next.id == "g0-dummy"
    assert pin.allow_merge is False


def test_app_slug_for_role() -> None:
    assert app_slug_for_role("backend") == "adh-dev-backend"
    with pytest.raises(ValidationError):
        app_slug_for_role("god")


def test_roles_refuse_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = tmp_path / "adh-meta" / "config"
    meta.mkdir(parents=True)
    (meta / "pin.yaml").write_text(
        "\n".join(
            [
                "initiative: INIT-ADH-000",
                "allow_merge: false",
                "next:",
                "  id: x",
                "  role: backend",
                "  repo: realworld-web",
                '  prompt: "do not spawn"',
            ]
        ),
        encoding="utf-8",
    )
    (meta / "roles.yaml").write_text(
        "\n".join(
            [
                "apps:",
                "  adh-dev-backend:",
                "    app_id: 1",
                "    pem: /tmp/x.pem",
                "    repos: [adh]",
                "    used_by: cursor-coder",
                "spawn:",
                "  refuse_repo_not_on_identity: true",
                "  cannot_merge: true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORCH_META_ROOT", str(tmp_path / "adh-meta"))
    BaseSettings._instances.pop("OrchestratorSettings", None)

    tenants = MagicMock()
    tenants.allowed_repos.return_value = {"adh", "realworld-web"}
    walker = PinWalkerService(tenants)

    async def _run() -> None:
        await walker.initialize()
        wave = PinWave(id="x", role="backend", repo="realworld-web", prompt="no")
        with pytest.raises(ValidationError, match="spawn refused"):
            walker.app_for_wave(wave)

    asyncio.run(_run())


def test_roles_refuse_repo_outside_active_topology(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = tmp_path / "adh-meta" / "config"
    meta.mkdir(parents=True)
    (meta / "pin.yaml").write_text(
        "\n".join(
            [
                "initiative: INIT-ADH-000",
                "allow_merge: false",
                "next:",
                "  id: x",
                "  role: backend",
                "  repo: mystery-api",
                '  prompt: "do not spawn"',
            ]
        ),
        encoding="utf-8",
    )
    (meta / "roles.yaml").write_text(
        "\n".join(
            [
                "apps:",
                "  adh-dev-backend:",
                "    app_id: 1",
                "    pem: /tmp/x.pem",
                "    repos: [adh, mystery-api]",
                "    used_by: cursor-coder",
                "spawn:",
                "  refuse_repo_not_on_identity: true",
                "  cannot_merge: true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORCH_META_ROOT", str(tmp_path / "adh-meta"))
    BaseSettings._instances.pop("OrchestratorSettings", None)
    tenants = MagicMock()
    tenants.allowed_repos.return_value = {"adh", "adh-meta", "adh-iac-local", "realworld-api"}
    walker = PinWalkerService(tenants)

    async def _run() -> None:
        await walker.initialize()
        wave = PinWave(id="x", role="backend", repo="mystery-api", prompt="no")
        with pytest.raises(ValidationError, match="active tenant topology"):
            walker.app_for_wave(wave)

    asyncio.run(_run())
