"""Tests for tgparser.storage.writer — JSON, CSV, TXT, SQLite, incremental."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tgparser.models.message import Message
from tgparser.storage.writer import (
    _save_last_message_id,
    _write_csv,
    _write_json,
    _write_sqlite,
    _write_txt,
    get_last_message_id,
    save_messages,
    save_messages_incremental,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def sample_messages() -> list[Message]:
    """Return a few Message objects for testing."""
    return [
        Message(
            id=1,
            channel="@test_channel",
            date=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
            author="Alice",
            text="First message",
            media_urls=["https://example.com/img1.jpg"],
            reactions={"👍": 3},
            is_forwarded=False,
            raw_source="test",
        ),
        Message(
            id=2,
            channel="@test_channel",
            date=datetime(2025, 1, 15, 10, 5, 0, tzinfo=UTC),
            author="Bob",
            text="Second message with no media",
            media_urls=[],
            reactions={},
            is_forwarded=True,
            raw_source="test",
        ),
        Message(
            id=3,
            channel="@test_channel",
            date=datetime(2025, 1, 15, 10, 10, 0, tzinfo=UTC),
            author=None,
            text="Third message, no author",
            media_urls=["https://example.com/img2.jpg", "https://example.com/img3.jpg"],
            reactions={"❤️": 5, "🔥": 2},
            is_forwarded=False,
            raw_source="test",
        ),
    ]


@pytest.fixture
def tmp_output_dir(tmp_path: Path) -> Path:
    """A temporary directory for output files."""
    path = tmp_path / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------------
# JSON writer
# ------------------------------------------------------------------


def test_write_json(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """JSON file is valid and contains all message fields."""
    filepath = tmp_output_dir / "test.json"
    _write_json(filepath, sample_messages)

    assert filepath.exists()
    data = json.loads(filepath.read_text(encoding="utf-8"))
    assert len(data) == 3

    first = data[0]
    assert first["id"] == 1
    assert first["channel"] == "@test_channel"
    assert first["author"] == "Alice"
    assert first["text"] == "First message"
    assert first["media_urls"] == ["https://example.com/img1.jpg"]
    assert first["reactions"] == {"👍": 3}
    assert first["is_forwarded"] is False
    assert "date" in first


def test_write_json_empty(tmp_output_dir: Path) -> None:
    """Empty message list produces an empty JSON array."""
    filepath = tmp_output_dir / "empty.json"
    _write_json(filepath, [])
    data = json.loads(filepath.read_text(encoding="utf-8"))
    assert data == []


# ------------------------------------------------------------------
# CSV writer
# ------------------------------------------------------------------


def test_write_csv(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """CSV file is valid and contains all expected columns."""
    filepath = tmp_output_dir / "test.csv"
    _write_csv(filepath, sample_messages)

    assert filepath.exists()
    import csv

    with filepath.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 3

    first = rows[0]
    assert first["id"] == "1"
    assert first["channel"] == "@test_channel"
    assert first["author"] == "Alice"
    assert first["text"] == "First message"
    assert first["media_urls"] == "https://example.com/img1.jpg"  # single URL, no pipe
    assert "👍" in first["reactions"]
    assert first["is_forwarded"] == "False"

    # Third message has multiple media URLs → pipe separator
    third = rows[2]
    assert "|" in third["media_urls"]


def test_write_csv_empty(tmp_output_dir: Path) -> None:
    """Empty message list produces a CSV with header only."""
    filepath = tmp_output_dir / "empty.csv"
    _write_csv(filepath, [])
    assert filepath.exists()
    content = filepath.read_text(encoding="utf-8")
    assert content.startswith("id,channel")


# ------------------------------------------------------------------
# TXT writer
# ------------------------------------------------------------------


def test_write_txt(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """TXT file contains readable structured text."""
    filepath = tmp_output_dir / "test.txt"
    _write_txt(filepath, sample_messages)

    assert filepath.exists()
    text = filepath.read_text(encoding="utf-8")

    # Should contain message headers and content
    assert "--- Message #1 ---" in text
    assert "--- Message #3 ---" in text
    assert "First message" in text
    assert "Second message with no media" in text
    assert "Third message, no author" in text
    assert "Alice" in text
    assert "Bob" in text
    assert "https://example.com/img1.jpg" in text


def test_write_txt_empty(tmp_output_dir: Path) -> None:
    """Empty message list produces an empty file."""
    filepath = tmp_output_dir / "empty.txt"
    _write_txt(filepath, [])
    assert filepath.exists()
    assert filepath.read_text(encoding="utf-8") == ""


# ------------------------------------------------------------------
# SQLite writer
# ------------------------------------------------------------------


def test_write_sqlite(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """SQLite file is created and messages are stored correctly."""
    db_path = tmp_output_dir / "test.db"
    _write_sqlite(db_path, sample_messages)

    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 3

        row = conn.execute("SELECT id, channel, text FROM messages WHERE id = 1").fetchone()
        assert row[0] == 1
        assert row[1] == "@test_channel"
        assert row[2] == "First message"

        # Verify metadata table exists
        meta = conn.execute("SELECT last_message_id FROM metadata WHERE channel = ?", ("@test_channel",)).fetchone()
        assert meta is None  # metadata not auto-populated by _write_sqlite
    finally:
        conn.close()


def test_write_sqlite_duplicates(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """Duplicate (id, channel) pairs are ignored with INSERT OR IGNORE."""
    db_path = tmp_output_dir / "dedup.db"
    _write_sqlite(db_path, sample_messages)
    _write_sqlite(db_path, sample_messages)  # second write

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        assert cursor.fetchone()[0] == 3  # still 3, not 6
    finally:
        conn.close()


# ------------------------------------------------------------------
# save_messages (high-level)
# ------------------------------------------------------------------


def test_save_messages_json(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """High-level save_messages produces a file with correct extension and content."""
    result = save_messages(sample_messages, tmp_output_dir, "@test_channel", fmt="json")
    assert result is not None
    assert result.suffix == ".json"
    assert result.exists()
    data = json.loads(result.read_text(encoding="utf-8"))
    assert len(data) == 3


def test_save_messages_csv(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """High-level save_messages with CSV format."""
    result = save_messages(sample_messages, tmp_output_dir, "@test_channel", fmt="csv")
    assert result is not None
    assert result.suffix == ".csv"
    assert result.exists()


def test_save_messages_txt(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """High-level save_messages with TXT format."""
    result = save_messages(sample_messages, tmp_output_dir, "@test_channel", fmt="txt")
    assert result is not None
    assert result.suffix == ".txt"
    assert result.exists()


def test_save_messages_sqlite(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """High-level save_messages with SQLite format."""
    db_path = tmp_output_dir / "out.db"
    result = save_messages(
        sample_messages, tmp_output_dir, "@test_channel", fmt="sqlite", db_path=db_path
    )
    assert result is None  # sqlite returns None
    assert db_path.exists()


def test_save_messages_sqlite_no_db_path(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """SQLite without db_path raises ValueError."""
    with pytest.raises(ValueError, match="db_path is required"):
        save_messages(sample_messages, tmp_output_dir, "@test_channel", fmt="sqlite")


def test_save_messages_invalid_format(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """Unsupported format raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported format"):
        save_messages(sample_messages, tmp_output_dir, "@test_channel", fmt="yaml")  # type: ignore


