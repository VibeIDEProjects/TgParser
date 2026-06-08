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

# Default user-level data directory (independent of CWD).
# Linux/macOS:  ~/.tgparser/
# Windows:      %USERPROFILE%/.tgparser/
USER_DATA_DIR = Path.home() / ".tgparser"
DEFAULT_SESSION_DIR = USER_DATA_DIR / "sessions"
DEFAULT_OUTPUT_DIR = USER_DATA_DIR / "output"

# Mapping of well-known settings → their absolute default paths.  These are
# applied when the user does not override the value in config.yaml.
_BUILTIN_DEFAULTS: dict[tuple[str, ...], Any] = {
    ("session_dir",): str(DEFAULT_SESSION_DIR),
    ("output_dir",): str(DEFAULT_OUTPUT_DIR),
}


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

    For well-known path-like settings (session_dir, output_dir) we fall back
    to absolute user-level defaults under ``~/.tgparser/`` if neither the
    YAML config nor the caller's ``default`` provides a value.  This makes
    storage paths stable across different working directories.
    """
    node = _yaml_config
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            node = None
        if node is None:
            break
    if node is None:
        # Fall back to a built-in default, or the caller-supplied default.
        return _BUILTIN_DEFAULTS.get(keys, default)
    return node


def resolve_path(*keys: str, default: Path | None = None) -> Path:
    """Read a path-like setting and return a fully resolved absolute Path.

    - ``~`` is expanded.
    - Relative paths are resolved against ``USER_DATA_DIR`` (so the parser
      doesn't dump files into whatever directory the user happens to be in).
    - The parent directory is created if missing.

    Example::

        resolve_path("output_dir")  # -> /home/user/.tgparser/output

    Backwards compatibility: if the YAML config uses the legacy
    ``data/output`` / ``data/sessions`` paths (relative to the project
    root), the path is anchored at :data:`PROJECT_ROOT` so old configs
    keep working.
    """
    raw = get_setting(*keys, default=default)
    p = Path(str(raw)).expanduser()
    if not p.is_absolute():
        # Detect legacy project-local "data/..." paths and anchor them
        # to PROJECT_ROOT; otherwise anchor under USER_DATA_DIR.
        if p.parts and p.parts[0] == "data":
            p = PROJECT_ROOT / p
        else:
            p = USER_DATA_DIR / p
    p.mkdir(parents=True, exist_ok=True)
    return p
