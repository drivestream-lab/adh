"""Fixed delivery-voice lexicon for Buzz human bodies (machine ids stay in payloads/logs)."""

from __future__ import annotations

from typing import Mapping

# Hop / purpose → human phrase on Buzz. Keys are programme/stage purpose ids.
_HOP_PHRASES: Mapping[str, str] = {
    "product_writeup": "product write-up",
    "product_brief": "product brief",
    "product_questions": "product questions",
    "product_pr": "product PR",
    "product_merge": "product merge into develop",
    "knowledge_docs_pr": "knowledge docs PR",
    "knowledge_docs_merge": "knowledge docs merge into develop",
    "spec_pr": "spec PR",
    "implementation_pr": "implementation PR",
    "authoring-promote": "product write-up promote",
    "prd-pr-action": "product draft PR",
    "prd-merge": "product merge into develop",
    "pm-pe-answers": "product questions from PE",
    "kb-enrich": "knowledge docs PR",
    "kb-enrich-land": "knowledge docs merge into develop",
    "gate1": "product brief",
    "postpm": "post-PM product brief",
    "product_answers": "product clarification answers",
    "clarifications_settled": "clarifications settled",
    "pe.pm_answers": "product clarification answers",
}

# Substrings forbidden on Buzz human bodies (case-insensitive).
# Artefact paths inside `backticks` are stripped before the check so filenames
# like hermes-gate1-brief.md do not false-positive.
_FORBIDDEN_BUZZ_SUBSTRINGS: tuple[str, ...] = (
    "gate-1",
    "gate‑1",
    "pe.review",
    "kb.enrich",
    "merge on forge",
    "review/merge on forge",
    "prd_merge",
    "open_draft_pr",
)


def delivery_phrase(hop: str) -> str:
    """Map an internal hop/purpose to delivery language."""
    key = (hop or "").strip()
    if not key:
        return "work"
    return _HOP_PHRASES.get(
        key, _HOP_PHRASES.get(key.lower(), key.replace("_", " ").replace("-", " "))
    )


def forbidden_buzz_hits(body: str) -> list[str]:
    """Return forbidden substrings found in a Buzz body (for tests / guards)."""
    import re

    # Drop backtick spans (evidence paths / tokens) before jargon scan.
    scrubbed = re.sub(r"`[^`]*`", " ", body or "")
    lowered = scrubbed.lower().replace("‑", "-").replace("–", "-")
    hits: list[str] = []
    for needle in _FORBIDDEN_BUZZ_SUBSTRINGS:
        n = needle.lower().replace("‑", "-")
        if n in lowered:
            hits.append(needle)
    # Standalone "Gate1" / "gate1" as a word (not inside a path we already stripped).
    if re.search(r"\bgate\s*1\b", lowered) or re.search(r"\bgate1\b", lowered):
        hits.append("gate1")
    return hits
