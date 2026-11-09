"""Gate‑1 product questions — capped, Impact-Map grounded (no regex artefact parse)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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


def _pipe_rows(text: str) -> list[list[str]]:
    """Split markdown table lines on `|` — no regex."""
    rows: list[list[str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        inner = line.strip("|")
        cells = [c.strip() for c in inner.split("|")]
        if not cells:
            continue
        # Skip separator rows (---).
        if all(not c or set(c) <= {"-", ":", " "} for c in cells):
            continue
        rows.append(cells)
    return rows


def _header_index(header: list[str], *names: str) -> int | None:
    lowered = [h.lower() for h in header]
    for name in names:
        key = name.lower()
        for i, cell in enumerate(lowered):
            if key in cell:
                return i
    return None


def build_product_questions(
    impact_map_text: str,
    *,
    initiative: str,
    max_questions: int = 10,
) -> list[ProductQuestion]:
    """Derive a capped Gate‑1 question set from Impact-Map tables (deterministic)."""
    questions: list[ProductQuestion] = []
    rows = _pipe_rows(impact_map_text)
    if not rows:
        return [_fallback_question(initiative)]

    # Walk tables: when we see a header with Service/Repo, treat following rows as repos.
    i = 0
    while i < len(rows) and len(questions) < max_questions:
        header = rows[i]
        svc_i = _header_index(header, "service")
        repo_i = _header_index(header, "repo")
        scope_i = _header_index(header, "scope summary", "scope")
        ctr_i = _header_index(header, "contract id", "contract")
        provider_i = _header_index(header, "provider")
        consumer_i = _header_index(header, "consumer")
        cap_i = _header_index(header, "capability")
        status_i = _header_index(header, "status")
        i += 1
        if svc_i is not None and repo_i is not None:
            while i < len(rows) and len(questions) < max_questions:
                row = rows[i]
                # Next header?
                if _header_index(row, "contract id", "contract", "service") is not None and (
                    _header_index(row, "provider") is not None
                    or _header_index(row, "repo") is not None
                ):
                    break
                i += 1
                if len(row) <= max(svc_i, repo_i):
                    continue
                service = row[svc_i]
                repo = row[repo_i]
                if "meta" in repo.lower():
                    continue
                scope = row[scope_i] if scope_i is not None and scope_i < len(row) else ""
                scope_s = " ".join(scope.split())
                questions.append(
                    ProductQuestion(
                        qid=f"PQ-{len(questions) + 1:02d}",
                        title=f"Confirm scope for `{service}`",
                        prd_ref=f"{initiative} / Impact-Map §2",
                        repos=[repo],
                        delta="partial",
                        scenario=(
                            f"When we treat `{service}` as in-scope for this initiative, "
                            "members and guests should see only the behaviours listed in the map."
                        ),
                        example=scope_s[:240] or f"Ship {service} capabilities named in the PRD.",
                        recommendation=f"Keep `{service}` in wave scope as mapped.",
                        why=(
                            "Wrong repo scope ships the wrong product surface "
                            "or skips a required provider/consumer."
                        ),
                        alternatives=[
                            f"A: Keep `{service}` in scope (recommended)",
                            f"B: Defer `{service}` with an explicit revisit condition",
                        ],
                        evidence=f"{repo} · Impact-Map §2 · EXTRACTED",
                    )
                )
            continue
        if (
            ctr_i is not None
            and provider_i is not None
            and consumer_i is not None
            and status_i is not None
        ):
            while i < len(rows) and len(questions) < max_questions:
                row = rows[i]
                if _header_index(row, "service", "contract") is not None and (
                    _header_index(row, "repo") is not None
                    or _header_index(row, "provider") is not None
                ):
                    break
                i += 1
                need = max(ctr_i, provider_i, consumer_i, status_i)
                if len(row) <= need:
                    continue
                status_s = row[status_i].strip().lower()
                if status_s not in {"new", "changed", "unknown", "conflict"}:
                    continue
                ctr = row[ctr_i]
                provider = row[provider_i]
                consumer = row[consumer_i]
                capability = row[cap_i] if cap_i is not None and cap_i < len(row) else "capability"
                questions.append(
                    ProductQuestion(
                        qid=f"PQ-{len(questions) + 1:02d}",
                        title=f"Contract {ctr} product stance",
                        prd_ref=f"{initiative} / {capability}",
                        repos=[provider, consumer],
                        delta=status_s,
                        scenario=(
                            f"When the web client depends on `{ctr}` from the API, "
                            "users should observe the capability behaviour without silent drift."
                        ),
                        example=f"PRD acceptance names {ctr} for {capability}.",
                        recommendation=f"Treat `{ctr}` as **{status_s}** for this initiative.",
                        why=(
                            "Contract mismatch causes false 'already built' "
                            "or broken guest/member journeys."
                        ),
                        alternatives=[
                            f"A: Accept `{ctr}` as {status_s} (recommended)",
                            f"B: Mark `{ctr}` deferred / out of wave",
                        ],
                        evidence=f"{provider}→{consumer} · Impact-Map · EXTRACTED",
                    )
                )
            continue

    if not questions:
        return [_fallback_question(initiative)]
    return questions[:max_questions]


def _fallback_question(initiative: str) -> ProductQuestion:
    return ProductQuestion(
        qid="PQ-01",
        title="Confirm Gate‑1 readiness of meta PRD draft",
        prd_ref=f"{initiative} / PRD",
        repos=[],
        delta="unknown",
        scenario=(
            "When PE attests this meta draft, product scope must be explicit "
            "enough for mutate waves."
        ),
        example="Lead confirms CAP/CTR tables match intended commons behaviour.",
        recommendation="Proceed to attest after PM confirms no open product blockers.",
        why="Attesting an underspecified PRD locks the wrong delivery bar.",
        alternatives=[
            "A: Attest after PM ack (recommended)",
            "B: Hold — PM revises PRD first",
        ],
        evidence="Impact-Map missing/unparsed · INFERRED",
    )


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
