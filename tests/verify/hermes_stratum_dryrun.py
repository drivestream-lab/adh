"""Opt-in Stratum Hermes behaviour dry-run (L3).

Default: render-only (no model). Pass ``--live`` to complete JSON packs via
configured Hermes models and write briefs under ``/tmp/adh-hermes-stratum-dryrun``.

No Buzz, no forge, no tenants.yaml. Does not modify ``src/``.

Usage::

    .venv/bin/python -m tests.verify.hermes_stratum_dryrun
    .venv/bin/python -m tests.verify.hermes_stratum_dryrun --live
    .venv/bin/python -m tests.verify.hermes_stratum_dryrun --live --scenarios edge-008,core-002
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from src.infra_services.prompt_service import PromptService
from tests._helpers.hermes_stratum import load_index, pack_variables

OUT_ROOT = Path("/tmp/adh-hermes-stratum-dryrun")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stratum Hermes harness dry-run")
    p.add_argument(
        "--live",
        action="store_true",
        help="Call LiteLLM for JSON template hops (copy hops stay render-only)",
    )
    p.add_argument(
        "--scenarios",
        default="",
        help="Comma-separated scenario ids (default: all)",
    )
    p.add_argument(
        "--out",
        default=str(OUT_ROOT),
        help="Output directory for rendered/completed briefs",
    )
    return p.parse_args(argv)


def _build_prompts(*, live: bool) -> PromptService:
    if not live:
        return PromptService(MagicMock())
    from src.infra_services.litellm_service import LiteLLMService

    return PromptService(LiteLLMService())


async def _run(args: argparse.Namespace) -> int:
    index = load_index()
    wanted = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    scenarios = wanted or list(index["scenarios"])
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    prompts = _build_prompts(live=args.live)
    await prompts.initialize()
    if args.live:
        litellm = prompts._litellm  # noqa: SLF001 — dry-run needs gateway init
        if hasattr(litellm, "initialize"):
            await litellm.initialize()

    failures: list[str] = []
    for sid in scenarios:
        if sid not in index["scenarios"]:
            failures.append(f"unknown scenario: {sid}")
            continue
        sc_dir = out_root / sid
        sc_dir.mkdir(parents=True, exist_ok=True)
        initiative = index["scenarios"][sid]["initiative"]
        print(f"== {sid} ({initiative})")
        for hop in index["hops"]:
            hop_id = hop["id"]
            pack = hop["pack"]
            vars_ = pack_variables(sid, hop_id)
            try:
                if hop["kind"] == "copy":
                    body = prompts.render_copy(pack, vars_)
                    path = sc_dir / f"{hop_id}.md"
                    path.write_text(body, encoding="utf-8")
                    print(f"  render {hop_id} → {path}")
                    continue

                rendered = prompts.render(pack, vars_)
                render_path = sc_dir / f"{hop_id}.render.md"
                render_path.write_text(
                    f"# {pack}\n\n## system\n{rendered.system}\n\n## user\n{rendered.user}\n",
                    encoding="utf-8",
                )

                if not args.live or not hop.get("live", True):
                    print(f"  render {hop_id} → {render_path}")
                    continue

                result = await prompts.complete(pack, vars_)
                data: dict[str, Any] = dict(result.parsed or {})
                if "recommend" in data and not str(data.get("recommend") or "").strip():
                    raise RuntimeError(f"{hop_id}: empty recommend")
                if "outcome" in data and not str(data.get("outcome") or "").strip():
                    raise RuntimeError(f"{hop_id}: empty outcome")

                out_path = sc_dir / f"{hop_id}.json"
                out_path.write_text(
                    json.dumps(
                        {
                            "template_id": result.template_id,
                            "model": result.model,
                            "parsed": data,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f"  live   {hop_id} → {out_path}")
            except Exception as exc:  # noqa: BLE001 — dry-run aggregates failures
                failures.append(f"{sid}/{hop_id}: {exc}")
                print(f"  FAIL   {hop_id}: {exc}", file=sys.stderr)

    await prompts.close()
    if failures:
        print("\nFailures:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"\nOK — wrote {out_root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
