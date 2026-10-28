"""Configuration loading utilities for Parichay."""

import os
from typing import Optional

import dotenv

from src.configs.app_settings import AppSettings


def load_dotenv(dotenv_path: Optional[str] = None, override: bool = True) -> bool:
    """Load environment variables from .env file."""
    if dotenv_path is None:
        dotenv_path = os.path.join(os.getcwd(), ".env")
    return dotenv.load_dotenv(dotenv_path=dotenv_path, override=override)


def get_settings(env_file: Optional[str] = None) -> AppSettings:
    """Get application settings."""
    if env_file:
        load_dotenv(dotenv_path=env_file)
    return AppSettings.get_instance()
