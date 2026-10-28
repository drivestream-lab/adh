"""Pin-driven spawn. No model on the control path. Never merges."""

import asyncio
from typing import Any, Optional
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.buzz_http_service import BuzzHttpService
from src.infra_services.cursor_cli_service import CursorCliService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.pin_walker_service import PinWalkerService
from src.models.buzz_models import EventType
from src.models.orchestrator_models import MergeRequest, PinDocument, SpawnResult


class OrchestratorService(BaseBusinessService):
    """Walks the pin, mints an App token, spawns Cursor, broadcasts on Buzz."""

    @inject
    def __init__(
        self,
        walker: PinWalkerService,
        github: GitHubAppService,
        cursor: CursorCliService,
        buzz: BuzzHttpService,
    ) -> None:
        super().__init__()
        self._walker = walker
        self._github = github
        self._cursor = cursor
        self._buzz = buzz

    async def initialize(self) -> None:
        await super().initialize()

    async def close(self) -> None:
        await self._walker.close()
        await self._github.close()
        await self._cursor.close()
        await self._buzz.close()
        await super().close()

    async def pin(self) -> PinDocument:
        await self._ensure()
        return self._walker.pin()

    async def merge_wave(self, request: MergeRequest) -> None:
        await self._ensure()
        pin = self._walker.pin()
        raise ValidationError(
            "checkpoint stop: orchestrator will not merge "
            f"(allow_merge={pin.allow_merge}, pr={request.pr_url or 'none'})"
        )

    async def spawn_next(self) -> SpawnResult:
        await self._ensure()
        pin = self._walker.pin()
        wave = self._walker.next_wave()
        slug, app = self._walker.app_for_wave(wave)
        handle = f"adh.coder.{wave.repo}"
        ids: list[str] = []
        await self._event(
            "adh.orchestrator",
            f"spawn start {wave.id} role={wave.role} repo={wave.repo}",
            EventType.START,
            ids,
            {"wave_id": wave.id, "repo": wave.repo, "role": wave.role},
        )
        token, granted = await self._github.installation_token(
            app, write=wave.write, repositories=[wave.repo]
        )
        cannot_merge = self._github.merge_forbidden(pin.allow_merge, granted)
        if not cannot_merge:
            raise ValidationError("checkpoint stop: merge is not allowed on this pin")
        await self._event(
            "adh.orchestrator",
            (f"token minted for {slug} write={wave.write} " f"cannot_merge={cannot_merge}"),
            EventType.PROGRESS,
            ids,
            {"app": slug, "permissions": granted, "cannot_merge": cannot_merge},
        )

        async def _progress(body: str) -> None:
            await self._buzz.heartbeat(handle, body)

        await self._event(
            handle,
            f"Cursor CLI start workspace={wave.repo} mode={wave.mode}",
            EventType.START,
            ids,
            {"mode": wave.mode},
        )
        try:
            code, output, model = await self._cursor.run(
                workspace=self._walker.repo_path(wave.repo),
                prompt=wave.prompt,
                mode=wave.mode,
                github_token=token,
                git_name=f"{slug}[bot]",
                git_email=f"{app.app_id}+{slug}[bot]@users.noreply.github.com",
                write=wave.write,
                on_progress=_progress,
            )
        except Exception as exc:
            self.logger.exception("Cursor CLI spawn failed")
            await self._event(
                handle,
                f"Cursor CLI stall: {exc}",
                EventType.STALL,
                ids,
                {"error": str(exc)},
            )
            code, output, model = 1, str(exc), None
        preview = output.strip()[:800]
        await self._event(
            handle,
            f"Cursor CLI done exit={code} model={model or 'unresolved'}\n{preview}",
            EventType.DONE,
            ids,
            {"exit_code": code, "model": model},
        )
        await self._event(
            "adh.orchestrator",
            f"spawn done {wave.id} merged=false cannot_merge={cannot_merge}",
            EventType.DONE,
            ids,
            {"merged": False, "cannot_merge": cannot_merge, "exit_code": code},
        )
        return SpawnResult(
            wave_id=wave.id,
            role=wave.role,
            repo=wave.repo,
            identity_handle=handle,
            app_slug=slug,
            model=model,
            exit_code=code,
            merged=False,
            cannot_merge=cannot_merge,
            token_permissions=granted,
            buzz_message_ids=ids,
            output_preview=preview,
        )

    async def g0_kill(self) -> SpawnResult:
        """H1–H5: PR on api, cannot push web, cannot merge, checkpoint, Buzz+verify."""
        await self._ensure()
        wave = self._walker.next_wave()
        handle = f"adh.coder.{wave.repo}"
        try:
            await self._buzz.ensure_identity(handle, f"Coder ({wave.repo})", "coder")
        except Exception:
            self.logger.exception("Buzz identity ensure failed", handle=handle)
        result = await self.spawn_next()
        slug, app = self._walker.app_for_wave(wave)
        token, _granted = await self._github.installation_token(
            app, write=wave.write, repositories=[wave.repo]
        )
        web_status = await self._github.probe_push(token, "realworld-web")
        cannot_push_web = web_status not in {200, 201}
        await self._event(
            "adh.orchestrator",
            f"H2 probe realworld-web status={web_status} cannot_push={cannot_push_web}",
            EventType.PROGRESS,
            result.buzz_message_ids,
            {"status": web_status, "cannot_push_web": cannot_push_web},
        )
        pr_number = await self._github.latest_pr_number(token, wave.repo)
        org = self._walker.github_org()
        pr_url: Optional[str] = None
        if pr_number is None:
            pr_number, pr_url = await self._github.ensure_kill_pr(
                token,
                wave.repo,
                branch="feature/g0-kill-backend",
                path="G0_KILL.md",
                contents=(
                    f"G0 kill marker for {wave.repo}. Opened by {slug}[bot]. "
                    "Do not merge. Do not touch realworld-web.\n"
                ),
                title="chore: G0 kill — backend App PR (do not merge)",
            )
        if pr_number is not None and not pr_url:
            pr_url = f"https://github.com/{org}/{wave.repo}/pull/{pr_number}"
        merge_status: Optional[int] = None
        if pr_number is not None:
            merge_status = await self._github.probe_merge(token, wave.repo, pr_number)
        merge_blocked = merge_status is None or merge_status in {401, 403, 405, 409, 422}
        await self._event(
            "adh.orchestrator",
            f"H3 merge probe pr={pr_number} status={merge_status} blocked={merge_blocked}",
            EventType.PROGRESS if merge_blocked else EventType.STALL,
            result.buzz_message_ids,
            {"pr": pr_number, "status": merge_status, "blocked": merge_blocked},
        )
        verify_exit = await self._run_verify()
        await self._event(
            "adh.reviewer",
            f"H5 make verify exit={verify_exit} against realworld-local",
            EventType.DONE if verify_exit == 0 else EventType.STALL,
            result.buzz_message_ids,
            {"verify_exit": verify_exit},
        )
        try:
            await self._buzz.post_hermes_grade(
                pr_ref=pr_url or f"{wave.repo}#{pr_number or 'none'}",
                verify_exit=verify_exit,
            )
        except Exception:
            self.logger.exception("Hermes grade failed")
        checkpoint = "honored"
        try:
            await self.merge_wave(MergeRequest(pr_url=pr_url or ""))
            checkpoint = "BROKEN: merge succeeded"
        except ValidationError as exc:
            checkpoint = str(exc)
        await self._event(
            "adh.orchestrator",
            f"H4 checkpoint {checkpoint}",
            EventType.DONE,
            result.buzz_message_ids,
            {"checkpoint": checkpoint},
        )
        result.cannot_push_web = cannot_push_web
        result.verify_exit = verify_exit
        result.pr_url = pr_url
        result.checkpoint = checkpoint
        result.web_probe_status = web_status
        result.merge_probe_status = merge_status
        result.cannot_merge = merge_blocked and "checkpoint stop" in checkpoint
        result.merged = merge_status == 200
        return result

    async def _run_verify(self) -> int:
        root = self._walker.workspace_root() / "realworld-local"
        process = await asyncio.create_subprocess_exec(
            "make",
            "verify",
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        preview = (stdout or b"").decode("utf-8", errors="replace")[-800:]
        self.logger.info("G0 verify finished", exit_code=process.returncode, preview=preview)
        return int(process.returncode or 0)

    async def _ensure(self) -> None:
        await self._walker.initialize()
        await self._github.initialize()
        await self._cursor.initialize()
        await self._buzz.initialize()

    async def _event(
        self,
        handle: str,
        body: str,
        event: EventType,
        ids: list[str],
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        try:
            posted = await self._buzz.post_event(handle, body, event, payload)
        except Exception:
            self.logger.exception("Buzz broadcast failed", handle=handle)
            return
        if isinstance(posted, UUID):
            ids.append(str(posted))
