"""Business services DI module for adh."""

from injector import Module, Binder


class BusinessServicesModule(Module):
    def configure(self, binder: Binder) -> None:
        # Add business service bindings as waves deliver them
        pass
