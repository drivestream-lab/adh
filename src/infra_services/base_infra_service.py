"""Base infrastructure service class for Parichay."""

import abc

from src.logging import get_logger

logger = get_logger()


class BaseInfraService(abc.ABC):
    """Abstract base class for all infrastructure services."""

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initialize the service."""
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the service and release resources."""
        pass

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Check if the service is healthy."""
        pass
