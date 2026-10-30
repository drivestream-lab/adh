"""Host entry: walk the pin, spawn one Cursor CLI, broadcast on Buzz."""

import argparse
import asyncio
import json
import os
import uuid

import dotenv

from src.business_services.orchestrator_service import OrchestratorService
from src.configs.app_settings import AppSettings
from src.infra_services.buzz_http_service import BuzzHttpService
from src.infra_services.cursor_cli_service import CursorCliService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.pin_walker_service import PinWalkerService
from src.logging import LoggingContext, get_logger, setup_logging
from src.models.orchestrator_models import MergeRequest

dotenv_path = os.path.join(os.getcwd(), ".env")
if os.path.exists(dotenv_path):
    dotenv.load_dotenv(dotenv_path=dotenv_path, override=True)


async def _spawn() -> int:
    walker = PinWalkerService()
    github = GitHubAppService()
    cursor = CursorCliService()
    buzz = BuzzHttpService()
    orch = OrchestratorService(walker, github, cursor, buzz)
    try:
        result = await orch.spawn_next()
        print(result.model_dump_json(indent=2))
        return 0 if result.exit_code == 0 and result.cannot_merge and not result.merged else 1
    finally:
        await orch.close()


async def _kill() -> int:
    walker = PinWalkerService()
    github = GitHubAppService()
    cursor = CursorCliService()
    buzz = BuzzHttpService()
    orch = OrchestratorService(walker, github, cursor, buzz)
    try:
        result = await orch.g0_kill()
        print(result.model_dump_json(indent=2))
        passed = (
            bool(result.pr_url)
            and result.cannot_push_web is True
            and result.cannot_merge is True
            and result.merged is False
            and result.verify_exit == 0
            and bool(result.checkpoint)
            and "checkpoint stop" in (result.checkpoint or "")
        )
        return 0 if passed else 1
    finally:
        await orch.close()


async def _merge() -> int:
    walker = PinWalkerService()
    github = GitHubAppService()
    cursor = CursorCliService()
    buzz = BuzzHttpService()
    orch = OrchestratorService(walker, github, cursor, buzz)
    try:
        await orch.merge_wave(MergeRequest())
    except Exception as exc:
        print(json.dumps({"merged": False, "error": str(exc)}))
        return 0
    finally:
        await orch.close()
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="ADH host orchestrator")
    parser.add_argument("command", choices=["spawn", "merge", "kill"], nargs="?", default="spawn")
    args = parser.parse_args()
    settings = AppSettings.get_instance()
    setup_logging(settings)
    logger = get_logger()
    correlation_id = str(uuid.uuid4())
    with LoggingContext(correlation_id):
        logger.info("Host orchestrator starting", command=args.command)
        if args.command == "merge":
            raise SystemExit(asyncio.run(_merge()))
        if args.command == "kill":
            raise SystemExit(asyncio.run(_kill()))
        raise SystemExit(asyncio.run(_spawn()))


if __name__ == "__main__":
    main()
