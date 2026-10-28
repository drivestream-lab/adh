"""Main entry point for Adh."""

import os
import uuid
import dotenv
import uvicorn
from src.app import create_app
from src.logging import get_logger, setup_logging, LoggingContext
from src.configs.app_settings import AppSettings

startup_correlation_id = str(uuid.uuid4())
dotenv_path = os.path.join(os.getcwd(), ".env")
if os.path.exists(dotenv_path):
    dotenv.load_dotenv(dotenv_path=dotenv_path, override=True)

settings = AppSettings.get_instance()
setup_logging(settings)
logger = get_logger()


def get_application():
    with LoggingContext(startup_correlation_id):
        return create_app()


if __name__ == "__main__":
    logger.info("Starting adh application", host=settings.host, port=settings.port)
    uvicorn.run(
        "src.main:get_application",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower(),
        factory=True,
    )
