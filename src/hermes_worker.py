"""Host Hermes worker: listen on Buzz (shared Redis/Postgres), run skills via local Cursor agent.

Buzz API/UI stay in Docker. This process owns outline listening + catalogue skill dispatch
so the Darwin ``agent`` CLI and keychain auth work on the Mac host.
"""

from __future__ import annotations

import asyncio
import os
import signal
import uuid

import dotenv

from src.business_services.hermes_service import HermesService
from src.configs.app_settings import AppSettings
from src.di.dependency_container import (
    close_all_services,
    configure_container,
    initialize_all_services,
    provide_service,
)
from src.logging import LoggingContext, get_logger, setup_logging

dotenv_path = os.path.join(os.getcwd(), ".env")
if os.path.exists(dotenv_path):
    dotenv.load_dotenv(dotenv_path=dotenv_path, override=True)


_SHUTDOWN_BUDGET_SECONDS = 8.0


async def _run() -> None:
    configure_container()
    await initialize_all_services()
    hermes = provide_service(HermesService)
    logger = get_logger()
    logger.info(
        "Hermes host worker ready",
        listen_ops=hermes._settings.listen_ops,
        skill_runner=hermes._settings.pm_skill_runner_enabled,
    )
    stop = asyncio.Event()
    shutting_down = False

    def _stop(*_args: object) -> None:
        nonlocal shutting_down
        if shutting_down:
            logger.warning("Second interrupt during shutdown — forcing exit")
            os._exit(1)
        shutting_down = True
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _stop())

    await stop.wait()
    logger.info("Hermes host worker shutting down")
    try:
        await asyncio.wait_for(close_all_services(), timeout=_SHUTDOWN_BUDGET_SECONDS)
    except asyncio.TimeoutError:
        logger.error(
            "Service shutdown exceeded budget; exiting",
            budget_seconds=_SHUTDOWN_BUDGET_SECONDS,
        )


def main() -> None:
    settings = AppSettings.get_instance()
    setup_logging(settings)
    logger = get_logger()
    correlation_id = str(uuid.uuid4())
    with LoggingContext(correlation_id):
        logger.info("Starting Hermes host worker")
        asyncio.run(_run())


if __name__ == "__main__":
    main()
