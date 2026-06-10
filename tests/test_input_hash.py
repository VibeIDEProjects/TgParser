"""Regression test: Textual ``Input`` widget must accept and display ``#``.

If this test fails the issue is in Textual / terminal handling, not in
the application.  When it passes but the GUI still drops ``#`` we know
the bug is somewhere else in the screen / app layer.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult
from textual.widgets import Input


class InputApp(App):
    def compose(self) -> ComposeResult:
        yield Input(id="probe", value="")


async def test_input_accepts_hash_via_value() -> None:
    """Setting ``value`` directly stores the ``#``."""
    app = InputApp()
    async with app.run_test() as pilot:
        probe = app.query_one("#probe", Input)
        probe.value = "https://web.telegram.org/a/#-1003929682471"
        await pilot.pause()
        assert probe.value == "https://web.telegram.org/a/#-1003929682471"
        assert "#" in probe.value


async def test_input_strips_hash_via_select_all_and_replace() -> None:
    """Simulating select-all + paste should keep ``#`` in ``value``."""
    app = InputApp()
    async with app.run_test() as pilot:
        probe = app.query_one("#probe", Input)
        # Set a baseline and then replace it wholesale.
        probe.value = "abc"
        await pilot.pause()
        probe.value = "abc#def"
        await pilot.pause()
        assert probe.value == "abc#def"
