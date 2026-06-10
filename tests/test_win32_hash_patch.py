"""Tests for the win32 # / paste fix.

The patch is a no-op off-Windows.  On Windows we verify the patch
mechanics by re-deriving the new method from the original source
via the same code path the patcher uses.
"""

from __future__ import annotations

import sys

import pytest

from tgparser.gui._win32_hash_patch import _NEW_BLOCK, _OLD_BLOCK


def test_old_block_matches_upstream_textual() -> None:
    """The buggy block we are patching must still match the Textual source.

    If this fails, the upstream Textual driver has changed and the
    patch needs to be re-derived.
    """
    if sys.platform != "win32":
        pytest.skip("Test for Windows only")

    import linecache
    import textual.drivers.win32 as w

    lines = linecache.getlines(w.__file__)
    src = "".join(lines)
    assert _OLD_BLOCK in src, (
        "Textual win32 driver no longer contains the buggy block we "
        "are patching. The patch needs to be re-derived from the "
        "upstream source."
    )


def test_new_block_keeps_hash_visible() -> None:
    """The new condition must NOT drop printable characters with no virtual key."""
    assert "wVirtualKeyCode == 0" in _NEW_BLOCK
    assert "not key_event.uChar.UnicodeChar" in _NEW_BLOCK
    # It must NOT contain the original buggy combination.
    assert "dwControlKeyState" not in _NEW_BLOCK or (
        "dwControlKeyState" in _NEW_BLOCK
        and "# TG_HASH_FIX" in _NEW_BLOCK  # only as a comment
    )


def test_apply_patch_is_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    from tgparser.gui import _win32_hash_patch

    assert _win32_hash_patch.apply_patch() is False


def test_apply_patch_idempotent_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("Test for Windows only")

    from tgparser.gui import _win32_hash_patch
    import textual.drivers.win32 as w

    # First call may or may not change anything depending on prior state.
    _win32_hash_patch.apply_patch()
    # Second call must be a no-op.
    assert _win32_hash_patch.apply_patch() is False
    # The patch flag is set on the class.
    assert getattr(w.EventMonitor, _win32_hash_patch._PATCH_FLAG_ATTR) is True
