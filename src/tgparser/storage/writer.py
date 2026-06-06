"""Serialize Message lists to structured formats (JSON, CSV, TXT, SQLite)."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from tgparser.models.message import Message

logger = logging.getLogger("tgparser")

OutputFormat = Literal["json", "csv", "txt", "sqlite"]


def save_messages(
    messages: list[Message],
    output_dir: str | Path,
    channel_name: str,
    fmt: OutputFormat = "json",
    db_path: str | Path | None = None,
) -> Path | None:
    """Persist *messages* to a file and return its path.

    File name is auto-generated: ``<channel>_<timestamp>.<ext>``.
    Creates *output_dir* if it does not exist.

    For ``sqlite`` format the result is written into an SQLite database;
    in that case *db_path* must be provided and the return value is ``None``.

    Args:
        messages: List of parsed messages.
        output_dir: Directory to write the output file.
        channel_name: Channel slug used in the file name.
        fmt: ``"json"``, ``"csv"``, ``"txt"`` or ``"sqlite"``.
        db_path: Path to the SQLite database file (required for ``sqlite``).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "sqlite":
        if db_path is None:
            raise ValueError("db_path is required for sqlite format")
        _write_sqlite(Path(db_path), messages)
        logger.info("Saved %d messages → sqlite:%s", len(messages), db_path)
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_channel = channel_name.lstrip("@").replace("/", "_")
    filename = f"{safe_channel}_{ts}.{fmt}"
    filepath = output_dir / filename

    if fmt == "json":
        _write_json(filepath, messages)
    elif fmt == "csv":
        _write_csv(filepath, messages)
    elif fmt == "txt":
        _write_txt(filepath, messages)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    logger.info("Saved %d messages → %s", len(messages), filepath)
    return filepath


def save_messages_incremental(
    messages: list[Message],
    output_dir: str | Path,
    channel_name: str,
    fmt: OutputFormat = "json",
    db_path: str | Path | None = None,
) -> Path | None:
    """Incremental variant -- only appends messages that are newer than the last stored ID.

    For file-based formats (json/csv/txt) the whole list is re-written each time,
    but only *new* messages (those with id > last saved id for that channel)
    are included.  For sqlite the new messages are inserted directly.

    The last message id is persisted in a small state file ``<channel>_state.json``
    inside *output_dir* (for file formats) or in the sqlite metadata table.
    """
    last_id = get_last_message_id(output_dir, channel_name, db_path)

    if last_id is not None:
        new_messages = [m for m in messages if m.id > last_id]
        if not new_messages:
            logger.info("No new messages for '%s' (last id = %d)", channel_name, last_id)
            return None
        logger.info("%d new messages (out of %d) for '%s'", len(new_messages), len(messages), channel_name)
    else:
        new_messages = messages

    result = save_messages(new_messages, output_dir, channel_name, fmt, db_path)

    # persist the new last id
    if new_messages:
        _save_last_message_id(output_dir, channel_name, max(m.id for m in new_messages))

    return result


def get_last_message_id(
    output_dir: str | Path,
    channel_name: str,
    db_path: str | Path | None = None,
) -> int | None:
    """Return the last persisted message id for *channel_name*, or ``None``."""
    if db_path is not None:
        from tgparser.storage.sqlite import get_last_message_id as _sqlite_last_id
        return _sqlite_last_id(Path(db_path), channel_name)

    state_file = Path(output_dir) / f"{channel_name.lstrip('@').replace('/', '_')}_state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return data.get("last_message_id")
        except Exception:
            logger.warning("Could not read state file %s", state_file)
    return None


# ------------------------------------------------------------------
# Internal writers
# ------------------------------------------------------------------


def _write_json(filepath: Path, messages: list[Message]) -> None:
    data = []
    for m in messages:
        data.append(
            {
                "id": m.id,
                "channel": m.channel,
                "date": m.date.isoformat(),
                "author": m.author,
                "text": m.text,
                "media_urls": m.media_urls,
                "reactions": m.reactions,
                "is_forwarded": m.is_forwarded,
                "raw_source": m.raw_source,
            }
        )
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(filepath: Path, messages: list[Message]) -> None:
    fieldnames = [
        "id",
        "channel",
        "date",
        "author",
        "text",
        "media_urls",
        "reactions",
        "is_forwarded",
        "raw_source",
    ]
    with filepath.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for m in messages:
            writer.writerow(
                {
                    "id": m.id,
                    "channel": m.channel,
                    "date": m.date.isoformat(),
                    "author": m.author or "",
                    "text": m.text,
                    "media_urls": "|".join(m.media_urls),
                    "reactions": json.dumps(m.reactions, ensure_ascii=False) if m.reactions else "",
                    "is_forwarded": m.is_forwarded,
                    "raw_source": m.raw_source,
                }
            )


def _write_txt(filepath: Path, messages: list[Message]) -> None:
    """Write messages as a plain-text file separated by blank lines."""
    lines: list[str] = []
    for m in messages:
        lines.append(f"--- Message #{m.id} ---")
        lines.append(f"Channel: {m.channel}")
        lines.append(f"Date:    {m.date.isoformat()}")
        lines.append(f"Author:  {m.author or '—'}")
        if m.media_urls:
            lines.append(f"Media:   {', '.join(m.media_urls)}")
        if m.reactions:
            reactions_str = ", ".join(f"{k}: {v}" for k, v in m.reactions.items())
            lines.append(f"Reactions: {reactions_str}")
        if m.is_forwarded:
            lines.append("Forwarded: yes")
        lines.append("")
        lines.append(m.text)
        lines.append("")  # blank line separator
    filepath.write_text("\n".join(lines), encoding="utf-8")


def _write_sqlite(db_path: Path, messages: list[Message]) -> None:
    """Delegate to the sqlite writer module."""
    from tgparser.storage.sqlite import save_messages as _sqlite_save
    _sqlite_save(db_path, messages)


def _save_last_message_id(output_dir: Path, channel_name: str, last_id: int) -> None:
    """Persist the last saved message id for incremental parsing."""
    safe_channel = channel_name.lstrip("@").replace("/", "_")
    state_file = output_dir / f"{safe_channel}_state.json"
    state_file.write_text(
        json.dumps({"last_message_id": last_id}, indent=2),
        encoding="utf-8",
    )
