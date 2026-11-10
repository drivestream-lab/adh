"""Build open briefs for Lead judgment and authorization. Tokens come from the brief itself."""

from __future__ import annotations

from typing import Any, Optional

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.exceptions.app_exceptions import ValidationError
from src.models.hermes.catalogue_models import WorkflowNodeDocument
from src.models.hermes.intent_models import JudgmentRequest

_MEANS_SEP = " — "


class HermesBriefService(BaseBusinessService):
    """Construct and render JudgmentRequest cards."""

    @inject
    def __init__(self) -> None:
        super().__init__()

    def build_brief(
        self,
        *,
        purpose: str,
        node_id: str,
        question: str,
        example: str = "",
        options: Optional[list[str]] = None,
        recommend: str = "",
        recommend_why: str = "",
        bluf: str = "",
        card_kind: str = "",
        locking: Optional[list[str]] = None,
        not_locking: Optional[list[str]] = None,
        revise_if: Optional[list[str]] = None,
        reply_tokens: Optional[list[str]] = None,
        artefact_path: Optional[str] = None,
    ) -> JudgmentRequest:
        bluf_text = (bluf or recommend_why or "").strip()
        return JudgmentRequest(
            purpose=purpose,
            node_id=node_id,
            question=question,
            example=example,
            options=list(options or []),
            recommend=recommend,
            recommend_why=bluf_text,
            bluf=bluf_text,
            card_kind=card_kind,
            locking=list(locking or []),
            not_locking=list(not_locking or []),
            revise_if=list(revise_if or []),
            reply_tokens=list(reply_tokens or []),
            artefact_path=artefact_path,
        )

    def brief_from_validate_finding(
        self,
        finding: dict[str, Any],
        *,
        node_id: str,
        purpose: str = "",
    ) -> JudgmentRequest:
        """One VF finding → brief. Reply tokens are ``<id>: <choice>`` from the finding's options."""
        fid = str(finding.get("id") or "").strip()
        if not fid:
            raise ValidationError("validate finding is missing an id")
        raw_options = finding.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise ValidationError(f"validate finding {fid} has no options")
        choices: list[str] = []
        options: list[str] = []
        for opt in raw_options:
            if not isinstance(opt, dict):
                raise ValidationError(f"validate finding {fid} has a malformed option")
            choice = str(opt.get("choice") or "").strip().lower()
            if not choice:
                raise ValidationError(f"validate finding {fid} has an option without a choice")
            means = str(opt.get("means") or "").strip()
            choices.append(choice)
            options.append(f"{choice}{_MEANS_SEP}{means}" if means else choice)
        recommend = str(finding.get("recommend") or "").strip().lower()
        severity = str(finding.get("severity") or "").strip()
        question = str(finding.get("question") or finding.get("finding") or fid).strip()
        if severity:
            question = f"{fid} ({severity}): {question}"
        else:
            question = f"{fid}: {question}"
        return self.build_brief(
            purpose=purpose,
            node_id=node_id,
            question=question,
            example=str(finding.get("example") or "").strip(),
            options=options,
            recommend=recommend,
            recommend_why=str(finding.get("recommend_why") or "").strip(),
            reply_tokens=[f"{fid}: {choice}" for choice in choices],
            artefact_path=str(finding["artefact_path"]) if finding.get("artefact_path") else None,
        )

    def brief_authorization(
        self,
        node: WorkflowNodeDocument,
        initiative: Optional[str],
    ) -> JudgmentRequest:
        """Ask the Lead to authorize the forge action declared on ``node``."""
        action = (node.forge.action if node.forge is not None else None) or ""
        if not action.strip():
            raise ValidationError(f"node {node.node_id!r} declares no forge action")
        target = f" for {initiative}" if initiative else ""
        return self.build_brief(
            purpose=node.purpose or node.node_id,
            node_id=node.node_id,
            question=f"Authorize `{action}`{target}? Nothing runs until you say so.",
            example=f"Hermes will run the forge action `{action}` as the product App. It never merges.",
            options=[f"authorize{_MEANS_SEP}run {action} now"],
            # Lead-facing token must equal recommend so god can auto-play Hermes judgment.
            recommend="go ahead",
            bluf="Nothing is pushed until you authorize this action.",
            reply_tokens=["go ahead", f"authorize {action}"],
        )

    def format_brief_markdown(self, brief: JudgmentRequest) -> str:
        """Product-focused decision card for a human PM."""
        label = brief.purpose or brief.node_id
        lines: list[str] = [f"### {label}", "", brief.question, ""]
        bluf = (brief.bluf or brief.recommend_why or "").strip()
        if brief.recommend:
            bluf_suffix = f" — {bluf}" if bluf else ""
            lines += [f"**Recommendation.** `{brief.recommend}`{bluf_suffix}", ""]
        elif bluf:
            lines += [f"**Recommendation.** {bluf}", ""]
        kind = (brief.card_kind or "").strip().lower()
        if kind == "postpm":
            primary, secondary, tertiary = (
                "**What changed.**",
                "**Deferred.**",
                "**Still risky.**",
            )
        else:
            primary, secondary, tertiary = (
                "**Buying.**",
                "**Not buying.**",
                "**Choose another if.**",
            )
        if brief.locking:
            lines += [primary]
            lines += [f"- {b}" for b in brief.locking]
            lines.append("")
        if brief.not_locking:
            lines += [secondary]
            lines += [f"- {b}" for b in brief.not_locking]
            lines.append("")
        if brief.revise_if:
            lines += [tertiary]
            lines += [f"- {b}" for b in brief.revise_if]
            lines.append("")
        if brief.example:
            lines += [f"**In real life.** {brief.example}", ""]
        if brief.options:
            lines += ["| If you choose | What happens |", "|---------------|--------------|"]
            for raw in brief.options:
                choice, _sep, means = raw.partition(_MEANS_SEP)
                mark = " ←" if choice == brief.recommend else ""
                lines.append(f"| `{choice}`{mark} | {means} |")
            lines.append("")
        if brief.artefact_path:
            lines += [f"Artefact: `{brief.artefact_path}`", ""]
        if brief.reply_tokens:
            tokens = " / ".join(f"`{t}`" for t in brief.reply_tokens)
            lines.append(f"Reply with {tokens}, or `stop` to cancel.")
        return "\n".join(lines).rstrip()
