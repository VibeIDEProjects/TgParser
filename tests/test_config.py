"""Tests for config.resolve_path and get_setting defaults."""
from __future__ import annotations

from pathlib import Path

import pytest

from tgparser import config as cfg
from tgparser.config import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SESSION_DIR,
    USER_DATA_DIR,
    get_setting,
    resolve_path,
)


@pytest.fixture(autouse=True)
def _empty_yaml_config(monkeypatch):
    """Make every test run as if no YAML config file was present."""
    monkeypatch.setattr(cfg, "_yaml_config", {})
    yield


def test_resolve_path_uses_user_default_for_known_keys() -> None:
    """Well-known path-like settings resolve to ~/.tgparser/... by default."""
    p = resolve_path("output_dir")
    assert p == DEFAULT_OUTPUT_DIR
    assert p.exists()
    assert p.is_absolute()
    home = Path.home().resolve()
    assert str(p.resolve()).startswith(str(home))


def test_resolve_path_session_dir() -> None:
    p = resolve_path("session_dir")
    assert p == DEFAULT_SESSION_DIR
    assert p.exists()
    assert p.is_absolute()


def test_resolve_path_unknown_key_uses_default() -> None:
    """For unknown keys, fall back to the caller-supplied default."""
    custom = Path.home() / "custom_default_dir"
    p = resolve_path("nonexistent", default=custom)
    assert p == custom


def test_resolve_path_expands_user(monkeypatch) -> None:
    """If a YAML config sets '~/foo', expanduser is applied."""
    monkeypatch.setattr(cfg, "_yaml_config", {"output_dir": "~/my_results"})
    p = resolve_path("output_dir")
    assert str(p) == str((Path.home() / "my_results").resolve())


def test_resolve_path_relative_becomes_user_data(monkeypatch) -> None:
    """Relative output_dir is anchored under USER_DATA_DIR, not CWD."""
    monkeypatch.setattr(cfg, "_yaml_config", {"output_dir": "subdir"})
    p = resolve_path("output_dir")
    assert p == USER_DATA_DIR / "subdir"


def test_resolve_path_legacy_data_anchored_at_project_root(monkeypatch) -> None:
    """Old ``data/output`` style still resolves under PROJECT_ROOT."""
    monkeypatch.setattr(cfg, "_yaml_config", {"output_dir": "data/output"})
    p = resolve_path("output_dir")
    assert p == Path(cfg.PROJECT_ROOT) / "data" / "output"


def test_get_setting_returns_builtin_default() -> None:
    """When YAML has no value, get_setting returns the built-in default."""
    v = get_setting("output_dir")
    assert v == str(DEFAULT_OUTPUT_DIR)
    v = get_setting("session_dir")
    assert v == str(DEFAULT_SESSION_DIR)
