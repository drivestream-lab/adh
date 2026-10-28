"""Repository module for dependency injection."""

from injector import Module


class RepositoryModule(Module):
    """Bind repositories here as product features add schema tables."""

    def configure(self, binder) -> None:
        pass
