"""Load pinned Prayog workflow + skill index. No LLM. No ADH allowlists."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from injector import inject

from src.configs.hermes_settings import HermesSettings
from src.exceptions.app_exceptions import NotFoundError, ValidationError
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.hermes.catalogue_models import (
    CatalogueSnapshot,
    ForgePolicyDocument,
    HarnessPinDocument,
    SkillDescriptor,
    WorkflowDocument,
    WorkflowNodeDocument,
)

logger = get_logger()


class WorkflowCatalogueService(BaseInfraService):
    """Fail-fast catalogue for Hermes navigation and intent binding."""

    @inject
    def __init__(self) -> None:
        super().__init__()
        self._settings = HermesSettings.get_instance()
        self._snapshot: Optional[CatalogueSnapshot] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._snapshot = load_catalogue_snapshot(
            repo_root=_discover_repo_root(self._settings.repo_root),
            skills_root_override=self._settings.prayog_skills_root,
        )
        self._initialized = True
        logger.info(
            "Workflow catalogue loaded",
            workflow_id=self._snapshot.workflow.id,
            contract=self._snapshot.workflow.contract,
            node_count=len(self._snapshot.workflow.nodes),
            skill_count=len(self._snapshot.skills),
            skills_root=self._snapshot.skills_root,
            pin_ref=self._snapshot.pin.agent_skills_ref,
        )

    async def close(self) -> None:
        self._initialized = False
        self._snapshot = None

    async def health_check(self) -> bool:
        return self._initialized and self._snapshot is not None

    def snapshot(self) -> CatalogueSnapshot:
        if self._snapshot is None:
            raise ValidationError("workflow catalogue has not been initialized")
        return self._snapshot

    def reload(self) -> CatalogueSnapshot:
        """Synchronous reload (tests / ops). Replaces process snapshot."""
        self._snapshot = load_catalogue_snapshot(
            repo_root=_discover_repo_root(self._settings.repo_root),
            skills_root_override=self._settings.prayog_skills_root,
        )
        self._initialized = True
        return self._snapshot


def load_catalogue_snapshot(
    *,
    repo_root: Path,
    skills_root_override: str = "",
) -> CatalogueSnapshot:
    """Pure loader — used by the infra service and unit tests."""
    pin_path = repo_root / ".harness-pin.yaml"
    pin = _load_harness_pin(pin_path)

    skills_root = _resolve_skills_root(repo_root, skills_root_override)
    workflow_path = skills_root / "workflow.yaml"
    if not workflow_path.is_file():
        raise NotFoundError("workflow.yaml", str(workflow_path))

    raw = _read_yaml(workflow_path)
    if not isinstance(raw, dict):
        raise ValidationError("workflow.yaml root must be a mapping")
    workflow = _parse_workflow(raw)
    if not workflow.nodes:
        raise ValidationError("workflow.yaml has no nodes")
    skills = index_skills(skills_root / "skills")
    return CatalogueSnapshot(
        pin=pin,
        workflow=workflow,
        skills=skills,
        skills_root=str(skills_root),
        workflow_path=str(workflow_path),
    )


def index_skills(skills_dir: Path) -> dict[str, SkillDescriptor]:
    """Walk ``skills/**/SKILL.md`` and index by frontmatter ``name``."""
    if not skills_dir.is_dir():
        raise NotFoundError("skills directory", str(skills_dir))
    out: dict[str, SkillDescriptor] = {}
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        skill_id, description = _parse_skill_frontmatter(skill_md)
        if not skill_id:
            logger.warning("SKILL.md missing name frontmatter", path=str(skill_md))
            continue
        rel = skill_md.relative_to(skills_dir)
        category = rel.parts[0] if len(rel.parts) > 1 else ""
        out[skill_id] = SkillDescriptor(
            skill_id=skill_id,
            description=description,
            category=category,
            skill_md_path=str(skill_md),
        )
    return out


def _parse_workflow(raw: dict) -> WorkflowDocument:
    nodes_raw = raw.get("nodes") or {}
    if not isinstance(nodes_raw, dict):
        raise ValidationError("workflow.yaml nodes must be a mapping")
    nodes: dict[str, WorkflowNodeDocument] = {}
    for node_id, body in nodes_raw.items():
        if not isinstance(body, dict):
            raise ValidationError(f"node {node_id!r} must be a mapping")
        forge_raw = body.get("forge")
        forge = None
        if isinstance(forge_raw, dict):
            forge = ForgePolicyDocument.model_validate(forge_raw)
        elif forge_raw is not None:
            raise ValidationError(f"node {node_id!r} forge must be a mapping")
        outcomes_raw = body.get("outcomes") or {}
        if outcomes_raw and not isinstance(outcomes_raw, dict):
            raise ValidationError(f"node {node_id!r} outcomes must be a mapping")
        outcomes = {
            str(k): str(v) for k, v in outcomes_raw.items() if str(k).strip() and str(v).strip()
        }
        nodes[str(node_id)] = WorkflowNodeDocument(
            node_id=str(node_id),
            type=str(body.get("type") or "").strip(),
            profile=_opt_str(body.get("profile")),
            dispatch=_opt_str(body.get("dispatch")),
            purpose=_opt_str(body.get("purpose")),
            owner=_opt_str(body.get("owner")),
            provider=_opt_str(body.get("provider")),
            authorization=_opt_str(body.get("authorization")),
            forge=forge,
            outcomes=outcomes,
        )
        if not nodes[str(node_id)].type:
            raise ValidationError(f"node {node_id!r} missing type")

    entrypoints_raw = raw.get("entrypoints") or {}
    if entrypoints_raw and not isinstance(entrypoints_raw, dict):
        raise ValidationError("workflow.yaml entrypoints must be a mapping")
    entrypoints = {
        str(k): str(v) for k, v in entrypoints_raw.items() if str(k).strip() and str(v).strip()
    }
    return WorkflowDocument.model_validate(
        {
            "apiVersion": raw.get("apiVersion") or "",
            "kind": raw.get("kind") or "",
            "id": raw.get("id") or "",
            "contract": raw.get("contract") or "",
            "entrypoints": entrypoints,
            "nodes": nodes,
        }
    )


def _load_harness_pin(path: Path) -> HarnessPinDocument:
    if not path.is_file():
        raise NotFoundError("harness pin", str(path))
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise ValidationError(".harness-pin.yaml must be a mapping")
    skills = raw.get("agent_skills") or {}
    ref = ""
    if isinstance(skills, dict):
        ref = str(skills.get("ref") or "").strip()
    return HarnessPinDocument(
        profile=str(raw.get("profile") or "").strip(),
        delivery_contract=str(raw.get("delivery_contract") or "").strip(),
        agent_skills_ref=ref,
    )


def _parse_skill_frontmatter(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return "", ""
    end = text.find("\n---", 3)
    if end < 0:
        return "", ""
    block = text[3:end]
    data = yaml.safe_load(block)
    if not isinstance(data, dict):
        return "", ""
    skill_id = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    return skill_id, description


def _resolve_skills_root(repo_root: Path, override: str) -> Path:
    if (override or "").strip():
        path = Path(override).expanduser().resolve()
        if not path.is_dir():
            raise NotFoundError("prayog skills root", str(path))
        return path
    candidate = (repo_root / "prayog-skills").resolve()
    if not candidate.is_dir():
        raise NotFoundError("prayog skills root", str(candidate))
    return candidate


def _discover_repo_root(explicit: str = "") -> Path:
    """Resolve ADH checkout that owns ``.harness-pin.yaml``.

    Order: ``HERMES_REPO_ROOT`` / settings override → walk from cwd →
    ``$ORCH_WORKSPACE_ROOT/adh`` (Docker mount).
    """
    seeds: list[Path] = []
    if (explicit or "").strip():
        seeds.append(Path(explicit).expanduser().resolve())
    here = Path.cwd().resolve()
    seeds.extend((here, *here.parents))
    orch = (os.environ.get("ORCH_WORKSPACE_ROOT") or "").strip()
    if orch:
        seeds.append((Path(orch) / "adh").resolve())
    seen: set[Path] = set()
    for candidate in seeds:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / ".harness-pin.yaml").is_file():
            return candidate
    raise NotFoundError("repo root (.harness-pin.yaml)", str(here))


def _read_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _opt_str(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
