"""GitHub issue/label → durable Buzz task bind (poll stub; no webhook dual path)."""

from __future__ import annotations

from typing import Optional

from injector import inject

from src.adh_agents.surface.buzz_poster import HermesBuzzPoster
from src.business_services.buzz_service import BuzzService
from src.infra_services.tenant_registry_service import TenantRegistryService
from src.logging import get_logger
from src.models.buzz_models import (
    EventType,
    RoomMemberCreate,
    TaskCreate,
    TaskEventCreate,
    TaskEventKind,
    TaskKind,
    TaskRead,
    TaskSource,
    TaskState,
)
from src.models.tenant_models import TenantContext

logger = get_logger()

# RealWorld guinea-pig labels → task kind.
_LABEL_KIND: dict[str, TaskKind] = {
    "bug": TaskKind.BUG,
    "enhancement": TaskKind.ENHANCEMENT,
    "adh:bug": TaskKind.BUG,
    "adh:enhancement": TaskKind.ENHANCEMENT,
}


class GitHubIngressService:
    """Bind a GH issue to a PG task + task room (unique source_ref)."""

    @inject
    def __init__(
        self,
        buzz: BuzzService,
        poster: HermesBuzzPoster,
        tenants: TenantRegistryService,
    ) -> None:
        self._buzz = buzz
        self._poster = poster
        self._tenants = tenants

    def kind_from_labels(self, labels: list[str]) -> Optional[TaskKind]:
        for raw in labels:
            key = (raw or "").strip().lower()
            if key in _LABEL_KIND:
                return _LABEL_KIND[key]
        return None

    async def bind_issue(
        self,
        *,
        tenant_slug: str,
        repo: str,
        issue_number: int,
        title: str,
        labels: list[str],
        issue_url: str = "",
        hired_role: str = "adh.pm",
    ) -> Optional[TaskRead]:
        """Create task+room when labels match; fail closed if role missing on hub."""
        tenant = self._tenants.by_slug(tenant_slug)
        if tenant is None:
            logger.warning("GH ingress: unknown tenant", tenant=tenant_slug)
            return None
        kind = self.kind_from_labels(labels)
        if kind is None:
            logger.info(
                "GH ingress: no bindable label",
                tenant=tenant_slug,
                issue=issue_number,
                labels=labels,
            )
            return None
        source_ref = f"github:{repo}#{int(issue_number)}"
        task_id = self._task_id_for(tenant, kind, issue_number)
        # Fail closed: hired role must already be a hub member (seeded) or we stall.
        members = await self._buzz.list_members(tenant.ops_room)
        handles = {m.identity_handle for m in members}
        if hired_role not in handles:
            await self._poster.post_status(
                tenant.ops_room,
                (
                    f"**Ingress stall** — `{hired_role}` is not on hub `#{tenant.ops_room}` "
                    f"for `{source_ref}` (`{title}`). Hire/seed the role before bind."
                ),
                EventType.STALL,
                {"status": "ingress_stall", "source_ref": source_ref, "role": hired_role},
            )
            return None
        task = await self._buzz.create_task(
            TaskCreate(
                tenant_slug=tenant.slug,
                kind=kind,
                task_id=task_id,
                title=(title or f"{kind.value} #{issue_number}")[:512],
                source=TaskSource.GITHUB,
                source_ref=source_ref,
                hub_room_slug=tenant.ops_room,
            )
        )
        for handle in ("adh.pm", "adh.pe", "adh.read", "adh.kb", "nikd10x"):
            try:
                await self._buzz.ensure_member(
                    RoomMemberCreate(room_slug=task.task_room_slug, identity_handle=handle)
                )
            except Exception:
                logger.exception("GH ingress member ensure failed", handle=handle)
        await self._buzz.append_task_event(
            TaskEventCreate(
                tenant_slug=tenant.slug,
                task_id=task.task_id,
                kind=TaskEventKind.INGRESS,
                role_id=hired_role,
                purpose="github_bind",
                token=source_ref,
                evidence_ref=issue_url or source_ref,
                payload={"repo": repo, "issue": issue_number, "labels": labels},
            )
        )
        await self._poster.post_status(
            tenant.ops_room,
            (
                f"Bound GitHub `{source_ref}` → task `{task.task_id}` "
                f"in `#{task.task_room_slug}` ({kind.value})."
            ),
            EventType.START,
            {
                "status": "task_bound",
                "task_id": task.task_id,
                "source_ref": source_ref,
                "kind": kind.value,
            },
        )
        try:
            await self._buzz.set_task_state(
                tenant.slug, task.task_id, TaskState.RUNNING, role_id=hired_role
            )
        except Exception:
            logger.exception("GH ingress task state → running failed", task_id=task.task_id)
        return task

    async def poll_realworld_once(
        self,
        *,
        issues: list[dict],
        default_repo: str = "realworld-api",
    ) -> int:
        """Minimal poll stub: bind each issue dict once (unique source_ref).

        Expected issue keys: number, title, labels (list[str]), html_url?, repo?
        """
        bound = 0
        for raw in issues:
            if not isinstance(raw, dict):
                continue
            number = int(raw.get("number") or 0)
            if number <= 0:
                continue
            labels = [str(x) for x in (raw.get("labels") or [])]
            repo = str(raw.get("repo") or default_repo)
            task = await self.bind_issue(
                tenant_slug="realworld",
                repo=repo,
                issue_number=number,
                title=str(raw.get("title") or f"Issue #{number}"),
                labels=labels,
                issue_url=str(raw.get("html_url") or ""),
            )
            if task is not None:
                bound += 1
        return bound

    def _task_id_for(self, tenant: TenantContext, kind: TaskKind, issue_number: int) -> str:
        prefix = tenant.slug.upper()
        if kind == TaskKind.BUG:
            return f"BUG-{prefix}-{int(issue_number):03d}"
        if kind == TaskKind.ENHANCEMENT:
            return f"ENH-{prefix}-{int(issue_number):03d}"
        return f"ISSUE-{prefix}-{int(issue_number):03d}"
