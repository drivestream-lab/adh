"""IAC DB analysis — connect with discovered creds (real lab only)."""

from __future__ import annotations

from dataclasses import dataclass, field

import asyncpg


@dataclass
class AnalyzeResult:
    ok: bool
    summary: str
    details: list[str] = field(default_factory=list)


async def analyze_database(
    database_url: str,
    *,
    expect_db: str = "realworld",
) -> AnalyzeResult:
    """Connect and run lightweight SoT probes. Fail closed on connect error."""
    details: list[str] = []
    try:
        conn = await asyncpg.connect(database_url, timeout=15)
    except Exception as exc:
        return AnalyzeResult(
            ok=False,
            summary=f"DB connect failed: {exc}",
            details=[f"url_host=127.0.0.1 expect_db={expect_db}"],
        )
    try:
        db = await conn.fetchval("SELECT current_database()")
        details.append(f"current_database={db}")
        if expect_db and str(db) != expect_db:
            return AnalyzeResult(
                ok=False,
                summary=f"unexpected database {db!r} (want {expect_db!r})",
                details=details,
            )
        tables = await conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            LIMIT 40
            """
        )
        names = [str(r["table_name"]) for r in tables]
        details.append(f"public_tables={','.join(names) or '(none)'}")
        if not names:
            return AnalyzeResult(
                ok=False,
                summary="no public tables — tip/migrations may be missing",
                details=details,
            )
        return AnalyzeResult(
            ok=True,
            summary=f"DB `{db}` reachable with {len(names)} public table(s)",
            details=details,
        )
    except Exception as exc:
        return AnalyzeResult(ok=False, summary=f"DB probe failed: {exc}", details=details)
    finally:
        await conn.close()
