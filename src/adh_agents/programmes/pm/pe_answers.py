"""PM auto-answers PE product questions (agent↔agent — no human ack gate)."""

from __future__ import annotations

from injector import inject

from src.adh_agents.baton.models import Baton
from src.adh_agents.baton.redis_store import RedisBatonStore
from src.adh_agents.collaboration.okf_context import load_okf_context
from src.adh_agents.forge_acl import forge_allowed
from src.adh_agents.settings import PmAgentSettings
from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.base_business_service import BaseBusinessService
from src.infra_services.forge_action_service import ForgeActionService
from src.infra_services.litellm_service import LiteLLMService
from src.infra_services.pm_workspace_service import PmWorkspaceService
from src.logging import get_logger
from src.models.buzz_models import EventType
from src.models.tenant_models import TenantContext

logger = get_logger()


def pm_pe_answers_path(initiative: str) -> str:
    return f"prd/reports/{initiative.strip().upper()}-pm-pe-answers.md"


class PmPeAnswersProgramme(BaseBusinessService):
    """Answer PE questions on the product PR; emit pe.pm_answers for settle."""

    programme_id = "pm-pe-answers"
    role_id = "adh.pm"

    @inject
    def __init__(
        self,
        batons: RedisBatonStore,
        poster: HermesBuzzPoster,
        workspace: PmWorkspaceService,
        forge: ForgeActionService,
        litellm: LiteLLMService,
    ) -> None:
        super().__init__()
        self._batons = batons
        self._poster = poster
        self._workspace = workspace
        self._forge = forge
        self._litellm = litellm
        self._settings = PmAgentSettings.get_instance()

    async def answer_pe_questions(
        self,
        tenant: TenantContext,
        room: str,
        baton: Baton,
    ) -> str:
        """Write answers artefact, comment PR, emit pe.pm_answers. Returns answers path."""
        init = (baton.initiative or "").strip().upper()
        payload = baton.payload or {}
        questions_path = str(payload.get("questions_path") or "")
        pr_url = str(payload.get("pr_url") or "")
        round_n = str(payload.get("round") or "1")
        questions_body = (
            self._workspace.read_local(tenant, questions_path) if questions_path else ""
        )
        from src.adh_agents.programmes.pm.validation_report import impact_map_path

        impact = self._workspace.read_local(tenant, impact_map_path(init))
        if not impact.strip():
            for cand in (
                f"prd/reports/IMPACT-MAP-{init}.md",
                f"prd/reports/{init}-impact-map.md",
            ):
                impact = self._workspace.read_local(tenant, cand)
                if impact.strip():
                    break
        prd = self._workspace.read_local(tenant, f"prd/{init}.md")
        okf = load_okf_context(
            tenant.meta_root,
            repo_names=list(tenant.repos.keys()) if tenant.repos else [],
        )
        answers_md = await self._llm_answers(
            initiative=init,
            round_n=round_n,
            questions_body=questions_body or "(questions artefact missing)",
            impact_map=impact[:8000],
            prd=prd[:8000],
            okf=okf,
        )
        rel = pm_pe_answers_path(init)
        self._workspace.write_local(tenant, rel, answers_md)
        await self._poster.post_status(
            room,
            (
                f"PM answered product questions for **{init}** (round {round_n}).\n"
                f"Artefact: `{rel}`"
            ),
            EventType.PROGRESS,
            {
                "status": "pm_pe_answered",
                "initiative": init,
                "round": round_n,
                "answers_path": rel,
            },
        )
        pr_number = _pr_number_from_url(pr_url)
        if pr_number is not None and forge_allowed(self.role_id, "comment_pr"):
            try:
                app = self._workspace.pm_app_role()
                result = await self._forge.comment_pr(
                    app=app,
                    repo=tenant.meta_repo,
                    pr_number=pr_number,
                    body=(
                        f"## PM clarification answers — {init} (round {round_n})\n\n"
                        f"{answers_md}\n"
                    ),
                )
                await self._poster.post_status(
                    room,
                    f"Posted PM answers on product PR #{pr_number}: {result.url or 'ok'}",
                    EventType.DONE,
                    {"status": "pm_answers_pr_comment", "initiative": init},
                )
            except Exception as exc:
                self.logger.exception("PM answers PR comment failed", initiative=init)
                await self._poster.post_status(
                    room,
                    f"PM answers artefact ready (`{rel}`) but PR comment failed: {exc}",
                    EventType.STALL,
                )
        await self._emit_pe_pm_answers(
            tenant,
            room,
            initiative=init,
            answers_path=rel,
            questions_path=questions_path,
            pr_url=pr_url,
            round_n=round_n,
        )
        return rel

    async def _llm_answers(
        self,
        *,
        initiative: str,
        round_n: str,
        questions_body: str,
        impact_map: str,
        prd: str,
        okf: str,
    ) -> str:
        system = (
            "You are adh.pm — product manager for a multi-repo programme. "
            "Answer each PE product question with a clear product stance. "
            "Cite Impact-Map / PRD / OKF when possible. "
            "Do not invent repos. Prefer Buying/Not buying style bullets. "
            "Return markdown only with ## Answers then one ### per PQ id."
        )
        user = (
            f"Initiative: {initiative}\nRound: {round_n}\n\n"
            f"## OKF context\n{okf or '(none yet)'}\n\n"
            f"## Impact-Map (excerpt)\n{impact_map or '(missing)'}\n\n"
            f"## PRD (excerpt)\n{prd or '(missing)'}\n\n"
            f"## PE questions\n{questions_body}\n"
        )
        try:
            await self._litellm.initialize()
            text = await self._litellm.complete(
                system=system,
                user=user,
                max_tokens=2500,
                temperature=0.2,
            )
            body = (text or "").strip()
            if body:
                return (
                    f"# PM clarification answers — {initiative}\n\n"
                    f"> Round **{round_n}**. Posted by **adh.pm** (agent↔agent rally).\n\n"
                    f"{body}\n"
                )
        except Exception:
            self.logger.exception(
                "PM LLM answers failed; using deterministic stub", init=initiative
            )
        return _deterministic_answers(initiative, round_n, questions_body)

    async def _emit_pe_pm_answers(
        self,
        tenant: TenantContext,
        room: str,
        *,
        initiative: str,
        answers_path: str,
        questions_path: str,
        pr_url: str,
        round_n: str,
    ) -> None:
        ttl = int(self._settings.baton_ttl_seconds)
        baton = Baton(
            type="pe.pm_answers",
            from_role=self.role_id,
            to_role="adh.pe",
            tenant=tenant.slug,
            ops_room=room,
            initiative=initiative,
            idempotency_key=f"pe.pm_answers:{tenant.slug}:{initiative}:r{round_n}",
            payload={
                "answers_path": answers_path,
                "questions_path": questions_path,
                "pr_url": pr_url,
                "round": round_n,
            },
            artefact_refs=[answers_path],
        )
        stored, created = await self._batons.create_pending(baton, ttl=ttl)
        if not created:
            logger.info(
                "pe.pm_answers baton idempotent (no Buzz)",
                baton_id=stored.id,
                initiative=initiative,
            )
            return
        await self._poster.post_status(
            room,
            (
                f"@{baton.to_role} baton `pe.pm_answers` (init={initiative}; "
                f"correlation={stored.correlation_id})"
            ),
            EventType.PROGRESS,
            {
                "status": "baton_emitted",
                "collab": True,
                "baton_type": "pe.pm_answers",
                "baton_id": stored.id,
                "idempotency_key": stored.idempotency_key,
                "tenant": tenant.slug,
                "initiative": initiative,
                "created": True,
            },
        )


def _deterministic_answers(initiative: str, round_n: str, questions_body: str) -> str:
    """Fail-closed stub when LLM is down — still advances the rally."""
    lines = [
        f"# PM clarification answers — {initiative}",
        "",
        f"> Round **{round_n}**. Deterministic stub (LLM unavailable).",
        "",
        "## Answers",
        "",
        "### Stance",
        "",
        "- **Buying.** Keep Impact-Map repo/contract scope as written for this wave.",
        "- **Not buying.** Silent scope expansion beyond the map.",
        "- **Open.** Any PQ the PE marked conflict/unknown should be called out in the "
        "settled brief for human review before merge.",
        "",
        "## Source questions (echo)",
        "",
        "```",
        (questions_body or "")[:2000],
        "```",
        "",
    ]
    return "\n".join(lines)


def _pr_number_from_url(pr_url: str) -> int | None:
    parts = (pr_url or "").rstrip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "pull" and parts[-1].isdigit():
        return int(parts[-1])
    return None
