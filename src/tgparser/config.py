"""Configuration loader — .env secrets + config.yaml settings."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root (where pyproject.toml lives)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def _load_env(env_path: Path | None = None) -> None:
    """Load .env file, ignoring if not found."""
    path = env_path or DEFAULT_ENV_PATH
    if path.exists():
        load_dotenv(path)


def _load_yaml(config_path: Path | None = None) -> dict[str, Any]:
    """Load YAML config, returning empty dict if missing."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Load once at import time
_load_env()
_yaml_config = _load_yaml()


def get_secret(key: str, default: str | None = None) -> str | None:
    """Read a secret from environment (os.environ — loaded from .env)."""
    return os.environ.get(key, default)


def get_setting(*keys: str, default: Any = None) -> Any:
    """Traverse nested YAML config by key path.

    Example: get_setting("parsing", "scroll_delay_ms") -> 1500
    """
    node = _yaml_config
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return default
        if node is None:
            return default
    return node
