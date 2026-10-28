"""Configuration module for dependency injection.

Settings classes (AppSettings, JWTSettings, etc.) are configuration bags — they are
NOT part of the injector graph (dependency-injection.mdc v0.5.3). Services access them
via FooSettings.get_instance() directly in their __init__ body.

This module is intentionally empty. It remains as a registration point for any
future non-settings bindings (e.g. typed qualifiers, feature flags backed by DI).
"""

from injector import Binder, Module


class ConfigModule(Module):
    """Placeholder module — settings are not bound in DI."""

    def configure(self, binder: Binder) -> None:
        pass
