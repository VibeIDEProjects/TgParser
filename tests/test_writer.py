"""Tests for tgparser.storage.writer — JSON, CSV, TXT, SQLite, incremental."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tgparser.models.message import Message
from tgparser.storage.writer import (
    _write_csv,
    _write_json,
    _write_markdown,
    _write_sqlite,
    _write_txt,
    get_last_message_id,
    get_seen_message_ids,
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
    """New run merges — combined file now contains the union of known messages."""
    # First run with only first 2 messages
    save_messages_incremental(
        sample_messages[:2], tmp_output_dir, "@test_channel", fmt="json"
    )
    # Second run with all 3 — combined file should now contain all 3.
    result = save_messages_incremental(
        sample_messages, tmp_output_dir, "@test_channel", fmt="json"
    )
    assert result is not None
    data = json.loads(result.read_text(encoding="utf-8"))
    ids = {d["id"] for d in data}
    assert ids == {1, 2, 3}
    # The state file should mark all 3 as seen.
    assert get_seen_message_ids(tmp_output_dir, "@test_channel") == {1, 2, 3}


def test_save_messages_incremental_state_file(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """State file is created and contains the full seen-id list."""
    save_messages_incremental(sample_messages, tmp_output_dir, "@test_channel", fmt="json")
    state_file = tmp_output_dir / "test_channel_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    # Backwards compat: last_message_id is still set.
    assert state["last_message_id"] == 3
    # New schema: full id set is also present.
    assert sorted(state["message_ids"]) == [1, 2, 3]
    assert state["count"] == 3


# ------------------------------------------------------------------
# get_last_message_id
# ------------------------------------------------------------------


def test_get_last_message_id_none(tmp_output_dir: Path) -> None:
    """No state file → returns None."""
    assert get_last_message_id(tmp_output_dir, "@nonexistent") is None
    assert get_seen_message_ids(tmp_output_dir, "@nonexistent") == set()


def test_get_last_message_id_from_state(tmp_output_dir: Path) -> None:
    """State file present → returns stored id."""
    from tgparser.storage.writer import _persist_seen_ids

    _persist_seen_ids(tmp_output_dir, "@channel", {41, 42, 43})
    assert get_last_message_id(tmp_output_dir, "@channel") == 43
    assert get_seen_message_ids(tmp_output_dir, "@channel") == {41, 42, 43}


def test_get_last_message_id_from_sqlite(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """SQLite metadata is queried when db_path is given (and no messages table yet)."""
    from tgparser.storage.sqlite import update_last_message_id

    db_path = tmp_output_dir / "test.db"
    update_last_message_id(db_path, "@test_channel", 7)
    last_id = get_last_message_id(tmp_output_dir, "@test_channel", db_path=db_path)
    assert last_id == 7
    assert get_seen_message_ids(tmp_output_dir, "@test_channel", db_path=db_path) == {7}


# ------------------------------------------------------------------
# Markdown export
# ------------------------------------------------------------------


def test_save_messages_markdown(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """Markdown export produces a readable .md file."""
    fp = save_messages(sample_messages, tmp_output_dir, "@md", fmt="markdown")
    assert fp is not None
    assert fp.suffix == ".md"
    text = fp.read_text(encoding="utf-8")
    assert text.startswith("# @test_channel")
    assert "## Message #1" in text
    assert "First message" in text
    assert "https://example.com/img1.jpg" in text
    assert "Forwarded" in text  # message #2 is forwarded


def test_save_messages_markdown_extension(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """The canonical ``markdown`` format produces a ``.md`` file."""
    fp = save_messages(sample_messages, tmp_output_dir, "@alias", fmt="markdown")
    assert fp is not None
    assert fp.suffix == ".md"


def test_write_markdown_empty(tmp_output_dir: Path) -> None:
    """Empty list produces a stub Markdown file."""
    fp = tmp_output_dir / "empty.md"
    _write_markdown(fp, [])
    assert "# (no messages)" in fp.read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Incremental with seen-id set
# ------------------------------------------------------------------


def test_incremental_uses_seen_set(
    tmp_output_dir: Path, sample_messages: list[Message]
) -> None:
    """Re-importing the same messages doesn't duplicate them."""
    save_messages_incremental(sample_messages, tmp_output_dir, "@dedup")
    # Second call with the SAME messages should produce no new output.
    result = save_messages_incremental(sample_messages, tmp_output_dir, "@dedup")
    assert result is None
    # And the seen set still equals the original ids.
    assert get_seen_message_ids(tmp_output_dir, "@dedup") == {1, 2, 3}


def test_incremental_skips_known_ids(
    tmp_output_dir: Path, sample_messages: list[Message]
) -> None:
    """Only the new message is appended on the second run."""
    save_messages_incremental(sample_messages[:2], tmp_output_dir, "@mix")
    new_msg = Message(
        id=99,
        channel="@mix",
        date=datetime(2025, 1, 20, 12, 0, 0, tzinfo=UTC),
        text="Newly arrived",
    )
    fp = save_messages_incremental(
        sample_messages[:2] + [new_msg], tmp_output_dir, "@mix"
    )
    assert fp is not None
    # The combined file should contain all three ids.
    assert {1, 2, 99} == get_seen_message_ids(tmp_output_dir, "@mix")
    data = json.loads(fp.read_text(encoding="utf-8"))
    ids = {d["id"] for d in data}
    assert ids == {1, 2, 99}


def test_incremental_markdown_format(tmp_output_dir: Path, sample_messages: list[Message]) -> None:
    """Incremental export also works in Markdown format."""
    fp = save_messages_incremental(
        sample_messages, tmp_output_dir, "@mdinc", fmt="markdown"
    )
    assert fp is not None
    text = fp.read_text(encoding="utf-8")
    assert "# @test_channel" in text
    # Second call: nothing new, no new file.
    fp2 = save_messages_incremental(
        sample_messages, tmp_output_dir, "@mdinc", fmt="markdown"
    )
    assert fp2 is None
