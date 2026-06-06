"""Tests for tgparser.storage.sqlite — SQLite persistence layer."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tgparser.models.message import Message
from tgparser.storage.sqlite import (
    _ensure_tables,
    get_last_message_id,
    save_messages,
    update_last_message_id,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def sample_messages() -> list[Message]:
    """Return a few Message objects for testing."""
    return [
        Message(
            id=10,
            channel="@channel_a",
            date=datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC),
            author="Alice",
            text="Hello from SQLite",
            media_urls=["https://example.com/a.jpg"],
            reactions={"👍": 1},
            is_forwarded=False,
            raw_source="test",
        ),
        Message(
            id=20,
            channel="@channel_a",
            date=datetime(2025, 2, 1, 12, 5, 0, tzinfo=UTC),
            author="Bob",
            text="Second message",
            media_urls=[],
            reactions=None,
            is_forwarded=True,
            raw_source="test",
        ),
    ]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Path to a temporary SQLite database."""
    return tmp_path / "test.db"


# ------------------------------------------------------------------
# _ensure_tables
# ------------------------------------------------------------------


def test_ensure_tables_creates_schema(db_path: Path) -> None:
    """Tables messages and metadata are created."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_tables(conn)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "messages" in table_names
        assert "metadata" in table_names
    finally:
        conn.close()


def test_ensure_tables_idempotent(db_path: Path) -> None:
    """Calling _ensure_tables multiple times does not fail."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_tables(conn)
        _ensure_tables(conn)  # second call
    finally:
        conn.close()


# ------------------------------------------------------------------
# save_messages
# ------------------------------------------------------------------


def test_save_messages_inserts(db_path: Path, sample_messages: list[Message]) -> None:
    """Messages are correctly inserted into the database."""
    save_messages(db_path, sample_messages)

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 2

        row = conn.execute(
            "SELECT id, channel, text, media_urls, reactions FROM messages WHERE id = 10"
        ).fetchone()
        assert row[0] == 10
        assert row[1] == "@channel_a"
        assert row[2] == "Hello from SQLite"
        assert json.loads(row[3]) == ["https://example.com/a.jpg"]
        assert json.loads(row[4]) == {"👍": 1}
    finally:
        conn.close()


def test_save_messages_ignore_duplicates(db_path: Path, sample_messages: list[Message]) -> None:
    """Inserting same messages again should not create duplicates."""
    save_messages(db_path, sample_messages)
    save_messages(db_path, sample_messages)  # second write

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 2  # still 2
    finally:
        conn.close()


def test_save_messages_empty(db_path: Path) -> None:
    """Empty message list does not cause errors."""
    save_messages(db_path, [])
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


# ------------------------------------------------------------------
# get_last_message_id
# ------------------------------------------------------------------


def test_get_last_message_id_returns_none_for_empty(db_path: Path) -> None:
    """No data for a channel → None."""
    assert get_last_message_id(db_path, "@nonexistent") is None


def test_get_last_message_id_from_metadata(db_path: Path) -> None:
    """When metadata exists, it takes precedence over scanning messages."""
    # Insert a message
    msg = Message(
        id=42,
        channel="@test",
        date=datetime(2025, 1, 1, tzinfo=UTC),
        text="test",
    )
    save_messages(db_path, [msg])
    # Update metadata explicitly
    update_last_message_id(db_path, "@test", 42)

    # Add a newer message that is NOT in metadata
    msg2 = Message(
        id=99,
        channel="@test",
        date=datetime(2025, 1, 2, tzinfo=UTC),
        text="newer",
    )
    save_messages(db_path, [msg2])

    # The metadata still says 42
    assert get_last_message_id(db_path, "@test") == 42


def test_get_last_message_id_from_scan(db_path: Path) -> None:
    """Without metadata, scan the messages table for MAX(id)."""
    msg1 = Message(
        id=5,
        channel="@test",
        date=datetime(2025, 1, 1, tzinfo=UTC),
        text="first",
    )
    msg2 = Message(
        id=10,
        channel="@test",
        date=datetime(2025, 1, 2, tzinfo=UTC),
        text="second",
    )
    save_messages(db_path, [msg1, msg2])
    assert get_last_message_id(db_path, "@test") == 10


# ------------------------------------------------------------------
# update_last_message_id
# ------------------------------------------------------------------


def test_update_last_message_id_inserts(db_path: Path) -> None:
    """First call inserts a record."""
    update_last_message_id(db_path, "@test", 100)
    assert get_last_message_id(db_path, "@test") == 100


def test_update_last_message_id_updates(db_path: Path) -> None:
    """Second call updates the existing record."""
    update_last_message_id(db_path, "@test", 100)
    update_last_message_id(db_path, "@test", 200)
    assert get_last_message_id(db_path, "@test") == 200


def test_update_last_message_id_multiple_channels(db_path: Path) -> None:
    """Different channels have independent metadata."""
    update_last_message_id(db_path, "@a", 1)
    update_last_message_id(db_path, "@b", 2)
    assert get_last_message_id(db_path, "@a") == 1
    assert get_last_message_id(db_path, "@b") == 2
