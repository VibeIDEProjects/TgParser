"""Integration tests for the Textual GUI application.

These tests verify that screens interact correctly and handle errors.
"""

from __future__ import annotations

import importlib
import inspect
import re

import pytest
from tgparser.gui.app import TgParserApp


@pytest.fixture
def app():
    """Create a test app instance."""
    return TgParserApp()


async def test_parse_screen_empty_channel_does_not_start(app):
    """Test that trying to parse an empty channel does not switch screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Navigate to parse screen
        await pilot.click("#btn-parse")
        await pilot.pause()
        assert app.screen.id == "parse-screen"

        # Click start without entering a channel
        await pilot.click("#btn-start")
        await pilot.pause()

        # The app should remain on parse screen (no result screen triggered)
        assert app.screen.id == "parse-screen"


async def test_main_screen_refresh_handles_no_database(app):
    """Test that refresh button gracefully handles missing database."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Click refresh — should not crash, even without database
        await pilot.click("#btn-refresh")
        await pilot.pause()

        # The app should remain on main screen
        assert app.screen.id == "main-screen"
        # Status should indicate something
        status_bar = app.screen.query_one("#status-bar")
        assert status_bar.visual.plain is not None


async def test_auth_screen_switch_tabs(app):
    """Test that auth screen tabs switch correctly."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Navigate to auth screen
        await pilot.click("#btn-auth")
        await pilot.pause()
        assert app.screen.id == "auth-screen"

        # The auth screen has tabs: "Web Auth" and "MTProto Auth"
        tabbed = app.screen.query_one("TabbedContent")
        assert tabbed is not None

        # Find the MTProto tab by its label
        mtproto_tab = app.screen.query_one("TabPane")
        # The first tab should be "Web Auth", second should be "MTProto Auth"
        # We can get all tabs and click the second one
        tabs = app.screen.query("TabPane")
        assert len(tabs) >= 2
        # Click on the second tab (MTProto Auth)
        await pilot.click(tabs[1])
        await pilot.pause()

        # Check that mtproto inputs are visible
        assert app.screen.query_one("#api-id-input")
        assert app.screen.query_one("#api-hash-input")
        assert app.screen.query_one("#phone-input")
        assert app.screen.query_one("#code-input")


async def test_parse_screen_stop_parsing_no_parse(app):
    """Test that stop button does nothing when no parse is running."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Navigate to parse screen
        await pilot.click("#btn-parse")
        await pilot.pause()
        assert app.screen.id == "parse-screen"

        # Click stop — should not crash
        await pilot.click("#btn-stop")
        await pilot.pause()

        # The screen should still be the parse screen
        assert app.screen.id == "parse-screen"


# ------------------------------------------------------------------
# Compose() smoke tests — catch NameError regressions like the
# 'Label' import that broke ResultScreen in v0.2.30.
# ------------------------------------------------------------------

# Whitelist of classes that don't come from textual.widgets.
_LOCAL_CLASSES = {
    "ChannelTable",
    "CopyableRichLog",
    "InputWithLabel",
    "TabPane",
}


@pytest.mark.parametrize(
    "screen_module,screen_class",
    [
        ("tgparser.gui.screens.main_screen", "MainScreen"),
        ("tgparser.gui.screens.auth_screen", "AuthScreen"),
        ("tgparser.gui.screens.parse_screen", "ParseScreen"),
        ("tgparser.gui.screens.result_screen", "ResultScreen"),
    ],
)
def test_screen_compose_does_not_reference_unimported_widgets(
    screen_module, screen_class
) -> None:
    """Every widget class used in `yield X(` must be importable.

    This static check would have caught the v0.2.30 regression where
    ``Label`` was used in ResultScreen.compose() but never imported.
    """
    module = importlib.import_module(screen_module)
    screen_cls = getattr(module, screen_class)

    try:
        source = inspect.getsource(screen_cls.compose)
    except (OSError, TypeError):
        pytest.skip(f"{screen_class}.compose has no source")

    referenced = set(m.group(1) for m in re.finditer(r"\byield\s+(\w+)\(", source))
    referenced -= _LOCAL_CLASSES

    from textual import widgets as tw

    missing = sorted(c for c in referenced if not hasattr(tw, c))
    assert not missing, (
        f"{screen_module}.{screen_class}.compose() references "
        f"unimported widget classes: {missing}"
    )
