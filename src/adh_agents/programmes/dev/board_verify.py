"""Fail-closed proof that create-board-tickets actually seeded GitHub issues."""

from __future__ import annotations

import re
from dataclasses import dataclass

# github.com/<owner>/<repo>/issues/<n> (optional www. / trailing slash / query)
_ISSUE_URL = re.compile(
    r"https?://(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)/"
    r"issues/(?P<number>\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BoardSeedProof:
    ok: bool
    issue_urls: tuple[str, ...] = ()
    reason: str = ""


def extract_github_issue_urls(text: str) -> tuple[str, ...]:
    """Dedupe issue URLs from skill stdout / seed summary (order preserved)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _ISSUE_URL.finditer(text or ""):
        url = (
            f"https://github.com/{match.group('owner')}/"
            f"{match.group('repo')}/issues/{match.group('number')}"
        )
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
    return tuple(out)


def verify_board_seed_output(
    text: str,
    *,
    initiative: str = "",
    min_issues: int = 1,
) -> BoardSeedProof:
    """Require real issue URLs before programme may mark ``board_seeded``.

    Cursor exit 0 alone is not proof — skills can claim seeded while
    ``has_issues=false`` left the org project empty.
    """
    urls = extract_github_issue_urls(text)
    if len(urls) < min_issues:
        init = (initiative or "").strip() or "INIT"
        return BoardSeedProof(
            ok=False,
            issue_urls=urls,
            reason=(
                f"Board seed proof failed for **{init}** — need ≥{min_issues} "
                f"GitHub issue URL(s) from forge `create_board_tickets` "
                f"(found {len(urls)}). Likely ``has_issues=false``, missing "
                "issues:write on the App, or project attach failed. Fix, then "
                "reply `reseed board` (or `revise engg` for full reopen)."
            ),
        )
    return BoardSeedProof(ok=True, issue_urls=urls, reason="")
