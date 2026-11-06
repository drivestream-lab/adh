"""Host read worker — Team OS agent process."""

from __future__ import annotations

import asyncio
import os
import signal
import uuid

import dotenv

from src.adh_agents.agents.read_agent import ReadAgent
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
    agent = provide_service(ReadAgent)
    await agent.initialize()
    logger = get_logger()
    logger.info("ReadAgent host worker ready", role=agent.role_id)
    stop = asyncio.Event()
    shutting_down = False

    def _stop(*_args: object) -> None:
        nonlocal shutting_down
        if shutting_down:
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
    try:
        await asyncio.wait_for(close_all_services(), timeout=_SHUTDOWN_BUDGET_SECONDS)
    except asyncio.TimeoutError:
        pass


def main() -> None:
    settings = AppSettings.get_instance()
    setup_logging(settings)
    with LoggingContext(str(uuid.uuid4())):
        asyncio.run(_run())


if __name__ == "__main__":
    main()
