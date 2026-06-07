"""Smoke tests for the Textual GUI application.

These tests verify that the application starts, renders correctly,
and basic navigation between screens works.
"""

import pytest
from tgparser.gui.app import TgParserApp


@pytest.fixture
def app():
    """Create a test app instance."""
    return TgParserApp()


async def test_app_starts(app):
    """Test that the application starts and renders the main screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Check that the main screen is showing
        assert app.screen is not None
        assert app.screen.id == "main-screen"
        # Check that key widgets are present
        assert app.screen.query_one("#welcome-text")
        assert app.screen.query_one("#channel-table")
        assert app.screen.query_one("#btn-auth")
        assert app.screen.query_one("#btn-parse")
        assert app.screen.query_one("#btn-export")
        assert app.screen.query_one("#btn-refresh")
        assert app.screen.query_one("#status-bar")


async def test_navigation_to_auth_screen(app):
    """Test navigation from main screen to auth screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Click on Auth button
        await pilot.click("#btn-auth")
        # Wait for the screen to switch
        await pilot.pause()
        # Check that we are on auth screen
        assert app.screen.id == "auth-screen"
        # Check auth screen widgets
        assert app.screen.query_one("#auth-title")
        assert app.screen.query_one("#api-id-input")
        assert app.screen.query_one("#api-hash-input")
        assert app.screen.query_one("#phone-input")
        assert app.screen.query_one("#code-input")
        assert app.screen.query_one("#btn-auth-start")
        assert app.screen.query_one("#btn-auth-cancel")


async def test_navigation_to_parse_screen(app):
    """Test navigation from main screen to parse screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Click on Parse Channel button
        await pilot.click("#btn-parse")
        await pilot.pause()
        # Check that we are on parse screen
        assert app.screen.id == "parse-screen"
        # Check parse screen widgets
        assert app.screen.query_one("#parse-title")
        assert app.screen.query_one("#channel-input")
        assert app.screen.query_one("#channel-type-select")
        assert app.screen.query_one("#limit-input")
        assert app.screen.query_one("#date-from-input")
        assert app.screen.query_one("#date-to-input")
        assert app.screen.query_one("#btn-start")
        assert app.screen.query_one("#btn-stop")
        assert app.screen.query_one("#btn-back")
        assert app.screen.query_one("#progress-bar")


async def test_parse_screen_back_navigation(app):
    """Test that back button on parse screen returns to main screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Go to parse screen
        await pilot.click("#btn-parse")
        await pilot.pause()
        assert app.screen.id == "parse-screen"
        # Try clicking back; scroll_visible may be needed
        await pilot.pause(0.3)
        btn_back = app.screen.query_one("#btn-back")
        # Scroll the button into view
        btn_back.scroll_visible()
        await pilot.pause(0.3)
        # Use click with widget reference
        await pilot.click(btn_back)
        await pilot.pause(0.3)
        assert app.screen.id == "main-screen"


async def test_auth_screen_cancel_navigation(app):
    """Test that cancel button on auth screen returns to main screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Go to auth screen
        await pilot.click("#btn-auth")
        await pilot.pause()
        assert app.screen.id == "auth-screen"
        # Click cancel
        await pilot.click("#btn-auth-cancel")
        await pilot.pause()
        assert app.screen.id == "main-screen"


async def test_status_bar_text(app):
    """Test that the status bar shows the default message."""
    async with app.run_test(size=(120, 40)) as pilot:
        status_bar = app.screen.query_one("#status-bar")
        # Use .visual.plain to get the text content of a Static widget
        assert "Ready" in status_bar.visual.plain


async def test_channel_table_exists(app):
    """Test that the channel table widget exists and has columns."""
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.screen.query_one("#channel-table")
        columns = table.columns
        assert len(columns) >= 3  # Should have Channel, Last Parsed, Actions


async def test_main_screen_header(app):
    """Test that the main screen header/title is displayed."""
    async with app.run_test(size=(120, 40)) as pilot:
        welcome = app.screen.query_one("#welcome-text")
        # Use .visual.plain to get the text content of a Label widget
        assert "TgParser" in welcome.visual.plain
