"""Authoring programme: outline → think/quality → Hermes PM promote judgment.

Catalogue skills write think + quality artefacts. Hermes then runs its own
promote-judge hop (decision card: bluf / locking / revise-if) and briefs Lead.
Does not wait on ``/prd-critic``. Ask/recommend LiteLLM hops are retired.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Optional
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.hermes.collaboration.brief_service import HermesBriefService
from src.business_services.hermes.decision_card import (
    CARD_PROMOTE,
    DecisionCard,
    decision_card,
    parse_promote_decision_card,
)
from src.business_services.hermes.execution.dispatch_service import HermesDispatchService
from src.business_services.hermes.lead_tokens import (
    _coerce_init,
    _is_numbered_init,
    parse_promote_pick,
    promote_pick_wants_clean,
)
from src.business_services.hermes.promote_cleanup import (
    archive_dest,
    scratch_paths_for_initiative,
)
from src.business_services.hermes.runtime.session_store import (
    UNBOUND_INITIATIVE,
    HermesSessionStoreService,
)
from src.business_services.hermes.surface.buzz_poster import HermesBuzzPoster
from src.configs.hermes_settings import HermesSettings
from src.infra_services.pm_workspace_service import (
    PmWorkspaceService,
    hermes_promote_brief_path,
    next_free_think_runs,
    next_programme_init,
    prd_path,
    quality_path,
    think_path,
)
from src.models.buzz_models import EventType, MessageKind, MessageRead
from src.models.hermes.session_models import (
    AWAITING_CLARIFY,
    AWAITING_JUDGMENT,
    HermesProgrammeType,
    HermesSession,
)
from src.models.tenant_models import TenantContext

_PROGRAMME = HermesProgrammeType.AUTHORING
_SLOT_THINKS = "authoring_think_paths"
_SLOT_QUALITY = "authoring_quality_path"
_SLOT_OUTLINE = "authoring_outline"
_SLOT_PROMOTE_PATHS = "authoring_promote_paths"
_INIT_TOKEN = re.compile(r"\b(INIT-[A-Z0-9]+-\d+)\b", re.I)


class AuthoringProgrammeService(BaseBusinessService):
    """Skill-backed pre-promote authoring + session-backed promote gate."""

    @inject
    def __init__(
        self,
        store: HermesSessionStoreService,
        dispatch: HermesDispatchService,
        briefs: HermesBriefService,
        poster: HermesBuzzPoster,
        workspace: PmWorkspaceService,
    ) -> None:
        super().__init__()
        self._store = store
        self._dispatch = dispatch
        self._briefs = briefs
        self._poster = poster
        self._workspace = workspace
        self._settings = HermesSettings.get_instance()
        self._work_tasks: set[asyncio.Task[None]] = set()

    async def start_outline(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        *,
        fingerprint: str,
        source_id: str,
        source_message_id: Optional[UUID] = None,
        initiative: Optional[str] = None,
    ) -> None:
        listing = self._workspace.inventory(tenant)
        try:
            resolved = (
                _coerce_init(initiative, tenant.slug)
                if initiative
                else next_programme_init(tenant.init_prefix, listing.inits)
            )
        except ValueError:
            await self._ask_for_init(tenant, room, outline, fingerprint, source_id)
            return
        if not _is_numbered_init(resolved, tenant):
            await self._ask_for_init(tenant, room, outline, fingerprint, source_id)
            return
        session = HermesSession(
            tenant_slug=tenant.slug,
            room=room,
            initiative=resolved,
            programme=_PROGRAMME,
            stage="prd-think",
            slots={_SLOT_OUTLINE: outline, "fingerprint": fingerprint, "source_id": source_id},
        )
        await self._store.save(session)
        task = asyncio.create_task(self._run_authoring(tenant, room, session, source_message_id))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    async def handle_lead_message(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        """True when authoring session consumed the message (init / promote / stop)."""
        if (message.identity_handle or "") != self._settings.lead_handle:
            return False
        if message.kind != MessageKind.MESSAGE:
            return False
        body = (message.body or "").strip()
        authoring = [
            s for s in await self._store.list_active(tenant.slug) if s.programme == _PROGRAMME
        ]
        unbound = await self._store.load_unbound(tenant.slug)
        if unbound is not None and unbound.programme == _PROGRAMME and unbound not in authoring:
            authoring.append(unbound)
        if not authoring:
            # Promote recovery without session: C-label after prior recommend slot
            if parse_promote_pick(body) is not None:
                return await self._promote_without_session(tenant, room, body)
            return False
        if body.lower() == "stop":
            if len(authoring) == 1:
                init = authoring[0].initiative or UNBOUND_INITIATIVE
                await self._store.clear(tenant.slug, init)
                await self._poster.post_status(
                    room,
                    f"Authoring stopped for {authoring[0].initiative or 'unbound'}.",
                    EventType.STALL,
                )
                return True
            options = [s.initiative or "unbound" for s in authoring]
            await self._poster.post_status(
                room,
                (
                    "Several authoring sessions are open. "
                    f"Reply with an INIT id to stop (`{'` / `'.join(options)}`), "
                    "or `stop all`."
                ),
                EventType.STALL,
                {"status": "need_stop_pick", "initiatives": options},
            )
            return True
        if body.lower() == "stop all":
            for session in authoring:
                await self._store.clear(tenant.slug, session.initiative or UNBOUND_INITIATIVE)
            await self._poster.post_status(room, "All authoring sessions stopped.", EventType.STALL)
            return True
        # Prefer the session whose open brief matches this reply.
        matched = [
            s
            for s in authoring
            if s.open_brief is not None
            and s.slots.get(_SLOT_PROMOTE_PATHS)
            and (s.stage == "authoring-promote" or s.awaiting == AWAITING_JUDGMENT)
        ]
        from src.business_services.hermes.runtime.orchestrator_service import match_reply_token

        token_hits = [
            s
            for s in matched
            if s.open_brief is not None
            and match_reply_token(body, s.open_brief.reply_tokens) is not None
        ]
        if len(token_hits) > 1:
            options = [s.initiative or "?" for s in token_hits]
            await self._poster.post_status(
                room,
                (
                    "That reply matches more than one promote gate. "
                    f"Which initiative? (`{'` / `'.join(options)}`)"
                ),
                EventType.STALL,
                {"status": "need_init_pick", "initiatives": options},
            )
            return True
        session = (
            token_hits[0] if len(token_hits) == 1 else (matched[0] if len(matched) == 1 else None)
        )
        if session is None and len(authoring) == 1:
            session = authoring[0]
        if session is None:
            options = [s.initiative or "unbound" for s in authoring]
            await self._poster.post_status(
                room,
                (
                    "Several authoring sessions are open. "
                    f"Name the INIT (`{'` / `'.join(options)}`) or finish one gate first."
                ),
                EventType.STALL,
                {"status": "need_init_pick", "initiatives": options},
            )
            return True
        # Promote gate: open brief, or recover after collaborator ate the judgment.
        if session.slots.get(_SLOT_PROMOTE_PATHS) and (
            session.stage == "authoring-promote"
            or (session.awaiting == AWAITING_JUDGMENT and session.open_brief is not None)
        ):
            if await self._on_promote_reply(tenant, room, session, body):
                return True
        # Dig INIT while clarifying
        if session.awaiting == AWAITING_CLARIFY or not session.initiative:
            match = _INIT_TOKEN.search(body)
            if match:
                outline = session.slots.get(_SLOT_OUTLINE) or ""
                fingerprint = session.slots.get("fingerprint") or ""
                source_id = session.slots.get("source_id") or ""
                await self.start_outline(
                    tenant,
                    room,
                    outline,
                    fingerprint=fingerprint,
                    source_id=source_id,
                    initiative=match.group(1).upper(),
                )
                return True
        return True  # chatter while authoring open

    async def _ask_for_init(
        self,
        tenant: TenantContext,
        room: str,
        outline: str,
        fingerprint: str,
        source_id: str,
    ) -> None:
        prefix = (tenant.init_prefix or f"INIT-{tenant.slug.upper()}-").rstrip("-") + "-"
        session = HermesSession(
            tenant_slug=tenant.slug,
            room=room,
            programme=_PROGRAMME,
            awaiting=AWAITING_CLARIFY,
            slots={
                _SLOT_OUTLINE: outline,
                "fingerprint": fingerprint,
                "source_id": source_id,
            },
        )
        await self._store.save(session)
        await self._poster.post_status(
            room,
            f"Name an initiative id (example `{prefix}001`) to start authoring.",
            EventType.STALL,
            {"status": "need_init", "programme_slug": tenant.slug},
        )

    async def _run_authoring(
        self,
        tenant: TenantContext,
        room: str,
        session: HermesSession,
        source_message_id: Optional[UUID],
    ) -> None:
        del source_message_id  # skills use workspace baton; Buzz id is in slots
        initiative = session.initiative or ""
        outline = session.slots.get(_SLOT_OUTLINE) or ""
        max_think = int(self._settings.pm_max_think_runs)
        listing = self._workspace.inventory(tenant)
        first_run, _second = next_free_think_runs(initiative, listing.think_paths)
        think_paths: list[str] = []
        runs = max_think
        for offset in range(runs):
            run = first_run + offset
            path = think_path(initiative, run)
            label = f"C{run}"
            await self._poster.post_status(
                room,
                f"Running `/prd-think` → `{path}` ({label}) "
                f"({offset + 1}/{runs}; progress every "
                f"{int(self._settings.progress_seconds)}s)…",
                EventType.PROGRESS,
                {
                    "status": "in_progress",
                    "hop": f"think-{label.lower()}",
                    "initiative": initiative,
                    "think_index": offset + 1,
                    "think_total": runs,
                },
            )
            try:
                result = await self._dispatch.run_catalog_skill(
                    tenant,
                    "prd-think",
                    initiative,
                    extra_prompt=(
                        f"Brief/outline:\n{outline}\n\n"
                        f"Write candidate {label} to `{path}` in this turn. "
                        f"This is think {offset + 1} of {runs} — diverge from "
                        "prior candidates; do not clone an earlier C-file. "
                        "Treat the outline as Lead-approved for T1 locks. "
                        "Do not ask questions or wait. "
                        "Do not overwrite prd/{INIT}.md."
                    ),
                    on_progress=self._progress_callback(
                        room,
                        hop=f"think-{label.lower()}",
                        initiative=initiative,
                        label=label,
                    ),
                )
            except Exception as exc:
                self.logger.exception("prd-think failed", initiative=initiative)
                await self._poster.post_status(
                    room,
                    f"Think failed for {label}: {str(exc)[:200]}",
                    EventType.STALL,
                )
                return
            body = self._workspace.read_local(tenant, path)
            if not body.strip():
                await self._poster.post_status(
                    room,
                    f"Think produced no file at `{path}` (exit {result.exit_code}).",
                    EventType.STALL,
                )
                return
            think_paths.append(path)
            await self._poster.post_status(
                room,
                f"Think {label} ready (`{path}`).",
                EventType.PROGRESS,
            )
        if not think_paths:
            await self._poster.post_status(
                room, f"No think files for {initiative}.", EventType.STALL
            )
            return
        qpath = quality_path(initiative)
        await self._poster.post_status(
            room,
            f"Running `/prd-quality` for {initiative} "
            f"({len(think_paths)} candidates; progress every "
            f"{int(self._settings.progress_seconds)}s)…",
            EventType.PROGRESS,
            {"status": "in_progress", "hop": "quality", "initiative": initiative},
        )
        try:
            await self._dispatch.run_catalog_skill(
                tenant,
                "prd-quality",
                initiative,
                extra_prompt=(
                    "Act as a human PM evaluating think candidates for Lead. "
                    "Compare ALL candidates below, score them on the delivery bar, "
                    "and recommend exactly one C-label to promote "
                    f"(cap was {runs} thinks).\n"
                    + "\n".join(f"- {p}" for p in think_paths)
                    + f"\nWrite `{qpath}` with comparative rationale.\n"
                    "In Handover / Next (human), state the single recommended "
                    "C-label and a one-sentence why Lead should pick it "
                    "(concrete deltas vs the others — not 'from quality').\n"
                    "Do not install, invoke, or wait for `/prd-critic`. "
                    "Omit the Secondary (prd-critic) section entirely — "
                    "Hermes briefs Lead; critic is not required."
                ),
                on_progress=self._progress_callback(
                    room, hop="quality", initiative=initiative, label="quality"
                ),
            )
        except Exception as exc:
            self.logger.exception("prd-quality failed", initiative=initiative)
            await self._poster.post_status(
                room,
                f"Quality failed: {str(exc)[:200]}",
                EventType.STALL,
            )
            return
        labels = [f"C{_run_from_path(p)}" for p in think_paths]
        brief_path = hermes_promote_brief_path(initiative)
        await self._poster.post_status(
            room,
            f"Hermes PM evaluating think candidates for {initiative} "
            f"(decision card: bluf / locking / revise-if; progress every "
            f"{int(self._settings.progress_seconds)}s)…",
            EventType.PROGRESS,
            {"status": "in_progress", "hop": "promote-judge", "initiative": initiative},
        )
        try:
            await self._dispatch.run_hermes_copy(
                tenant,
                "hermes.pm.promote.judge",
                {
                    "initiative": initiative,
                    "think_list": "\n".join(
                        f"- {lab}: `{path}`" for lab, path in zip(labels, think_paths)
                    ),
                    "labels": ", ".join(labels),
                    "quality_path": qpath,
                    "brief_path": brief_path,
                    "extra": "(none)",
                },
                on_progress=self._progress_callback(
                    room,
                    hop="promote-judge",
                    initiative=initiative,
                    label="promote-judge",
                ),
                label="promote-judge",
            )
        except Exception as exc:
            self.logger.exception("Hermes promote judge failed", initiative=initiative)
            await self._poster.post_status(
                room,
                f"Hermes promote judgment failed: {str(exc)[:200]}",
                EventType.STALL,
            )
            return
        judgment = promote_brief_from_hermes(
            self._workspace.read_local(tenant, brief_path),
            think_paths,
        )
        if judgment is None:
            # Scorecard fallback only when Hermes brief artefact is missing/malformed.
            judgment = promote_brief_from_quality(
                self._workspace.read_local(tenant, qpath),
                think_paths,
            )
            brief_path = qpath
        reply_tokens = labels + ["skip", "none", "iterate"]
        if judgment.recommend and judgment.recommend not in reply_tokens:
            reply_tokens.insert(0, judgment.recommend)
        session.slots[_SLOT_THINKS] = json.dumps(think_paths)
        session.slots[_SLOT_QUALITY] = qpath
        session.slots[_SLOT_PROMOTE_PATHS] = json.dumps(
            {f"C{_run_from_path(p)}": p for p in think_paths}
        )
        session.stage = "authoring-promote"
        session.open_brief = self._briefs.build_brief(
            purpose="authoring-promote",
            node_id="authoring-promote",
            question=f"Which product bet should become the PRD for {initiative}?",
            example=judgment.example,
            options=[
                f"{lab} — copy `{think_paths[i]}` → `prd/{initiative}.md`"
                for i, lab in enumerate(labels)
            ],
            recommend=judgment.recommend,
            bluf=judgment.bluf,
            card_kind=CARD_PROMOTE,
            locking=list(judgment.locking),
            not_locking=list(judgment.not_locking),
            revise_if=list(judgment.revise_if),
            reply_tokens=reply_tokens,
            artefact_path=brief_path,
        )
        session.awaiting = AWAITING_JUDGMENT
        await self._store.save(session)
        await self._poster.post_status(
            room,
            self._briefs.format_brief_markdown(session.open_brief),
            EventType.PROGRESS,
            {"status": "need_promote", "initiative": initiative, "choices": labels},
        )

    async def _on_promote_reply(
        self, tenant: TenantContext, room: str, session: HermesSession, body: str
    ) -> bool:
        from src.business_services.hermes.runtime.orchestrator_service import match_reply_token

        brief = session.open_brief
        token = match_reply_token(body, brief.reply_tokens) if brief is not None else None
        pick_raw = token or parse_promote_pick(body)
        if pick_raw is None:
            if brief is not None:
                await self._poster.post_status(
                    room,
                    f"Reply with one of: {', '.join(f'`{t}`' for t in brief.reply_tokens)}",
                    EventType.STALL,
                )
                return True
            return False
        pick, clean = promote_pick_wants_clean(pick_raw if token is None else token)
        lowered = pick.lower()
        if lowered in {"skip", "none", "iterate", "stop"}:
            await self._store.clear(tenant.slug, session.initiative or UNBOUND_INITIATIVE)
            await self._poster.post_status(
                room,
                f"No promote for {session.initiative} (`{pick}`).",
                EventType.DONE,
            )
            return True
        paths = json.loads(session.slots.get(_SLOT_PROMOTE_PATHS) or "{}")
        source = paths.get(pick.upper()) or paths.get(pick) or ""
        if not source and "prd/reports/" in pick:
            source = pick.split("|")[0]
        if not source:
            await self._poster.post_status(room, f"Unknown promote pick `{pick}`.", EventType.STALL)
            return True
        initiative = session.initiative or ""
        dest = prd_path(initiative)
        contents = self._workspace.read_local(tenant, source)
        if not contents.strip():
            await self._poster.post_status(room, f"Empty think file `{source}`.", EventType.STALL)
            return True
        self._workspace.write_local(tenant, dest, contents)
        await self._store.clear(tenant.slug, initiative)
        await self._poster.post_status(
            room,
            self._poster.copy(
                "hermes.pm.status.promote-await-validate",
                {"initiative": initiative, "path": dest},
            ),
            EventType.PROGRESS,
            {
                "status": "awaiting_post_pm",
                "hop": "promote",
                "initiative": initiative,
                "path": dest,
                "programme_slug": tenant.slug,
            },
        )
        if clean:
            await self._archive_scratch(tenant, room, initiative)
        return True

    def _progress_callback(
        self,
        room: str,
        *,
        hop: str,
        initiative: str,
        label: str,
    ):
        """Buzz still-working posts every ``progress_seconds`` while Cursor runs."""
        # Quality hop keeps the body unprefixed (matches historical Buzz copy).
        prefix = "" if label == "quality" else label
        return self._poster.still_working_callback(
            room,
            hop=hop,
            initiative=initiative,
            label=prefix,
        )

    async def _promote_without_session(self, tenant: TenantContext, room: str, body: str) -> bool:
        """Legacy C-label promote when session was lost — inventory-based recovery."""
        pick_raw = parse_promote_pick(body)
        if pick_raw is None:
            return False
        pick, clean = promote_pick_wants_clean(pick_raw)
        if pick.lower() in {"skip", "none", "iterate"}:
            return True
        listing = self._workspace.inventory(tenant)
        initiative = ""
        if listing.inits:
            initiative = listing.inits[-1]
        if not initiative:
            return False
        paths = list(listing.think_paths)
        source = ""
        if re.fullmatch(r"C\d+", pick, re.I):
            index = int(pick[1:])
            if 1 <= index <= len(paths):
                source = paths[index - 1]
        elif "prd/reports/" in pick:
            source = pick
        if not source:
            return False
        contents = self._workspace.read_local(tenant, source)
        if not contents.strip():
            return False
        dest = prd_path(initiative)
        self._workspace.write_local(tenant, dest, contents)
        await self._poster.post_status(
            room,
            self._poster.copy(
                "hermes.pm.status.promote-await-validate",
                {"initiative": initiative, "path": dest},
            ),
            EventType.PROGRESS,
            {"status": "awaiting_post_pm", "initiative": initiative, "path": dest},
        )
        if clean:
            await self._archive_scratch(tenant, room, initiative)
        return True

    async def _archive_scratch(self, tenant: TenantContext, room: str, initiative: str) -> None:
        listing = self._workspace.inventory(tenant)
        candidates = list(listing.think_paths) + [
            f"prd/reports/{initiative}-prd-quality.md",
            f"prd/reports/{initiative}-prd-ask.md",
            f"prd/reports/{initiative}-prd-recommend.md",
        ]
        paths = scratch_paths_for_initiative(initiative, candidates)
        moves = [(path, archive_dest(path, initiative)) for path in paths]
        if not moves:
            return
        result = await self._workspace.archive_paths(
            tenant,
            moves,
            commit_message=f"docs({initiative}): archive pre-promote scratch",
        )
        archived = result.get("archived") or []
        path_list = (
            ", ".join(f"`{item.get('source')}` → `{item.get('dest')}`" for item in archived)
            or "(none)"
        )
        await self._poster.post_status(
            room,
            self._poster.copy(
                "hermes.pm.status.promote-archived",
                {"initiative": initiative, "paths": path_list},
            ),
            EventType.PROGRESS,
            {"status": "promote_archived", "initiative": initiative},
        )


def _run_from_path(path: str) -> int:
    match = re.search(r"-prd-think(?:-(\d+))?\.md$", path)
    if match is None:
        return 1
    return int(match.group(1) or "1")


# Back-compat name used by tests / callers.
PromoteBriefJudgment = DecisionCard

_RECOMMEND_ASSIGN = re.compile(r"recommend(?:_promote|)\s*[:=]\s*(C\d+)", re.I)
_RECOMMEND_ARROW = re.compile(r"\b(C\d+)\s*←")
_RECOMMEND_NEXT = re.compile(
    r"Recommended single pick[^\n]*?\*\*(C\d+)\*\*[^\n]*?(?:\(([^)]+)\))?",
    re.I,
)
_PREFER_LINE = re.compile(
    r"Prefer\s+(C\d+)\s+if[^.()]*\(([^)]+)\)",
    re.I,
)
_JOB_IN_SECTION = re.compile(
    r"###\s+(C\d+)\b[^\n]*\n.*?B1 Job\s*\|[^|\n]*\|[^|\n]*\|\s*" r"(?:Job:\s*)?[“\"]([^”\"]+)[”\"]",
    re.I | re.S,
)


def _recommend_from_quality(body: str, think_paths: list[str]) -> str:
    text = body or ""
    for pattern in (_RECOMMEND_NEXT, _RECOMMEND_ASSIGN, _RECOMMEND_ARROW):
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    prefer = _PREFER_LINE.search(text)
    if prefer:
        return prefer.group(1).upper()
    if think_paths:
        return f"C{_run_from_path(think_paths[-1])}"
    return ""


def _why_from_quality(body: str, recommend: str) -> str:
    text = body or ""
    next_pick = _RECOMMEND_NEXT.search(text)
    if next_pick and next_pick.group(1).upper() == recommend:
        detail = (next_pick.group(2) or "").strip()
        if detail:
            return detail.strip()
    prefer = _PREFER_LINE.search(text)
    if prefer and prefer.group(1).upper() == recommend:
        detail = (prefer.group(2) or "").strip()
        if detail:
            return detail.strip()
    if recommend:
        return f"Promote {recommend} — strongest scorecard pick among the think candidates."
    return "Quality did not name a winner — pick a C-label or skip."


def _example_from_quality(body: str, recommend: str) -> str:
    text = body or ""
    jobs = {m.group(1).upper(): m.group(2).strip() for m in _JOB_IN_SECTION.finditer(text)}
    job = jobs.get(recommend.upper(), "")
    if job:
        return f"If we promote {recommend}, the PRD locks this job: {job}"
    return (
        f"Choosing {recommend} copies that think to `prd/{{INIT}}.md`. "
        "Then say post-pm so validate can prove the public reader path."
    )


def promote_brief_from_quality(body: str, think_paths: list[str]) -> DecisionCard:
    """Fallback: thin decision card from quality when Hermes brief is missing."""
    recommend = _recommend_from_quality(body, think_paths)
    bluf = _why_from_quality(body, recommend)
    return decision_card(
        recommend=recommend,
        bluf=bluf if recommend else bluf,
        example=_example_from_quality(body, recommend),
        locking=(),
        not_locking=("none",),
        revise_if=("Hermes brief missing — re-read the think files before promoting",),
        card_kind=CARD_PROMOTE,
    )


def promote_brief_from_hermes(body: str, think_paths: list[str]) -> Optional[DecisionCard]:
    """Parse Hermes-owned promote decision card. None if malformed / empty."""
    allowed = [f"C{_run_from_path(p)}" for p in think_paths]
    return parse_promote_decision_card(body, allowed_labels=allowed)
