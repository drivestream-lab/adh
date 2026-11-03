"""Post-promote PM walk: validate → VF briefs → resolution → update → impact."""

from __future__ import annotations

# pyright: reportAttributeAccessIssue=false

import asyncio
import json
from typing import Any, Optional

from src.business_services.hermes.decision_cards import (
    apply_validate_briefs,
    format_validate_brief_block,
)
from src.business_services.hermes.lead_tokens import (
    parse_finding_answers,
    parse_impact_answer,
    parse_manifest_answer,
    parse_post_promote_gate,
    validate_finding_answers,
)
from src.business_services.hermes.promote_cleanup import (
    archive_dest,
    scratch_paths_for_initiative,
)
from src.business_services.hermes.validation_report import (
    format_resolution_markdown,
    impact_map_path,
    open_critical,
    parse_validation_findings,
    resolution_path,
    validation_report_path,
)
from src.infra_services.pm_workspace_service import prd_path
from src.models.buzz_models import EventType, MessageRead
from src.models.tenant_models import TenantContext


class PostPromoteWalkMixin:
    """Lead post-promote gate + skill hops + ask-shaped decision briefs."""

    async def _try_post_promote_gate(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        if not self._is_lead_text(message):
            return False
        pending = await self._load_pending_post_promote(tenant.slug)
        if pending is None:
            return False
        if str(pending.get("room") or room) != room:
            return False
        token = parse_post_promote_gate(message.body)
        if token is None:
            self.logger.info(
                "Ignored Lead chatter while awaiting post-promote validate/clean",
                slug=tenant.slug,
            )
            return True
        if token == "stop":
            await self._halt_programme(tenant, room)
            return True
        initiative = str(pending.get("initiative") or "")
        if token == "clean":
            await self._archive_scratch(tenant, room, initiative)
            return True
        if token.startswith("retry:"):
            hop = token.split(":", 1)[1]
            if hop == "validate":
                await self._clear_pending_post_promote(tenant.slug)
                task = asyncio.create_task(self._run_post_promote(tenant, room, initiative))
                self._work_tasks.add(task)
                task.add_done_callback(self._work_tasks.discard)
            return True
        # validate
        await self._clear_pending_post_promote(tenant.slug)
        task = asyncio.create_task(self._run_post_promote(tenant, room, initiative))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)
        return True

    async def _try_finding_answers(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        if not self._is_lead_text(message):
            return False
        pending = await self._load_pending_validate_decisions(tenant.slug)
        if pending is None:
            return False
        if str(pending.get("room") or room) != room:
            return False
        answers = parse_finding_answers(message.body)
        if answers is None:
            self.logger.info(
                "Ignored Lead chatter while VF decisions are open",
                slug=tenant.slug,
            )
            return True
        if answers.get("_invalid"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.validate-invalid",
                    {
                        "initiative": str(pending.get("initiative") or ""),
                        "reason": str(answers.get("_invalid")),
                    },
                ),
                EventType.STALL,
                {"status": "validate_invalid", "hop": "validate"},
            )
            return True
        if answers.get("_skip") == "stop":
            await self._halt_programme(tenant, room)
            return True
        open_ids = [str(item.get("id") or "") for item in pending.get("wave") or []]
        mismatch = validate_finding_answers(answers, open_ids)
        if mismatch:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.validate-invalid",
                    {
                        "initiative": str(pending.get("initiative") or ""),
                        "reason": mismatch,
                    },
                ),
                EventType.STALL,
                {"status": "validate_invalid", "hop": "validate"},
            )
            return True
        if answers.get("_accept_recs"):
            answers = {
                str(item.get("id") or ""): str(item.get("recommend") or "fix")
                for item in pending.get("wave") or []
                if item.get("id")
            }
        # explain: deepen one brief, do not advance
        explains = {k: v for k, v in answers.items() if v == "explain"}
        decisions = {k: v for k, v in answers.items() if v != "explain" and not k.startswith("_")}
        if explains and not decisions:
            for fid in explains:
                brief = next(
                    (item for item in pending.get("wave") or [] if item.get("id") == fid),
                    None,
                )
                if brief:
                    await self._status(
                        room,
                        self._copy(
                            "hermes.pm.status.validate-explain",
                            {
                                "initiative": str(pending.get("initiative") or ""),
                                "brief_block": format_validate_brief_block([brief]),
                            },
                        ),
                        EventType.PROGRESS,
                        {"status": "need_validate_decisions", "hop": "validate"},
                    )
            return True
        stored = dict(pending.get("decisions") or {})
        stored.update(decisions)
        pending["decisions"] = stored
        wave_ids = {str(item.get("id") or "") for item in pending.get("wave") or []}
        answered_wave = wave_ids.issubset(set(stored))
        await self._store_pending_validate_decisions(tenant, pending)
        if not answered_wave:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.validate-partial",
                    {
                        "initiative": str(pending.get("initiative") or ""),
                        "answered": str(len(stored)),
                        "wave_size": str(len(wave_ids)),
                    },
                ),
                EventType.PROGRESS,
                {"status": "need_validate_decisions", "hop": "validate"},
            )
            return True
        task = asyncio.create_task(self._continue_validate_decisions(tenant, pending))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)
        return True

    async def _try_manifest_answer(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        if not self._is_lead_text(message):
            return False
        pending = await self._load_pending_update_manifest(tenant.slug)
        if pending is None:
            return False
        if str(pending.get("room") or room) != room:
            return False
        answers = parse_manifest_answer(message.body)
        if answers is None:
            return True
        if answers.get("_invalid"):
            return True
        if answers.get("_all") == "stop":
            await self._halt_programme(tenant, room)
            return True
        task = asyncio.create_task(self._continue_manifest(tenant, pending, answers))
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)
        return True

    async def _try_impact_answer(
        self, tenant: TenantContext, room: str, message: MessageRead
    ) -> bool:
        if not self._is_lead_text(message):
            return False
        pending = await self._load_pending_impact_confirm(tenant.slug)
        if pending is None:
            return False
        if str(pending.get("room") or room) != room:
            return False
        token = parse_impact_answer(message.body)
        if token is None:
            return True
        if token == "stop":
            await self._halt_programme(tenant, room)
            return True
        initiative = str(pending.get("initiative") or "")
        await self._clear_pending_impact_confirm(tenant.slug)
        if token == "revise":
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.impact-revise",
                    {"initiative": initiative},
                ),
                EventType.STALL,
                {"status": "impact_revise", "hop": "impact"},
            )
            return True
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.impact-confirmed",
                {
                    "initiative": initiative,
                    "path": impact_map_path(initiative),
                },
            ),
            EventType.DONE,
            {
                "status": "forge_baton_ready",
                "hop": "impact",
                "initiative": initiative,
                "programme_slug": tenant.slug,
            },
        )
        # Keep a soft post-promote gate so Lead can still `clean` or `stop`.
        await self._store_pending_post_promote(tenant, room, initiative, prd_path(initiative))
        return True

    async def _enter_post_promote_gate(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        *,
        clean_after: bool = False,
    ) -> None:
        dest = prd_path(initiative)
        await self._store_pending_post_promote(
            tenant, room, initiative, dest, clean_after=clean_after
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.promote-await-validate",
                {"initiative": initiative, "path": dest},
            ),
            EventType.PROGRESS,
            {
                "status": "awaiting_validate",
                "hop": "promote",
                "initiative": initiative,
                "path": dest,
                "programme_slug": tenant.slug,
            },
        )
        if clean_after:
            await self._archive_scratch(tenant, room, initiative)

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
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.promote-archived",
                    {"initiative": initiative, "paths": "(none)"},
                ),
                EventType.PROGRESS,
                {"status": "promote_archived", "hop": "clean"},
            )
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
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.promote-archived",
                {"initiative": initiative, "paths": path_list},
            ),
            EventType.PROGRESS,
            {
                "status": "promote_archived",
                "hop": "clean",
                "archive": result,
                "initiative": initiative,
            },
        )

    async def _run_post_promote(self, tenant: TenantContext, room: str, initiative: str) -> None:
        self._open_initiative[tenant.slug] = initiative
        passes = 0
        max_passes = int(self._settings.pm_max_post_validate_passes)
        while passes < max_passes:
            passes += 1
            ok = await self._validate_pass(tenant, room, initiative, pass_number=passes)
            if not ok:
                return
            findings = parse_validation_findings(
                self._workspace.read_local(tenant, validation_report_path(initiative))
            )
            if not findings:
                await self._status(
                    room,
                    self._copy(
                        "hermes.pm.status.zero-findings-skip",
                        {"initiative": initiative},
                    ),
                    EventType.PROGRESS,
                    {"status": "zero_findings", "hop": "validate"},
                )
                await self._impact_pass(tenant, room, initiative)
                return
            if not open_critical(findings) and passes > 1:
                await self._impact_pass(tenant, room, initiative)
                return
            await self._validate_decision_pass(tenant, room, initiative, findings)
            return

    async def _validate_pass(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        *,
        pass_number: int,
    ) -> bool:
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.validate-next",
                {"initiative": initiative, "pass_number": pass_number},
            ),
            EventType.PROGRESS,
            {"status": "in_progress", "hop": "validate", "initiative": initiative},
        )
        runner = getattr(self, "_skill_runner", None)
        if runner is None:
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.skill-failed",
                    {"initiative": initiative, "hop": "validate", "error": "runner missing"},
                ),
                EventType.STALL,
                {"status": "skill_failed", "hop": "validate"},
            )
            await self._store_pending_post_promote(tenant, room, initiative, prd_path(initiative))
            return False
        try:
            result = await runner.run_skill(
                tenant,
                "validate-requirements",
                initiative,
                extra_prompt=(f"Pass {pass_number}. Write {validation_report_path(initiative)}."),
            )
        except Exception as exc:
            self.logger.exception("validate skill failed", initiative=initiative)
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.skill-failed",
                    {
                        "initiative": initiative,
                        "hop": "validate",
                        "error": str(exc)[:200],
                    },
                ),
                EventType.STALL,
                {"status": "skill_failed", "hop": "validate"},
            )
            await self._store_pending_post_promote(tenant, room, initiative, prd_path(initiative))
            return False
        if not result.get("ok"):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.skill-failed",
                    {
                        "initiative": initiative,
                        "hop": "validate",
                        "error": f"exit {result.get('exit_code')}",
                    },
                ),
                EventType.STALL,
                {"status": "skill_failed", "hop": "validate"},
            )
            await self._store_pending_post_promote(tenant, room, initiative, prd_path(initiative))
            return False
        body = self._workspace.read_local(tenant, validation_report_path(initiative))
        if not body.strip():
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.skill-failed",
                    {
                        "initiative": initiative,
                        "hop": "validate",
                        "error": "empty validation report",
                    },
                ),
                EventType.STALL,
                {"status": "skill_failed", "hop": "validate"},
            )
            await self._store_pending_post_promote(tenant, room, initiative, prd_path(initiative))
            return False
        return True

    async def _validate_decision_pass(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        findings: list[dict[str, Any]],
        *,
        prior_decisions: Optional[dict[str, str]] = None,
    ) -> None:
        unanswered = [
            row for row in findings if str(row.get("id") or "") not in (prior_decisions or {})
        ]
        if not unanswered:
            await self._finish_findings(tenant, room, initiative, findings, prior_decisions or {})
            return
        limit = int(self._settings.pm_max_validate_briefs)
        wave = unanswered[:limit]
        briefs = await self._build_validate_briefs(initiative, wave)
        pending = {
            "room": room,
            "initiative": initiative,
            "findings": findings,
            "wave": briefs,
            "decisions": dict(prior_decisions or {}),
        }
        await self._store_pending_validate_decisions(tenant, pending)
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.validate-card",
                {
                    "initiative": initiative,
                    "brief_block": format_validate_brief_block(briefs),
                },
            ),
            EventType.PROGRESS,
            {
                "status": "need_validate_decisions",
                "hop": "validate",
                "initiative": initiative,
                "choices": [item.get("id") for item in briefs],
            },
        )

    async def _build_validate_briefs(
        self, initiative: str, wave: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        try:
            card = await self._prompts.complete(
                "hermes.pm.validate.card",
                {
                    "initiative": initiative,
                    "prd_path": prd_path(initiative),
                    "findings": json.dumps(wave, ensure_ascii=False),
                },
                model=self._settings.model_for_lane("pm"),
            )
            return apply_validate_briefs(wave, dict(card.parsed))
        except Exception:
            self.logger.exception("validate card failed; using frozen fallback")
            return apply_validate_briefs(wave, {"briefs": []})

    async def _continue_validate_decisions(
        self, tenant: TenantContext, pending: dict[str, Any]
    ) -> None:
        initiative = str(pending.get("initiative") or "")
        room = str(pending.get("room") or tenant.ops_room)
        findings = list(pending.get("findings") or [])
        decisions = dict(pending.get("decisions") or {})
        unanswered = [row for row in findings if str(row.get("id") or "") not in decisions]
        if unanswered:
            await self._validate_decision_pass(
                tenant, room, initiative, findings, prior_decisions=decisions
            )
            return
        await self._clear_pending_validate_decisions(tenant.slug)
        await self._finish_findings(tenant, room, initiative, findings, decisions)

    async def _finish_findings(
        self,
        tenant: TenantContext,
        room: str,
        initiative: str,
        findings: list[dict[str, Any]],
        decisions: dict[str, str],
    ) -> None:
        body = format_resolution_markdown(initiative, decisions, findings)
        await self._workspace.publish(
            tenant,
            resolution_path(initiative),
            body,
            f"docs({initiative}): resolution from Lead VF answers",
        )
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.resolution-wrote",
                {"initiative": initiative, "path": resolution_path(initiative)},
            ),
            EventType.PROGRESS,
            {"status": "resolution_wrote", "hop": "review"},
        )
        await self._update_pass(tenant, room, initiative)

    async def _update_pass(self, tenant: TenantContext, room: str, initiative: str) -> None:
        runner = getattr(self, "_skill_runner", None)
        if runner is None:
            await self._impact_pass(tenant, room, initiative)
            return
        try:
            result = await runner.run_skill(
                tenant,
                "update-documents",
                initiative,
                extra_prompt=(
                    f"Resolution mode using {resolution_path(initiative)}. "
                    "Prepare the change manifest; apply only after Lead confirms."
                ),
            )
        except Exception as exc:
            self.logger.exception("update skill failed")
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.skill-failed",
                    {"initiative": initiative, "hop": "update", "error": str(exc)[:200]},
                ),
                EventType.STALL,
                {"status": "skill_failed", "hop": "update"},
            )
            return
        # Present a simple whole-manifest gate; per-CHG when skill emits CHG rows later.
        pending = {
            "room": room,
            "initiative": initiative,
            "chgs": [{"id": "CHG-01", "recommend": "apply"}],
            "skill_ok": bool(result.get("ok")),
        }
        await self._store_pending_update_manifest(tenant, pending)
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.manifest-card",
                {
                    "initiative": initiative,
                    "brief_block": (
                        "### Change manifest\n\n"
                        "**In real life.** Applying updates the promoted PRD from your VF decisions.\n\n"
                        "**We recommend.** `apply` — keep the PRD aligned with what you just decided.\n\n"
                        "Reply `apply`, `hold`, or `CHG-01: apply`."
                    ),
                },
            ),
            EventType.PROGRESS,
            {"status": "need_manifest", "hop": "update"},
        )

    async def _continue_manifest(
        self,
        tenant: TenantContext,
        pending: dict[str, Any],
        answers: dict[str, str],
    ) -> None:
        room = str(pending.get("room") or tenant.ops_room)
        initiative = str(pending.get("initiative") or "")
        await self._clear_pending_update_manifest(tenant.slug)
        all_token = answers.get("_all")
        if all_token == "hold" or (
            not all_token and all(v == "hold" for k, v in answers.items() if not k.startswith("_"))
        ):
            await self._status(
                room,
                self._copy(
                    "hermes.pm.status.manifest-held",
                    {"initiative": initiative},
                ),
                EventType.STALL,
                {"status": "manifest_held", "hop": "update"},
            )
            return
        # Re-validate after apply intent
        ok = await self._validate_pass(tenant, room, initiative, pass_number=2)
        if not ok:
            return
        findings = parse_validation_findings(
            self._workspace.read_local(tenant, validation_report_path(initiative))
        )
        if open_critical(findings):
            await self._validate_decision_pass(tenant, room, initiative, findings)
            return
        await self._impact_pass(tenant, room, initiative)

    async def _impact_pass(self, tenant: TenantContext, room: str, initiative: str) -> None:
        runner = getattr(self, "_skill_runner", None)
        if runner is not None:
            try:
                await runner.run_skill(
                    tenant,
                    "prd-impact-map",
                    initiative,
                    extra_prompt=f"Write {impact_map_path(initiative)}. Do not open a PR.",
                )
            except Exception:
                self.logger.exception("impact skill failed")
                await self._status(
                    room,
                    self._copy(
                        "hermes.pm.status.skill-failed",
                        {
                            "initiative": initiative,
                            "hop": "impact",
                            "error": "impact skill failed",
                        },
                    ),
                    EventType.STALL,
                    {"status": "skill_failed", "hop": "impact"},
                )
                return
        body = self._workspace.read_local(tenant, impact_map_path(initiative))
        excerpt = "\n".join(body.splitlines()[:40]) if body.strip() else "(impact map missing)"
        pending = {"room": room, "initiative": initiative}
        await self._store_pending_impact_confirm(tenant, pending)
        await self._status(
            room,
            self._copy(
                "hermes.pm.status.impact-card",
                {
                    "initiative": initiative,
                    "brief_block": (
                        f"### Impact map for {initiative}\n\n"
                        f"**In real life.** This is the repo blast radius before Forge drafts.\n\n"
                        f"**We recommend.** `confirm` if the affected/not-affected list matches your intent.\n\n"
                        f"```\n{excerpt}\n```\n\n"
                        "Reply `confirm` or `revise`. Forge will not draft from Hermes."
                    ),
                },
            ),
            EventType.PROGRESS,
            {"status": "need_impact_confirm", "hop": "impact"},
        )
