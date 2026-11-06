"""Catalogue load + resolve — strings from YAML, no ADH hop allowlists."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.adh_agents.catalogue.resolve import resolve_next
from src.adh_agents.understanding.understand_service import (
    HermesUnderstandService,
)
from src.exceptions.app_exceptions import ValidationError
from src.infra_services.workflow_catalogue_service import (
    index_skills,
    load_catalogue_snapshot,
)
from src.models.hermes.catalogue_models import CatalogueSnapshot, WorkflowDocument


_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "hermes" / "mini_workflow.yaml"
_REPO = Path(__file__).resolve().parents[2]


def _mini_snapshot(tmp_path: Path) -> CatalogueSnapshot:
    skills_root = tmp_path / "prayog-skills"
    skills_dir = skills_root / "skills" / "requirements" / "validate-requirements"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        "---\nname: validate-requirements\ndescription: test skill\n---\n\n# Test\n",
        encoding="utf-8",
    )
    impact = skills_root / "skills" / "requirements" / "prd-impact-map"
    impact.mkdir(parents=True)
    (impact / "SKILL.md").write_text(
        "---\nname: prd-impact-map\ndescription: impact\n---\n\n# Impact\n",
        encoding="utf-8",
    )
    (skills_root / "workflow.yaml").write_text(
        _FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )

    pin = tmp_path / ".harness-pin.yaml"
    pin.write_text(
        "\n".join(
            [
                "profile: python-backend",
                "delivery_contract: sdd-delivery/v2",
                "agent_skills:",
                "  ref: v0.0-test",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return load_catalogue_snapshot(repo_root=tmp_path, skills_root_override=str(skills_root))


def test_load_mini_catalogue(tmp_path: Path) -> None:
    snap = _mini_snapshot(tmp_path)
    assert snap.workflow.id == "hermes-test-mini"
    assert snap.entrypoint("meta-pm") == "validate-requirements"
    assert snap.node("validate-requirements").is_skill()
    assert snap.node("requirements-human-decision").is_human_checkpoint()
    assert snap.node("prd-pr-action").requires_explicit_authorization()
    forge = snap.node("prd-pr-action").forge
    assert forge is not None
    assert forge.action == "open_draft_pr"
    assert "validate-requirements" in snap.skills
    assert snap.skills["validate-requirements"].category == "requirements"


def test_resolve_next_from_outcomes(tmp_path: Path) -> None:
    snap = _mini_snapshot(tmp_path)
    nxt = resolve_next(snap, "validate-requirements", "pass")
    assert nxt.node_id == "prd-impact-map"
    gate = resolve_next(snap, "validate-requirements", "needs-input")
    assert gate.is_human_checkpoint()
    assert gate.purpose == "requirements-clarification"
    with pytest.raises(ValidationError):
        resolve_next(snap, "validate-requirements", "not-a-real-outcome")


def test_live_prayog_workflow_loads() -> None:
    """Integration against the repo submodule — skip if checkout missing."""
    skills = _REPO / "prayog-skills"
    if not (skills / "workflow.yaml").is_file():
        pytest.skip("prayog-skills/workflow.yaml not present")
    snap = load_catalogue_snapshot(repo_root=_REPO, skills_root_override=str(skills))
    assert snap.workflow.contract.startswith("sdd-delivery")
    assert "meta-pm" in snap.workflow.entrypoints
    start = snap.entrypoint("meta-pm")
    assert snap.node(start).is_skill()
    # Navigation is data-driven: every outcome target must exist
    for node in snap.workflow.nodes.values():
        for outcome, target in node.outcomes.items():
            assert target in snap.workflow.nodes, f"{node.node_id}.{outcome} -> {target}"
    assert len(snap.skills) > 0
    assert "validate-requirements" in snap.skills


def test_index_skills_reads_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "skills" / "forge" / "open-draft-pr"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: open-draft-pr\ndescription: Open a draft PR\n---\n",
        encoding="utf-8",
    )
    indexed = index_skills(tmp_path / "skills")
    assert indexed["open-draft-pr"].category == "forge"
    assert "draft PR" in indexed["open-draft-pr"].description


def test_understand_mentions_catalogue_node(tmp_path: Path) -> None:
    snap = _mini_snapshot(tmp_path)

    class _Cat:
        def snapshot(self) -> CatalogueSnapshot:
            return snap

    svc = HermesUnderstandService(catalogue=_Cat())  # type: ignore[arg-type]
    candidates = svc.candidates_for_node_mention(
        "run validate-requirements for INIT-RW-001",
        init_prefix="INIT-RW-",
    )
    assert candidates
    assert candidates[0].node_id == "validate-requirements"
    assert candidates[0].slots.get("initiative") == "INIT-RW-001"
    assert svc.clarify_for(candidates, init_prefix="INIT-RW-") is None

    dig = svc.candidates_for_node_mention("start validate-requirements", init_prefix="INIT-RW-")
    assert dig[0].missing_slots == ["initiative"]
    clarify = svc.clarify_for(dig, init_prefix="INIT-RW-")
    assert clarify is not None
    assert "INIT-RW-" in clarify.question


def test_workflow_document_roundtrip() -> None:
    raw = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    # Ensure fixture parses as mapping; full parse goes through loader
    assert raw.get("kind") == "SkillWorkflow"
    assert "nodes" in raw
    doc = WorkflowDocument.model_validate(
        {
            "apiVersion": raw["apiVersion"],
            "kind": raw["kind"],
            "id": raw["id"],
            "contract": raw["contract"],
            "entrypoints": raw["entrypoints"],
            "nodes": {},
        }
    )
    assert doc.id == "hermes-test-mini"
