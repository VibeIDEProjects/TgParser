"""Monkey-patch the Textual win32 driver so '#' is delivered to widgets.

Background
----------
Textual on Windows reads keyboard input through ``ReadConsoleInputW``
via the ``textual.drivers.win32.EventMonitor`` thread.  Inside its
``run()`` loop the original code drops an event when both
``dwControlKeyState != 0`` (i.e. a modifier is held) AND
``wVirtualKeyCode == 0``:

.. code-block:: python

    if key_event.dwControlKeyState and key_event.wVirtualKeyCode == 0:
        continue

The intent is to skip "true control" events (mouse, resize, ...)
that have no real character to deliver.  Unfortunately, on modern
Windows Terminal the same combination is produced for **legitimate
printable characters generated with a modifier** (``#`` from
Shift+3, ``?`` from Shift+/, etc.) and for **clipboard-pasted
characters** - the terminal reports the modifier state but
clears the virtual key code, because the event is not coming from
a physical key.

The end result is that ``#`` (and many other useful characters)
silently disappear before they ever reach XTermParser / Input.
This module fixes that by **only** skipping events where there is
*also* no Unicode character to deliver:

.. code-block:: python

    if key_event.wVirtualKeyCode == 0 and not key_event.uChar.UnicodeChar:
        continue

The patch is idempotent: re-importing the module will not stack
multiple ``run()`` overrides.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any


_PATCH_FLAG_ATTR = "_tg_hash_fix_applied"

_OLD_BLOCK = """                        if key_event.bKeyDown:
                            if (
                                key_event.dwControlKeyState
                                and key_event.wVirtualKeyCode == 0
                            ):
                                continue
                            append_key(key)"""

_NEW_BLOCK = """                        if key_event.bKeyDown:
                            # TG_HASH_FIX: original code dropped the
                            # event whenever a modifier was active
                            # (``dwControlKeyState``) and the virtual
                            # key code was 0.  On Windows Terminal that
                            # condition matches every shifted printable
                            # character (``#`` from Shift+3, ``?`` from
                            # Shift+/, ...) and every clipboard-pasted
                            # character.  Skip only true control events
                            # where there is no Unicode character to
                            # deliver at all.
                            if (
                                key_event.wVirtualKeyCode == 0
                                and not key_event.uChar.UnicodeChar
                            ):
                                continue
                            append_key(key)"""


def _build_patched_run() -> Any:
    """Return a new ``EventMonitor.run`` function with the fix applied.

    We read the source of the original method via ``linecache`` (which
    handles module path resolution even for files inside ``.venv``)
    and substitute the buggy block with the corrected one.
    """
    import linecache
    import re

    import textual.drivers.win32 as _win32

    lines = linecache.getlines(_win32.__file__)
    text = "".join(lines)

    # Locate the EventMonitor.run method.  Capture the leading
    # indentation separately so we can ``dedent`` the body before
    # recompiling it as a top-level function.
    match = re.search(
        r"(\s+)def run\(self\) -> None:\n(.*?)(?=\n    def |\nclass |\Z)",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Could not locate EventMonitor.run in win32.py")

    leading_indent = match.group(1)
    body = match.group(2)

    if _OLD_BLOCK not in body:
        if _PATCH_FLAG_ATTR in body:
            # Already patched upstream - just return the original.
            return _win32.EventMonitor.run
        raise RuntimeError(
            "EventMonitor.run source no longer matches the expected "
            "block; the patch needs to be re-derived."
        )

    new_body = body.replace(_OLD_BLOCK, _NEW_BLOCK, 1)
    # Strip the leading indent that came from the class scope so the
    # body parses correctly when re-defined as a top-level function.
    n = len(leading_indent)
    new_body = "".join(
        line[n:] if line.startswith(leading_indent) else line
        for line in new_body.splitlines(keepends=True)
    )

    src = "def run(self) -> None:\n" + new_body

    # Compile in a module-like namespace so that the symbols used by
    # the method body are visible.
    namespace: dict[str, Any] = {
        "__name__": "_tg_patched_event_monitor_run",
        "__file__": _win32.__file__,
    }
    for name in (
        "XTermParser",
        "GetStdHandle",
        "STD_INPUT_HANDLE",
        "KERNEL32",
        "wintypes",
        "byref",
        "INPUT_RECORD",
        "wait_for_handles",
        "constants",
        "List",
    ):
        if name in _win32.__dict__:
            namespace[name] = _win32.__dict__[name]

    code = compile(src, _win32.__file__, "exec")
    exec(code, namespace)
    return namespace["run"]


def apply_patch() -> bool:
    """Replace ``EventMonitor.run`` with a fixed version.

    Returns ``True`` if a change was made, ``False`` if the patch
    was already applied or could not be applied.
    """
    # Only relevant on Windows.
    if sys.platform != "win32":
        return False

    import textual.drivers.win32 as _win32

    if getattr(_win32.EventMonitor, _PATCH_FLAG_ATTR, False):
        return False

    try:
        new_run = _build_patched_run()
    except Exception as exc:  # pragma: no cover - defensive
        # If patching fails we should NOT crash the GUI.
        # Log to stderr so the user can see the failure.
        print(
            f"[tgparser] Could not apply win32 # fix: {exc!r}",
            file=sys.stderr,
        )
        return False

    # ``run`` is a regular method on a Thread subclass.
    # Assigning a plain function to the class makes Python wrap it
    # as a bound method on access, so ``self`` (the instance) is
    # passed in normally.  Do NOT use ``types.MethodType(func, cls)``
    # here: that would bind ``cls`` itself as ``__self__`` and the
    # instance ``self`` would never be forwarded, silently breaking
    # the event loop.
    _win32.EventMonitor.run = new_run
    setattr(_win32.EventMonitor, _PATCH_FLAG_ATTR, True)
    return True


# Touch threading so the import is not flagged as unused when running
# the module on its own (e.g. for ``python -m tgparser.gui._win32_hash_patch``).
_ = threading
