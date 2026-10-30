"""Spawn one Cursor CLI process in a single repo worktree."""

import asyncio
import base64
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional

from src.configs.orchestrator_settings import OrchestratorSettings
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger

logger = get_logger()

ProgressCallback = Callable[[str], Awaitable[None]]


class CursorCliService(BaseInfraService):
    """Wave implementer. Does not call LiteLLM. One repo per run."""

    def __init__(self) -> None:
        self._settings = OrchestratorSettings.get_instance()
        self._in_flight = 0
        self._initialized = False

    async def initialize(self) -> None:
        self._initialized = True
        logger.info("Initializing Cursor CLI service", binary=self._settings.cursor_bin)

    async def close(self) -> None:
        self._initialized = False

    async def health_check(self) -> bool:
        return self._initialized

    async def run(
        self,
        *,
        workspace: Path,
        prompt: str,
        mode: str,
        github_token: str,
        git_name: str = "adh-dev-backend[bot]",
        git_email: str = "5508912+adh-dev-backend[bot]@users.noreply.github.com",
        write: bool = False,
        on_progress: Optional[ProgressCallback] = None,
    ) -> tuple[int, str, Optional[str]]:
        """Return (exit_code, combined_output, resolved_model)."""
        if self._in_flight >= self._settings.max_cursor:
            raise ValidationError(f"Cursor cap reached ({self._settings.max_cursor})")
        if not workspace.is_dir():
            raise ValidationError(f"workspace does not exist: {workspace}")
        command = [
            self._settings.cursor_bin,
            "-p",
            "--trust",
            "--output-format",
            "text",
            "--workspace",
            str(workspace),
        ]
        if mode in {"ask", "plan"}:
            command.extend(["--mode", mode])
        elif write:
            command.append("--force")
        command.append(prompt)
        env = dict(os.environ)
        env["GH_TOKEN"] = github_token
        env["GITHUB_TOKEN"] = github_token
        env["GH_PROMPT_DISABLED"] = "1"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_AUTHOR_NAME"] = git_name
        env["GIT_AUTHOR_EMAIL"] = git_email
        env["GIT_COMMITTER_NAME"] = git_name
        env["GIT_COMMITTER_EMAIL"] = git_email
        basic = base64.b64encode(f"x-access-token:{github_token}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {basic}"
        env.pop("HERMES_LITELLM_API_KEY", None)
        env.pop("OPENROUTER_API_KEY", None)
        self._in_flight += 1
        logger.info("Spawning Cursor CLI", workspace=str(workspace), mode=mode)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        heartbeat = asyncio.create_task(self._heartbeat(process, on_progress))
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=self._settings.cursor_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ValidationError("Cursor CLI timed out") from exc
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            self._in_flight -= 1
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        code = int(process.returncode or 0)
        logger.info("Cursor CLI exited", exit_code=code, bytes=len(output))
        return code, output, _extract_model(output)

    async def _heartbeat(
        self,
        process: asyncio.subprocess.Process,
        on_progress: Optional[ProgressCallback],
    ) -> None:
        if on_progress is None:
            return
        while process.returncode is None:
            await asyncio.sleep(self._settings.heartbeat_seconds)
            if process.returncode is None:
                await on_progress("Cursor CLI still running")


def _extract_model(output: str) -> Optional[str]:
    for line in output.splitlines():
        if "model" in line.lower() and ":" in line:
            return line.split(":", 1)[-1].strip()[:128] or None
    return None
