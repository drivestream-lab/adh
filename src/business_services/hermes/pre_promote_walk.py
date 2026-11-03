"""Pre-promote PM authoring walk and Lead ask/promote/init handlers."""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import asyncio
import re
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from src.business_services.hermes.lead_tokens import (
    _coerce_init,
    _is_numbered_init,
    is_lead_outline_body,
    parse_ask_answers,
    parse_promote_pick,
    validate_ask_answers,
)
from src.business_services.hermes.gates import _any_handover
from src.business_services.hermes.render_pm import (
    _fail_list_from_quality,
    _format_answers,
    _format_fork_block,
    _prior_candidate_text,
    _think_file_ref,
)
from src.configs.rubrics import RUBRIC_PM
from src.infra_services.pm_workspace_service import (
    ask_path,
    next_free_think_runs,
    next_programme_init,
    prd_path,
    quality_path,
    think_path,
)
from src.models.buzz_models import EventType, MessageKind, MessageRead
from src.models.hermes_models import HermesArtifactRead, HermesBriefRequest
from src.models.tenant_models import TenantContext


class PrePromoteWalkMixin:
    """Authoring loop plus Lead ask/promote/init finite-state handlers."""

    async def _run_outline_work(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        fingerprint: str,
        source_id: str,
        source_message_id: Optional[UUID] = None,
        initiative: Optional[str] = None,
    ) -> None:
        awaiting_init = False
        try:
            listing = self._workspace.inventory(tenant)
            try:
                resolved = (
                    _coerce_init(initiative, tenant.slug)
                    if initiative
                    else next_programme_init(tenant.init_prefix, listing.inits)
                )
            except ValueError:
                awaiting_init = True
                await self._ask_for_init(tenant, room, outline, fingerprint, source_id)
                return
            if not _is_numbered_init(resolved, tenant):
                awaiting_init = True
                await self._ask_for_init(tenant, room, outline, fingerprint, source_id)
                return
            await self._clear_pending_init(tenant.slug)
            self._open_initiative[tenant.slug] = resolved
            max_think = int(self._settings.pm_max_think_runs)
            max_ready = int(self._settings.pm_max_ready_passes)
            first_run, second_run = next_free_think_runs(resolved, listing.think_paths)
            occupied = ", ".join(listing.inits) if listing.inits else "(none)"
            meta = {
                "status": "in_progress",
                "outline_fingerprint": fingerprint,
                "source_message_id": source_id,
                "programme_slug": tenant.slug,
                "initiative": resolved,
                "hop": "t0",
                "max_think": max_think,
                "max_ready": max_ready,
            }
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.t0-using-init",
                    {
                        "initiative": resolved,
                        "meta_repo": tenant.meta_repo,
                        "occupied_inits": occupied,
                        "path_c1": think_path(resolved, first_run),
                        "path_c2": think_path(resolved, second_run),
                        "max_think": max_think,
                        "max_ready": max_ready,
                    },
                ),
                EventType.PROGRESS,
                meta,
            )
            await self._walk_pm_authoring(
                tenant,
                room,
                outline,
                resolved,
                source_message_id,
                meta,
                first_run=first_run,
                max_think=max_think,
                max_ready=max_ready,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception(
                "PM outline work failed", fingerprint=fingerprint, slug=tenant.slug
            )
            await self._status(
                room,
                self._copy("hermes.pm.status.failed", {"error": exc}),
                EventType.STALL,
                {
                    "status": "failed",
                    "outline_fingerprint": fingerprint,
                    "programme_slug": tenant.slug,
                    "source_message_id": source_id,
                },
            )
        finally:
            await self._release_outline(tenant.slug, fingerprint)
            self._open_initiative.pop(tenant.slug, None)
            if self._outline_tasks.get(tenant.slug) is asyncio.current_task():
                self._outline_tasks.pop(tenant.slug, None)
            if not awaiting_init:
                await self._clear_pending_init(tenant.slug)

    async def _walk_pm_authoring(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        *,
        first_run: int,
        max_think: int,
        max_ready: int,
    ) -> None:
        thinks: list[HermesArtifactRead] = []
        next_run = first_run
        fail_list = "(none)"
        while len(thinks) < 2:
            remaining = max_think - len(thinks) - 1
            prior = _prior_candidate_text(thinks[-1]) if thinks else ""
            artifact = await self._author_think_hop(
                tenant,
                room,
                outline,
                initiative,
                source_message_id,
                meta,
                run=next_run,
                remaining_thinks=max(remaining, 0),
                prior_candidate=prior,
                fail_list=fail_list,
            )
            thinks.append(artifact)
            initiative = artifact.initiative
            meta["initiative"] = initiative
            next_run += 1

        ready_passes = 0
        quality = await self._ready_pass(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            meta,
            thinks,
            pass_number=1,
            max_passes=max_ready,
        )
        ready_passes = 1
        stop_reason = ""
        if _any_handover(quality):
            stop_reason = "handover-yes"
        elif len(thinks) >= max_think:
            stop_reason = "max-think"
        elif ready_passes >= max_ready:
            stop_reason = "max-ready"
        else:
            fail_list = _fail_list_from_quality(quality)
            next_label = f"C{next_run}"
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.loop-continue",
                    {
                        "pass_number": ready_passes,
                        "max_passes": max_ready,
                        "label": next_label,
                        "claimed_path": think_path(initiative, next_run),
                        "fail_list": fail_list,
                        "think_runs": len(thinks),
                        "max_think": max_think,
                    },
                ),
                EventType.PROGRESS,
                {**meta, "hop": "loop"},
            )
            while len(thinks) < max_think:
                remaining = max_think - len(thinks) - 1
                prior = _prior_candidate_text(thinks[-1])
                artifact = await self._author_think_hop(
                    tenant,
                    room,
                    outline,
                    initiative,
                    source_message_id,
                    meta,
                    run=next_run,
                    remaining_thinks=max(remaining, 0),
                    prior_candidate=prior,
                    fail_list=fail_list,
                )
                thinks.append(artifact)
                next_run += 1
            quality = await self._ready_pass(
                tenant,
                room,
                outline,
                initiative,
                source_message_id,
                meta,
                thinks,
                pass_number=2,
                max_passes=max_ready,
            )
            ready_passes = 2
            stop_reason = "handover-yes" if _any_handover(quality) else "max-ready"

        await self._status(
            room,
            self._copy(
                "hermes.pm.status.loop-stop",
                {
                    "reason": stop_reason,
                    "think_runs": len(thinks),
                    "max_think": max_think,
                    "ready_passes": ready_passes,
                    "max_ready": max_ready,
                },
            ),
            EventType.PROGRESS,
            {**meta, "hop": "loop", "stop_reason": stop_reason},
        )
        await self._ask_then_recommend(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            {**meta, "stop_reason": stop_reason, "overall": quality.overall},
            thinks,
            quality,
        )

    async def _author_think_hop(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        *,
        run: int,
        remaining_thinks: int,
        prior_candidate: Any,
        fail_list: str,
    ) -> HermesArtifactRead:
        label = f"C{run}"
        claimed = think_path(initiative, run)
        hop = f"think-{label.lower()}"
        meta["hop"] = hop
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.think", {"label": label}),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.think-next",
                {
                    "label": label,
                    "initiative": initiative,
                    "claimed_path": claimed,
                    "remaining_thinks": remaining_thinks,
                },
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": f"think {label}"}),
            EventType.PROGRESS,
            meta,
        )
        artifact = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_think(
                HermesBriefRequest(
                    initiative=initiative,
                    outline=outline,
                    source_message_id=source_message_id,
                ),
                run=run,
                tenant=tenant,
                path=claimed,
                prior_candidate=prior_candidate,
                fail_list=fail_list,
                remaining_thinks=remaining_thinks,
            ),
        )
        self._raise_if_stub(artifact, f"think {label}")
        await self._publish_hop(
            tenant,
            room,
            artifact,
            f"docs({artifact.initiative}): prd-think {label}",
            {**meta, "hop": hop},
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.think-returned",
                {"label": label, "initiative": artifact.initiative},
            ),
            EventType.PROGRESS,
            {**meta, "hop": hop},
        )
        await self._post_logical(room, self._render_think_hop(artifact), {**meta, "hop": hop})
        return artifact

    async def _ready_pass(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        *,
        pass_number: int,
        max_passes: int,
    ) -> HermesArtifactRead:
        meta["hop"] = "quality"
        files = [_think_file_ref(item) for item in thinks]
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.quality"),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.quality-next",
                {
                    "initiative": initiative,
                    "pass_number": pass_number,
                    "max_passes": max_passes,
                },
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": "quality"}),
            EventType.PROGRESS,
            meta,
        )
        quality = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_quality(
                initiative=initiative,
                files=files,
                tenant=tenant,
                outline=outline,
                pass_number=pass_number,
                max_passes=max_passes,
                source_message_id=source_message_id,
            ),
        )
        self._raise_if_stub(quality, "quality")
        await self._publish_hop(
            tenant,
            room,
            quality,
            f"docs({initiative}): prd-quality",
            meta,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.quality-returned",
                {"pass_number": pass_number, "max_passes": max_passes},
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._post_logical(
            room,
            self._render_quality_hop(quality),
            {**meta, "hop": "quality", "overall": quality.overall},
        )
        return quality

    async def _ask_then_recommend(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
    ) -> None:
        ask, answers = await self._ask_pass(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            meta,
            thinks,
            quality,
        )
        if answers.get("_skip") == "stop":
            await self._clear_pending_ask(tenant.slug)
            await self._status(
                room,
                self._copy("hermes.pm.status.ask-stopped", {"initiative": initiative}),
                EventType.STALL,
                {**meta, "status": "stopped", "hop": "ask"},
            )
            await self._status(
                room,
                self._copy("hermes.pm.status.promote-is-you", {"initiative": initiative}),
                EventType.DONE,
                {**meta, "status": "done", "hop": "ask"},
            )
            return
        if not answers or answers.get("_skip"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-timeout-provisional",
                    {"initiative": initiative},
                ),
                EventType.PROGRESS,
                {**meta, "hop": "ask", "status": "provisional"},
            )
        await self._recommend_pass(
            tenant,
            room,
            outline,
            initiative,
            source_message_id,
            meta,
            thinks,
            quality,
            ask,
            answers,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.promote-is-you", {"initiative": initiative}),
            EventType.DONE,
            {
                **meta,
                "status": "done",
                "hop": "recommend",
                "overall": quality.overall,
            },
        )

    async def _ask_pass(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
    ) -> tuple[HermesArtifactRead, dict[str, str]]:
        meta = {**meta, "hop": "ask"}
        files = [_think_file_ref(item) for item in thinks]
        qpath = str(quality.payload.get("path") or quality_path(initiative))
        files.append(
            {
                "label": "quality",
                "path": qpath,
                "file_body": str(quality.payload.get("file_body") or quality.body),
            }
        )
        scorecard = self._render_quality_hop(quality)
        max_forks = int(self._settings.pm_max_ask_forks)
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.ask"),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-next",
                {"initiative": initiative, "max_forks": max_forks},
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": "ask"}),
            EventType.PROGRESS,
            meta,
        )
        artifact = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_ask(
                initiative=initiative,
                files=files,
                tenant=tenant,
                outline=outline,
                scorecard=scorecard,
                source_message_id=source_message_id,
            ),
        )
        self._raise_if_stub(artifact, "ask")
        await self._publish_hop(
            tenant,
            room,
            artifact,
            f"docs({initiative}): prd-ask",
            meta,
        )
        forks = list((artifact.payload.get("artifact") or {}).get("forks") or [])
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-returned",
                {"initiative": initiative, "fork_count": len(forks)},
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._post_logical(room, self._render_ask_hop(artifact), {**meta, "hop": "ask"})
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-card",
                {
                    "initiative": initiative,
                    "fork_block": _format_fork_block(forks),
                },
            ),
            EventType.PROGRESS,
            {**meta, "hop": "ask", "status": "need_ask", "choices": forks},
        )
        timeout = float(self._settings.pm_ask_wait_seconds)
        if not forks or timeout <= 0:
            return artifact, {}
        await self._store_pending_ask(
            tenant,
            room,
            outline,
            initiative,
            thinks,
            quality,
            forks,
        )
        answers = await self._wait_ask_answers(tenant.slug, timeout)
        await self._clear_pending_ask(tenant.slug)
        return artifact, answers

    async def _recommend_pass(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        initiative: str,
        source_message_id: Optional[UUID],
        meta: dict[str, Any],
        thinks: list[HermesArtifactRead],
        quality: HermesArtifactRead,
        ask: HermesArtifactRead,
        answers: dict[str, str],
    ) -> HermesArtifactRead:
        meta = {**meta, "hop": "recommend"}
        files = [_think_file_ref(item) for item in thinks]
        scorecard = self._render_quality_hop(quality)
        ask_file = str(ask.payload.get("file_body") or ask.body)
        await self._heartbeat(
            "adh.pm",
            self._copy("hermes.pm.heartbeat.recommend"),
            EventType.PROGRESS,
            tenant.ops_room,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.recommend-next", {"initiative": initiative}),
            EventType.PROGRESS,
            meta,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.calling-model", {"hop": "recommend"}),
            EventType.PROGRESS,
            meta,
        )
        artifact = await self._with_pm_progress(
            room,
            meta,
            self.run_pm_recommend(
                initiative=initiative,
                files=files,
                tenant=tenant,
                quality=quality,
                outline=outline,
                scorecard=scorecard,
                answers=_format_answers(answers),
                ask_file=ask_file,
                source_message_id=source_message_id,
            ),
        )
        self._raise_if_stub(artifact, "recommend")
        await self._publish_hop(
            tenant,
            room,
            artifact,
            f"docs({initiative}): prd-recommend",
            meta,
        )
        parsed = dict(artifact.payload.get("artifact") or {})
        pick = str(parsed.get("recommend") or "none")
        path = str(parsed.get("path") or artifact.payload.get("path") or "")
        ready = str(parsed.get("engineering_ready") or "no")
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.recommend-returned",
                {
                    "initiative": initiative,
                    "recommend": pick,
                    "engineering_ready": ready,
                },
            ),
            EventType.PROGRESS,
            meta,
        )
        await self._post_logical(
            room,
            self._render_recommend_hop(artifact),
            {**meta, "hop": "recommend"},
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.recommend-card",
                {
                    "initiative": initiative,
                    "recommend": pick,
                    "path": path or "(none)",
                    "engineering_ready": ready,
                    "why": str(parsed.get("why") or "(none)"),
                },
            ),
            EventType.PROGRESS,
            {
                **meta,
                "hop": "recommend",
                "status": "need_promote",
                "choices": [pick, "none", "iterate"],
            },
        )
        await self._store_pending_recommend(
            tenant,
            room,
            initiative,
            pick,
            path,
            think_paths=[str(item.get("path") or "") for item in files],
        )
        return artifact

    def _is_lead_text(self, message: MessageRead) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        return (message.identity_handle or "") == self._settings.lead_handle

    def _is_lead_stop(self, message: MessageRead) -> bool:
        return self._is_lead_text(message) and (message.body or "").strip().lower() == "stop"

    async def _try_lead_stop(self, tenant: TenantContext, room: str, message: MessageRead) -> bool:
        """Lead `stop` cancels think/quality/ask, not only an open /prd-ask wait."""
        if not self._is_lead_stop(message):
            return False
        if not self._tenant_has_open_work(tenant.slug) and tenant.slug not in self._outline_tasks:
            return False
        await self._halt_programme(tenant, room)
        return True

    async def _halt_programme(self, tenant: TenantContext, room: str) -> None:
        initiative = self._open_initiative.get(tenant.slug) or "(none)"
        task = self._outline_tasks.pop(tenant.slug, None)
        if task is not None and not task.done():
            task.cancel()
        event = self._ask_events.get(tenant.slug)
        if event is not None:
            self._ask_answers[tenant.slug] = {"_skip": "stop"}
            event.set()
        prefix = f"{tenant.slug}:"
        for token in list(self._inflight):
            if token.startswith(prefix):
                fingerprint = token[len(prefix) :]
                await self._release_outline(tenant.slug, fingerprint)
        await self._clear_pending_init(tenant.slug)
        await self._clear_pending_ask(tenant.slug)
        await self._clear_pending_recommend(tenant.slug)
        await self._status(
            room,
            self._copy("hermes.pm.status.lead-stopped", {"initiative": initiative}),
            EventType.STALL,
            {
                "lane": "pm",
                "hop": "loop",
                "status": "stopped",
                "initiative": initiative,
                "programme_slug": tenant.slug,
            },
        )
        self.logger.info("PM walk stopped by Lead", slug=tenant.slug, initiative=initiative)

    async def _try_ask_answer(self, tenant: TenantContext, room: str, message: MessageRead) -> bool:
        if not self._is_lead_text(message):
            return False
        pending = await self._load_pending_ask(tenant.slug)
        if pending is None:
            return False
        if str(pending.get("room") or room) != room:
            return False
        answers = parse_ask_answers(message.body)
        if answers is None:
            self.logger.info(
                "Ignored Lead chatter while /prd-ask is open",
                slug=tenant.slug,
            )
            return True
        if answers.get("_invalid"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-invalid",
                    {
                        "initiative": str(pending.get("initiative") or ""),
                        "reason": str(answers.get("_invalid")),
                    },
                ),
                EventType.STALL,
                {
                    "status": "ask_invalid",
                    "hop": "ask",
                    "reason": answers.get("_invalid"),
                    "initiative": pending.get("initiative"),
                    "programme_slug": tenant.slug,
                },
            )
            return True
        mismatch = validate_ask_answers(answers, list(pending.get("forks") or []))
        if mismatch:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-invalid",
                    {
                        "initiative": str(pending.get("initiative") or ""),
                        "reason": mismatch,
                    },
                ),
                EventType.STALL,
                {
                    "status": "ask_invalid",
                    "hop": "ask",
                    "reason": mismatch,
                    "initiative": pending.get("initiative"),
                    "programme_slug": tenant.slug,
                },
            )
            return True
        self._ask_answers[tenant.slug] = answers
        event = self._ask_events.get(tenant.slug)
        if event is not None:
            event.set()
            return True
        task = asyncio.create_task(self._continue_from_pending_ask(tenant, pending, answers))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)
        return True

    async def _try_promote_pick(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        if not self._is_lead_text(message):
            return False
        # A6: while ask is open, promote tokens are chatter (ask handler already claimed).
        if await self._load_pending_ask(tenant.slug) is not None:
            return False
        pick = parse_promote_pick(message.body)
        pending = await self._load_pending_recommend(tenant.slug)
        if pending is None:
            if pick is None or pick in {"none", "iterate", "skip"}:
                return False
            return await self._promote_recovery(tenant, room, pick)
        if str(pending.get("room") or room) != room:
            return False
        if pick is None:
            self.logger.info(
                "Ignored Lead chatter while /prd-recommend is open",
                slug=tenant.slug,
            )
            return True
        initiative = str(pending.get("initiative") or "")
        if pick in {"none", "iterate", "skip"}:
            await self._clear_pending_recommend(tenant.slug)
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.promote-skip",
                    {"initiative": initiative, "pick": pick},
                ),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_skip",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return True
        await self._promote_copy(
            tenant,
            room,
            initiative=initiative,
            pick=pick,
            preferred_path=str(pending.get("path") or ""),
            think_paths=list(pending.get("think_paths") or []),
        )
        await self._clear_pending_recommend(tenant.slug)
        return True

    async def _promote_recovery(self, tenant: TenantContext, room: str, pick: str) -> bool:
        """A7: promote when quality exists, PRD missing, even without awaiting-recommend."""
        listing = self._workspace.inventory(tenant)
        initiative = self._open_initiative.get(tenant.slug) or ""
        if not initiative and "prd/reports/" in pick.replace("\\", "/"):
            stem = Path(pick.replace("\\", "/")).name
            if stem.upper().endswith("-PRD-THINK.MD"):
                initiative = stem[: -len("-prd-think.md")]
            else:
                match = re.match(r"^(INIT-.+)-prd-think-\d+\.md$", stem, re.I)
                if match:
                    initiative = match.group(1)
        if not initiative and re.fullmatch(r"C\d+", pick, re.I):
            candidates: list[str] = []
            for init in listing.inits:
                qbody = self._workspace.read_local(tenant, quality_path(init))
                if not qbody.strip():
                    continue
                if self._workspace.read_local(tenant, prd_path(init)).strip():
                    continue
                candidates.append(init)
            if len(candidates) == 1:
                initiative = candidates[0]
        if not initiative:
            return False
        qpath = quality_path(initiative)
        if not self._workspace.read_local(tenant, qpath).strip():
            return False
        dest = prd_path(initiative)
        if self._workspace.read_local(tenant, dest).strip():
            await self._status(
                room,
                self._copy("hermes.pm.status.promote-already", {"initiative": initiative}),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_already",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return True
        think_paths = [
            path
            for path in listing.think_paths
            if path.startswith(f"prd/reports/{initiative}-prd-think")
        ]
        await self._promote_copy(
            tenant,
            room,
            initiative=initiative,
            pick=pick,
            preferred_path="",
            think_paths=think_paths,
        )
        return True

    async def _promote_copy(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        pick: str,
        preferred_path: str,
        think_paths: list[Any],
    ) -> None:
        dest = prd_path(initiative)
        if self._workspace.read_local(tenant, dest).strip():
            await self._status(
                room,
                self._copy("hermes.pm.status.promote-already", {"initiative": initiative}),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_already",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return
        source = self._resolve_promote_source(pick, preferred_path, think_paths)
        if not source:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.promote-unknown",
                    {"initiative": initiative, "pick": pick},
                ),
                EventType.STALL,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_unknown",
                    "pick": pick,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return
        body = self._workspace.read_local(tenant, source)
        if not body.strip():
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.promote-unknown",
                    {"initiative": initiative, "pick": pick},
                ),
                EventType.STALL,
                {
                    "lane": "pm",
                    "hop": "promote",
                    "status": "promote_unknown",
                    "pick": pick,
                    "path": source,
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                },
            )
            return
        result = await self._workspace.publish(
            tenant,
            dest,
            body,
            f"docs({initiative}): promote {pick} → prd",
        )
        local = result.get("local_path") or "skipped"
        github = result.get("github") or {}
        sha = ""
        if isinstance(github, dict):
            sha = str(github.get("commit_sha") or github.get("sha") or "")
        github_state = f"committed {sha[:7]}" if sha else "skipped"
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.promote-noted",
                {
                    "initiative": initiative,
                    "pick": pick,
                    "path": source,
                    "local": local,
                    "github_state": github_state,
                },
            ),
            EventType.PROGRESS,
            {
                "lane": "pm",
                "hop": "promote",
                "status": "promote_copied",
                "pick": pick,
                "source_path": source,
                "path": dest,
                "initiative": initiative,
                "programme_slug": tenant.slug,
                "publish": result,
            },
        )
        self.logger.info(
            "Promoted think file to PRD; Forge is not drafting; validate not started",
            slug=tenant.slug,
            pick=pick,
            initiative=initiative,
            source=source,
            dest=dest,
        )

    def _resolve_promote_source(
        self,
        pick: str,
        preferred_path: str,
        think_paths: list[Any],
    ) -> str:
        paths = [str(item) for item in think_paths if str(item or "").strip()]
        normalized = pick.replace("\\", "/")
        if "prd/reports/" in normalized and normalized.lower().endswith(".md"):
            return pick
        if re.fullmatch(r"C\d+", pick, re.I):
            index = int(pick[1:])
            if 1 <= index <= len(paths):
                return paths[index - 1]
            if preferred_path:
                return preferred_path
            return ""
        return preferred_path or ""

    async def _resume_pending_ask(self, tenant: TenantContext) -> None:
        pending = await self._load_pending_ask(tenant.slug)
        if pending is None:
            return
        if tenant.slug in self._ask_events:
            return
        room = str(pending.get("room") or tenant.ops_room)
        initiative = str(pending.get("initiative") or "")
        forks = list(pending.get("forks") or [])
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.ask-resume",
                {"initiative": initiative},
            ),
            EventType.PROGRESS,
            {
                "lane": "pm",
                "hop": "ask",
                "status": "need_ask",
                "initiative": initiative,
                "programme_slug": tenant.slug,
                "choices": forks,
            },
        )
        if forks:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-card",
                    {
                        "initiative": initiative,
                        "fork_block": _format_fork_block(forks),
                    },
                ),
                EventType.PROGRESS,
                {
                    "lane": "pm",
                    "hop": "ask",
                    "status": "need_ask",
                    "initiative": initiative,
                    "programme_slug": tenant.slug,
                    "choices": forks,
                },
            )
        task = asyncio.create_task(self._wait_then_continue_ask(tenant, pending))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    async def _wait_then_continue_ask(self, tenant: TenantContext, pending: dict[str, Any]) -> None:
        timeout = float(self._settings.pm_ask_wait_seconds)
        if timeout <= 0:
            answers: dict[str, str] = {}
        else:
            answers = await self._wait_ask_answers(tenant.slug, timeout)
        await self._continue_from_pending_ask(tenant, pending, answers)

    async def _continue_from_pending_ask(
        self,
        tenant: TenantContext,
        pending: dict[str, Any],
        answers: dict[str, str],
    ) -> None:
        await self._clear_pending_ask(tenant.slug)
        room = str(pending.get("room") or tenant.ops_room)
        initiative = str(pending.get("initiative") or "")
        outline = str(pending.get("outline") or "")
        if answers.get("_skip") == "stop":
            await self._status(
                room,
                self._copy("hermes.pm.status.ask-stopped", {"initiative": initiative}),
                EventType.STALL,
                {"status": "stopped", "hop": "ask", "initiative": initiative},
            )
            return
        thinks = self._thinks_from_paths(tenant, initiative, pending.get("think_paths") or [])
        qpath = str(pending.get("quality_path") or quality_path(initiative))
        qbody = self._workspace.read_local(tenant, qpath)
        quality = HermesArtifactRead(
            kind="pm_quality",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            body=qbody,
            payload={"path": qpath, "file_body": qbody, "artifact": {}, "hop": "quality"},
        )
        ask_body = self._workspace.read_local(tenant, ask_path(initiative))
        ask = HermesArtifactRead(
            kind="pm_ask",
            initiative=initiative,
            rubric_id=RUBRIC_PM["id"],
            body=ask_body,
            payload={
                "path": ask_path(initiative),
                "file_body": ask_body,
                "artifact": {"forks": pending.get("forks") or []},
                "hop": "ask",
            },
        )
        meta = {
            "initiative": initiative,
            "programme_slug": tenant.slug,
            "hop": "recommend",
            "status": "in_progress",
        }
        if not answers or answers.get("_skip"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.ask-timeout-provisional",
                    {"initiative": initiative},
                ),
                EventType.PROGRESS,
                {**meta, "hop": "ask", "status": "provisional"},
            )
        await self._recommend_pass(
            tenant,
            room,
            outline,
            initiative,
            None,
            meta,
            thinks,
            quality,
            ask,
            answers,
        )
        await self._status(
            room,
            self._copy("hermes.pm.status.promote-is-you", {"initiative": initiative}),
            EventType.DONE,
            {**meta, "status": "done", "hop": "recommend"},
        )

    def _thinks_from_paths(
        self, tenant: TenantContext, initiative: str, paths: list[Any]
    ) -> list[HermesArtifactRead]:
        thinks: list[HermesArtifactRead] = []
        for index, raw in enumerate(paths, start=1):
            path = str(raw or "")
            if not path:
                continue
            body = self._workspace.read_local(tenant, path)
            if not body.strip():
                continue
            label = f"C{index}"
            thinks.append(
                HermesArtifactRead(
                    kind=f"pm_think_{label.lower()}",
                    initiative=initiative,
                    rubric_id=RUBRIC_PM["id"],
                    body=body[:500],
                    payload={
                        "path": path,
                        "file_body": body,
                        "artifact": {"candidate_label": label},
                        "hop": f"think-{label.lower()}",
                    },
                )
            )
        return thinks

    def _is_lead_outline(self, message: MessageRead) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        handle = message.identity_handle or ""
        if handle != self._settings.lead_handle:
            return False
        return is_lead_outline_body(
            message.body or "",
            min_chars=int(self._settings.outline_min_chars),
        )

    def _is_lead_init_name(self, message: MessageRead, tenant: TenantContext) -> bool:
        if message.kind != MessageKind.MESSAGE:
            return False
        if (message.identity_handle or "") != self._settings.lead_handle:
            return False
        token = (message.body or "").strip().upper()
        prefix = tenant.init_prefix.rstrip("-").upper() + "-"
        if not token.startswith(prefix):
            return False
        if " " in token or "\n" in (message.body or ""):
            return False
        coerced = _coerce_init(token, tenant.slug)
        return _is_numbered_init(coerced, tenant)

    async def _on_named_init(self, tenant: TenantContext, room: str, message: MessageRead) -> None:
        pending = await self._load_pending_init(tenant.slug)
        if pending is None:
            return
        if str(pending.get("room") or room) != room:
            return
        initiative = _coerce_init((message.body or "").strip(), tenant.slug)
        if not _is_numbered_init(initiative, tenant):
            return
        fingerprint = str(pending.get("fingerprint") or "")
        source_id = str(pending.get("source_id") or "")
        outline = str(pending.get("outline") or "")
        if not fingerprint or not outline:
            return
        claimed = await self._claim_outline(tenant.slug, fingerprint, source_id)
        if not claimed:
            return
        await self._clear_pending_init(tenant.slug)
        source_uuid: Optional[UUID] = None
        try:
            source_uuid = UUID(source_id) if source_id else None
        except ValueError:
            source_uuid = None
        self._track_outline_task(
            tenant.slug,
            asyncio.create_task(
                self._run_outline_work(
                    tenant,
                    room,
                    outline,
                    fingerprint,
                    source_id,
                    source_uuid,
                    initiative=initiative,
                )
            ),
        )

    async def _resume_pending_outline(self, tenant: TenantContext) -> None:
        """Continue an outline that T0 stored while waiting for an INIT name."""
        pending = await self._load_pending_init(tenant.slug)
        if pending is None:
            return
        room = str(pending.get("room") or tenant.ops_room)
        if room != tenant.ops_room:
            return
        fingerprint = str(pending.get("fingerprint") or "")
        source_id = str(pending.get("source_id") or "")
        outline = str(pending.get("outline") or "")
        if not fingerprint or not outline:
            return
        claimed = await self._claim_outline(tenant.slug, fingerprint, source_id)
        if not claimed:
            return
        await self._clear_pending_init(tenant.slug)
        source_uuid: Optional[UUID] = None
        try:
            source_uuid = UUID(source_id) if source_id else None
        except ValueError:
            source_uuid = None
        self.logger.info(
            "Resuming outline with harness-allocated INIT",
            slug=tenant.slug,
            fingerprint=fingerprint,
        )
        await self._run_outline_work(
            tenant,
            room,
            outline,
            fingerprint,
            source_id,
            source_uuid,
        )
