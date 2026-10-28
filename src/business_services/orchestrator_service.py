"""Pin-driven spawn. No model on the control path. Never merges."""

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
        token, granted = await self._github.installation_token(app, write=wave.write)
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
