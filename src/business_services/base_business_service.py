"""Base business service class for Parichay."""

import abc

from src.logging import get_logger

logger = get_logger()


class BaseBusinessService(abc.ABC):
    """Abstract base class for all business services."""

    def __init__(self) -> None:
        self._initialized = False
        self.logger = get_logger()
        self.logger.info("Created business service", service=self.__class__.__name__)

    async def initialize(self) -> None:
        """Mark service ready after app startup. Override only for rare async setup (not resources)."""
        self.logger.info("Initializing business service", service=self.__class__.__name__)
        self._initialized = True
        self.logger.info(
            "Business service initialized successfully",
            service=self.__class__.__name__,
        )

    async def close(self) -> None:
        """Close the service."""
        self.logger.info("Closing business service", service=self.__class__.__name__)
        self._initialized = False

    async def health_check(self) -> bool:
        """Check if the service is healthy."""
        return self._initialized