# ------------------------------------------------------------------
# Incremental parsing
# ------------------------------------------------------------------


def test_save_messages_incremental_first_run(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """First incremental run saves all messages and persists last id."""
    result = save_messages_incremental(
        sample_messages, tmp_output_dir, "@test_channel", fmt="json"
    )
    assert result is not None
    assert result.exists()
    data = json.loads(result.read_text(encoding="utf-8"))
    assert len(data) == 3

    # Last id should be stored
    last_id = get_last_message_id(tmp_output_dir, "@test_channel")
    assert last_id == 3


def test_save_messages_incremental_no_new(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """Second run with same messages yields nothing (all ids <= last)."""
    # First run
    save_messages_incremental(sample_messages, tmp_output_dir, "@test_channel", fmt="json")
    # Second run
    result = save_messages_incremental(
        sample_messages, tmp_output_dir, "@test_channel", fmt="json"
    )
    assert result is None  # no new data


def test_save_messages_incremental_partial_new(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """Only messages with id > last_saved are included."""
    # First run with only first 2 messages
    save_messages_incremental(
        sample_messages[:2], tmp_output_dir, "@test_channel", fmt="json"
    )
    # Second run with all 3 — only the 3rd is new
    result = save_messages_incremental(
        sample_messages, tmp_output_dir, "@test_channel", fmt="json"
    )
    assert result is not None
    data = json.loads(result.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == 3


def test_save_messages_incremental_state_file(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """State file is created and contains the correct last id."""
    save_messages_incremental(sample_messages, tmp_output_dir, "@test_channel", fmt="json")
    state_file = tmp_output_dir / "test_channel_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["last_message_id"] == 3


# ------------------------------------------------------------------
# get_last_message_id
# ------------------------------------------------------------------


def test_get_last_message_id_none(tmp_output_dir: Path) -> None:
    """No state file → returns None."""
    assert get_last_message_id(tmp_output_dir, "@nonexistent") is None


def test_get_last_message_id_from_state(tmp_output_dir: Path) -> None:
    """State file present → returns stored id."""
    _save_last_message_id(tmp_output_dir, "@channel", 42)
    assert get_last_message_id(tmp_output_dir, "@channel") == 42


def test_get_last_message_id_from_sqlite(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """SQLite metadata is queried when db_path is given."""
    db_path = tmp_output_dir / "test.db"
    from tgparser.storage.sqlite import update_last_message_id

    update_last_message_id(db_path, "@test_channel", 7)
    last_id = get_last_message_id(tmp_output_dir, "@test_channel", db_path=db_path)
    assert last_id == 7


# ------------------------------------------------------------------
# _save_last_message_id
# ------------------------------------------------------------------


def test_save_last_message_id(tmp_output_dir: Path) -> None:
    """State file is written correctly."""
    _save_last_message_id(tmp_output_dir, "@test", 99)
    state_file = tmp_output_dir / "test_state.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["last_message_id"] == 99
