"""Tests for CLI export and format-conversion helpers."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from tgparser.cli import _dict_to_message, _parse_txt, main
from tgparser.models.message import Message
from tgparser.storage.writer import _write_csv, _write_json, _write_txt

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def sample_messages() -> list[Message]:
    """Return a few Message objects."""
    return [
        Message(
            id=1,
            channel="@test",
            date=datetime(2025, 3, 1, 8, 0, 0, tzinfo=UTC),
            author="Alice",
            text="First",
            media_urls=["https://example.com/a.jpg"],
            reactions={"👍": 2},
            is_forwarded=False,
            raw_source="test",
        ),
        Message(
            id=2,
            channel="@test",
            date=datetime(2025, 3, 1, 9, 0, 0, tzinfo=UTC),
            author=None,
            text="Second",
            media_urls=[],
            reactions=None,
            is_forwarded=True,
            raw_source="test",
        ),
    ]


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Temporary directory for test data."""
    path = tmp_path / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------------
# _dict_to_message
# ------------------------------------------------------------------


def test_dict_to_message_full() -> None:
    """Full dict with all fields converts correctly."""
    d = {
        "id": "10",
        "channel": "@chan",
        "date": "2025-03-01T12:00:00+00:00",
        "author": "Alice",
        "text": "Hello",
        "media_urls": "https://example.com/img.jpg|https://example.com/img2.jpg",
        "reactions": '{"👍": 3}',
        "is_forwarded": "True",
        "raw_source": "mtproto",
    }
    msg = _dict_to_message(d)
    assert msg.id == 10
    assert msg.channel == "@chan"
    assert msg.author == "Alice"
    assert msg.text == "Hello"
    assert msg.media_urls == ["https://example.com/img.jpg", "https://example.com/img2.jpg"]
    assert msg.reactions == {"👍": 3}
    assert msg.is_forwarded is True
    assert msg.raw_source == "mtproto"


def test_dict_to_message_minimal() -> None:
    """Minimal dict with required fields only."""
    d = {
        "id": "1",
        "channel": "@c",
        "date": "2025-01-01T00:00:00+00:00",
        "author": "",
        "text": "text",
        "media_urls": "",
        "reactions": "",
        "is_forwarded": "False",
        "raw_source": "",
    }
    msg = _dict_to_message(d)
    assert msg.id == 1
    assert msg.author is None
    assert msg.media_urls == []
    assert msg.reactions == {}
    assert msg.is_forwarded is False


# ------------------------------------------------------------------
# _parse_txt
# ------------------------------------------------------------------


def test_parse_txt(tmp_data_dir: Path) -> None:
    """Roundtrip: write TXT → read back via _parse_txt."""
    messages = [
        Message(
            id=5,
            channel="@chan",
            date=datetime(2025, 6, 15, 14, 30, 0, tzinfo=UTC),
            author="Bot",
            text="Hello world!\nSecond line.",
            media_urls=["https://example.com/pic.png"],
            reactions={"🔥": 1},
            is_forwarded=False,
            raw_source="web",
        ),
    ]
    filepath = tmp_data_dir / "test.txt"
    _write_txt(filepath, messages)

    parsed = _parse_txt(filepath)
    assert len(parsed) == 1
    p = parsed[0]
    assert p.id == 5
    assert p.channel == "@chan"
    assert p.author == "Bot"
    assert p.text == "Hello world!\nSecond line."
    assert p.media_urls == ["https://example.com/pic.png"]
    assert p.reactions == {"🔥": 1}


def test_parse_txt_empty(tmp_data_dir: Path) -> None:
    """Empty file produces empty list."""
    filepath = tmp_data_dir / "empty.txt"
    filepath.write_text("", encoding="utf-8")
    assert _parse_txt(filepath) == []


# ------------------------------------------------------------------
# CLI export command
# ------------------------------------------------------------------


def test_export_json_to_csv(tmp_data_dir: Path, sample_messages: list[Message]) -> None:
    """Convert a JSON file to CSV via the export command."""
    # Create a JSON input file
    json_file = tmp_data_dir / "output.json"
    _write_json(json_file, sample_messages)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "export",
            str(json_file),
            "--format", "csv",
            "--output-dir", str(tmp_data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Exported 2 messages" in result.output

    # Check CSV file was created
    csv_files = list(tmp_data_dir.glob("*.csv"))
    assert len(csv_files) == 1
    with csv_files[0].open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    assert len(rows) == 2


def test_export_csv_to_json(tmp_data_dir: Path, sample_messages: list[Message]) -> None:
    """Convert a CSV file to JSON via the export command."""
    csv_file = tmp_data_dir / "input.csv"
    _write_csv(csv_file, sample_messages)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "export",
            str(csv_file),
            "--format", "json",
            "--output-dir", str(tmp_data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    json_files = list(tmp_data_dir.glob("input_*.json"))
    assert len(json_files) >= 1


def test_export_txt_to_json(tmp_data_dir: Path, sample_messages: list[Message]) -> None:
    """Convert a TXT file to JSON via the export command."""
    txt_file = tmp_data_dir / "messages.txt"
    _write_txt(txt_file, sample_messages)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "export",
            str(txt_file),
            "--format", "json",
            "--output-dir", str(tmp_data_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    json_files = list(tmp_data_dir.glob("messages_*.json"))
    assert len(json_files) >= 1


def test_export_unsupported_input_format(tmp_data_dir: Path) -> None:
    """Export with an unsupported input format raises an error."""
    unsupported = tmp_data_dir / "data.abc"
    unsupported.write_text("something", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "export",
            str(unsupported),
            "--format", "json",
        ],
    )
    assert result.exit_code != 0
    assert "Unsupported input format" in result.output


def test_export_no_messages(tmp_data_dir: Path) -> None:
    """Export an empty JSON file produces a warning but no error."""
    empty_json = tmp_data_dir / "empty.json"
    empty_json.write_text("[]", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "export",
            str(empty_json),
            "--format", "json",
            "--output-dir", str(tmp_data_dir),
        ],
    )
    assert result.exit_code == 0
    assert "No messages found" in result.output
