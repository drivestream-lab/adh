"""Gate‑1 product questions — capped, Impact-Map grounded, PR/Buzz projection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_CAP_ROW = re.compile(
    r"^\|\s*(CAP-\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*$",
    re.MULTILINE,
)
_CTR_ROW = re.compile(
    r"^\|\s*(CTR-\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*$",
    re.MULTILINE,
)
_REPO_ROW = re.compile(
    r"^\|\s*([a-z0-9-]+)\s*\|\s*(drivestream-lab/[a-z0-9-]+)\s*\|\s*[^|]+\|\s*([^|]+)\|\s*",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ProductQuestion:
    qid: str
    title: str
    prd_ref: str
    repos: list[str]
    delta: str
    scenario: str
    example: str
    recommendation: str
    why: str
    alternatives: list[str]
    evidence: str

    def to_markdown(self) -> str:
        alts = "\n".join(f"  - {a}" for a in self.alternatives) or "  - (none)"
        repos = ", ".join(self.repos) if self.repos else "(meta)"
        return "\n".join(
            [
                f"### {self.qid} — {self.title}",
                "",
                f"- **PRD ref:** {self.prd_ref}",
                f"- **Repos(s):** {repos}",
                f"- **Delta:** {self.delta}",
                f"- **Scenario:** {self.scenario}",
                f"- **Example:** {self.example}",
                f"- **Recommendation:** {self.recommendation}",
                f"- **Why:** {self.why}",
                "- **Alternatives:**",
                alts,
                f"- **Evidence:** {self.evidence}",
            ]
        )


def impact_map_path(meta_root: Path, initiative: str) -> Path:
    return meta_root / "prd" / "reports" / f"Impact-Map-{initiative}.md"


def build_product_questions(
    impact_map_text: str,
    *,
    initiative: str,
    max_questions: int = 10,
) -> list[ProductQuestion]:
    """Derive a capped Gate‑1 question set from Impact-Map tables (no Cursor)."""
    questions: list[ProductQuestion] = []
    repos = _REPO_ROW.findall(impact_map_text)
    for service, repo, scope in repos:
        if "meta" in repo:
            continue
        scope_s = " ".join(scope.split())
        questions.append(
            ProductQuestion(
                qid=f"PQ-{len(questions) + 1:02d}",
                title=f"Confirm scope for `{service}`",
                prd_ref=f"{initiative} / Impact-Map §2",
                repos=[repo.strip()],
                delta="partial",
                scenario=(
                    f"When we treat `{service}` as in-scope for this initiative, "
                    "members and guests should see only the behaviours listed in the map."
                ),
                example=scope_s[:240] or f"Ship {service} capabilities named in the PRD.",
                recommendation=f"Keep `{service}` in wave scope as mapped.",
                why="Wrong repo scope ships the wrong product surface or skips a required provider/consumer.",
                alternatives=[
                    f"A: Keep `{service}` in scope (recommended)",
                    f"B: Defer `{service}` with an explicit revisit condition",
                ],
                evidence=f"{repo.strip()} · Impact-Map §2 · EXTRACTED",
            )
        )
        if len(questions) >= max_questions:
            return questions[:max_questions]

    for ctr, provider, consumer, capability, _owner, status in _CTR_ROW.findall(impact_map_text):
        status_s = status.strip().lower()
        if status_s not in {"new", "changed", "unknown", "conflict"}:
            continue
        questions.append(
            ProductQuestion(
                qid=f"PQ-{len(questions) + 1:02d}",
                title=f"Contract {ctr.strip()} product stance",
                prd_ref=f"{initiative} / {capability.strip()}",
                repos=[provider.strip(), consumer.strip()],
                delta=status_s,
                scenario=(
                    f"When the web client depends on `{ctr.strip()}` from the API, "
                    "users should observe the capability behaviour without silent drift."
                ),
                example=f"PRD acceptance names {ctr.strip()} for {capability.strip()}.",
                recommendation=f"Treat `{ctr.strip()}` as **{status_s}** for this initiative.",
                why="Contract mismatch causes false 'already built' or broken guest/member journeys.",
                alternatives=[
                    f"A: Accept `{ctr.strip()}` as {status_s} (recommended)",
                    f"B: Mark `{ctr.strip()}` deferred / out of wave",
                ],
                evidence=(f"{provider.strip()}→{consumer.strip()} · Impact-Map §6 · EXTRACTED"),
            )
        )
        if len(questions) >= max_questions:
            break

    if not questions:
        questions.append(
            ProductQuestion(
                qid="PQ-01",
                title="Confirm Gate‑1 readiness of meta PRD draft",
                prd_ref=f"{initiative} / PRD",
                repos=[],
                delta="unknown",
                scenario="When PE attests this meta draft, product scope must be explicit enough for mutate waves.",
                example="Lead confirms CAP/CTR tables match intended RealWorld commons behaviour.",
                recommendation="Proceed to attest after PM confirms no open product blockers.",
                why="Attesting an underspecified PRD locks the wrong delivery bar.",
                alternatives=[
                    "A: Attest after PM ack (recommended)",
                    "B: Hold — PM revises PRD first",
                ],
                evidence="Impact-Map missing/unparsed · INFERRED",
            )
        )
    return questions[:max_questions]


def format_questions_document(
    *,
    initiative: str,
    pr_url: str,
    round_number: int,
    max_rounds: int,
    questions: list[ProductQuestion],
) -> str:
    body = "\n\n".join(q.to_markdown() for q in questions)
    return "\n".join(
        [
            f"# Gate‑1 product questions — {initiative}",
            "",
            f"> Posted by **adh.pe** (Team OS Gate‑1). Round **{round_number}/{max_rounds}**. "
            f"Cap **{len(questions)}** questions. PM: confirm / adjust / reject on this thread "
            "or on Buzz, then update the PRD. PE does not decide product answers.",
            "",
            f"- **Meta PR:** {pr_url or '(unknown)'}",
            f"- **Round:** {round_number} / {max_rounds}",
            "",
            "## Questions",
            "",
            body,
            "",
            "---",
            "",
            "**PM:** reply per question (confirm / adjust / reject).  ",
            "**Lead / PE:** on Buzz reply `attest` when satisfied, `new_round` for another "
            f"capped pass (max {max_rounds}), or `hold`.",
            "",
        ]
    )
