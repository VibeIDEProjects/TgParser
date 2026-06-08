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

OutputFormat = Literal["json", "csv", "txt", "md", "markdown", "sqlite"]
SUPPORTED_FILE_FORMATS: tuple[str, ...] = ("json", "csv", "txt", "md", "markdown")


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
        fmt: ``"json"``, ``"csv"``, ``"txt"``, ``"md"``/``"markdown"`` or ``"sqlite"``.
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
    ext = "md" if fmt in ("md", "markdown") else fmt
    filename = f"{safe_channel}_{ts}.{ext}"
    filepath = output_dir / filename

    if fmt == "json":
        _write_json(filepath, messages)
    elif fmt == "csv":
        _write_csv(filepath, messages)
    elif fmt == "txt":
        _write_txt(filepath, messages)
    elif fmt in ("md", "markdown"):
        _write_markdown(filepath, messages)
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
    """Incremental variant -- only appends messages whose ID we have never seen.

    For file-based formats (json/csv/txt/md) a single file ``<channel>_all.<fmt>``
    is maintained.  New messages are merged with previously stored ones and the
    combined set is re-written.  For sqlite the new messages are inserted
    directly with INSERT OR IGNORE on the primary key.

    The full set of already-seen IDs is persisted in a small state file
    ``<channel>_state.json`` (for file formats) or in the sqlite metadata
    table.  This is more robust than a single ``last_id`` watermark: even if
    a channel is re-indexed (e.g. the admin deletes and re-posts a message)
    we still avoid re-importing duplicates.
    """
    seen_ids = get_seen_message_ids(output_dir, channel_name, db_path)

    if seen_ids:
        new_messages = [m for m in messages if m.id not in seen_ids]
        if not new_messages:
            logger.info(
                "No new messages for '%s' (%d already known)",
                channel_name, len(seen_ids),
            )
            return None
        logger.info(
            "%d new messages (out of %d) for '%s'",
            len(new_messages), len(messages), channel_name,
        )
    else:
        new_messages = messages

    if fmt == "sqlite":
        if db_path is None:
            raise ValueError("db_path is required for sqlite format")
        _write_sqlite_merge(Path(db_path), new_messages)
        for m in new_messages:
            seen_ids.add(m.id)
        _persist_seen_ids(output_dir, channel_name, seen_ids, db_path)
        logger.info("Saved %d messages → sqlite:%s", len(new_messages), db_path)
        return None

    # File-based formats: merge with previous content (if any) and rewrite.
    existing = _read_existing_messages(output_dir, channel_name, fmt)
    combined = list(existing) + new_messages
    # Sort newest first by id (works for telegram IDs which are monotonic).
    combined.sort(key=lambda m: m.id, reverse=True)

    result = _write_combined(
        output_dir, channel_name, fmt, combined,
    )
    for m in new_messages:
        seen_ids.add(m.id)
    _persist_seen_ids(output_dir, channel_name, seen_ids, db_path)
    return result


def get_last_message_id(
    output_dir: str | Path,
    channel_name: str,
    db_path: str | Path | None = None,
) -> int | None:
    """Return the last (max) persisted message id, or ``None``.

    Convenience wrapper kept for backwards compatibility.  New code should
    call :func:`get_seen_message_ids` to access the full set of known IDs.
    """
    ids = get_seen_message_ids(output_dir, channel_name, db_path)
    return max(ids) if ids else None


def get_seen_message_ids(
    output_dir: str | Path,
    channel_name: str,
    db_path: str | Path | None = None,
) -> set[int]:
    """Return the set of message IDs we have already stored for *channel_name*."""
    if db_path is not None:
        from tgparser.storage.sqlite import get_seen_message_ids as _sqlite_seen
        return _sqlite_seen(Path(db_path), channel_name)

    state_file = _state_file(output_dir, channel_name)
    if not state_file.exists():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        ids = data.get("message_ids", [])
        # Back-compat: legacy state files only had "last_message_id".
        if not ids and data.get("last_message_id") is not None:
            return {int(data["last_message_id"])}
        return {int(x) for x in ids}
    except Exception as exc:
        logger.warning("Could not read state file %s: %s", state_file, exc)
        return set()


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


def _write_markdown(filepath: Path, messages: list[Message]) -> None:
    """Write messages as a human-readable Markdown document.

    Format::

        # Channel name

        _Exported: 2026-06-08 21:14:33 UTC — 56 messages_

        ---

        ## Message #876566362 — 2026-06-08 17:19 UTC

        *Author: You*

        Message body in plain text.  Links and media URLs are listed below.

        - [https://www.python.org/](https://www.python.org/)

        `forwarded`
    """
    if not messages:
        filepath.write_text("# (no messages)\n", encoding="utf-8")
        return

    channel_name = messages[0].channel or "channel"
    exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out: list[str] = []
    out.append(f"# {channel_name}")
    out.append("")
    out.append(
        f"_Exported: {exported_at} — {len(messages)} message"
        f"{'s' if len(messages) != 1 else ''}_"
    )
    out.append("")
    out.append("---")
    out.append("")

    for m in messages:
        out.append(f"## Message #{m.id} — {m.date.strftime('%Y-%m-%d %H:%M UTC')}")
        out.append("")
        if m.author:
            out.append(f"*Author: {m.author}*")
            out.append("")
        if m.is_forwarded:
            out.append("> ↪️ Forwarded")
            out.append("")
        # Body — keep original line breaks
        body = (m.text or "").rstrip()
        if body:
            out.append(body)
            out.append("")
        if m.media_urls:
            out.append("**Media:**")
            out.append("")
            for url in m.media_urls:
                out.append(f"- <{url}>")
            out.append("")
        if m.reactions:
            reactions = ", ".join(f"{k}: {v}" for k, v in m.reactions.items())
            out.append(f"**Reactions:** {reactions}")
            out.append("")
        out.append("---")
        out.append("")

    filepath.write_text("\n".join(out), encoding="utf-8")


def _write_sqlite(db_path: Path, messages: list[Message]) -> None:
    """Delegate to the sqlite writer module."""
    from tgparser.storage.sqlite import save_messages as _sqlite_save
    _sqlite_save(db_path, messages)


def _write_sqlite_merge(db_path: Path, messages: list[Message]) -> None:
    """Insert messages into SQLite, skipping duplicates by id."""
    from tgparser.storage.sqlite import insert_messages_ignore
    insert_messages_ignore(db_path, messages)


# ------------------------------------------------------------------
# Incremental state helpers
# ------------------------------------------------------------------


def _state_file(output_dir: str | Path, channel_name: str) -> Path:
    safe = channel_name.lstrip("@").replace("/", "_")
    return Path(output_dir) / f"{safe}_state.json"


def _combined_file(output_dir: str | Path, channel_name: str, fmt: str) -> Path:
    safe = channel_name.lstrip("@").replace("/", "_")
    ext = "md" if fmt in ("md", "markdown") else fmt
    return Path(output_dir) / f"{safe}_all.{ext}"


def _persist_seen_ids(
    output_dir: str | Path,
    channel_name: str,
    seen_ids: set[int],
    db_path: str | Path | None = None,
) -> None:
    """Write the seen-id set to a state file (or into sqlite metadata)."""
    if db_path is not None:
        from tgparser.storage.sqlite import set_seen_message_ids
        set_seen_message_ids(Path(db_path), channel_name, seen_ids)
        return
    state_file = _state_file(output_dir, channel_name)
    payload = {
        "last_message_id": max(seen_ids) if seen_ids else None,
        "message_ids": sorted(seen_ids),
        "count": len(seen_ids),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    state_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_existing_messages(
    output_dir: str | Path,
    channel_name: str,
    fmt: str,
) -> list[Message]:
    """Load the previously stored combined file (if it exists) into Message objects."""
    path = _combined_file(output_dir, channel_name, fmt)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return []

    if fmt == "json":
        data = json.loads(text)
        return [Message.from_dict(d) for d in data]
    if fmt == "csv":
        import io

        return [
            Message.from_dict(_csv_row_to_dict(row))
            for row in csv.DictReader(io.StringIO(text))
        ]
    # txt / md — best-effort: nothing structured enough to merge.
    return []


def _csv_row_to_dict(row: dict) -> dict:
    """Invert the CSV serialisation performed by :func:`_write_csv`."""
    media = row.get("media_urls") or ""
    reactions_raw = row.get("reactions") or ""
    return {
        "id": int(row["id"]),
        "channel": row.get("channel"),
        "date": row["date"],
        "author": row.get("author") or None,
        "text": row.get("text") or "",
        "media_urls": [u for u in media.split("|") if u],
        "reactions": json.loads(reactions_raw) if reactions_raw else None,
        "is_forwarded": row.get("is_forwarded", "False") in ("True", "true", "1"),
        "raw_source": row.get("raw_source", "web"),
    }


def _write_combined(
    output_dir: str | Path,
    channel_name: str,
    fmt: str,
    messages: list[Message],
) -> Path:
    """Write *messages* to the combined file for *channel_name*."""
    path = _combined_file(output_dir, channel_name, fmt)
    if fmt == "json":
        _write_json(path, messages)
    elif fmt == "csv":
        _write_csv(path, messages)
    elif fmt in ("md", "markdown"):
        _write_markdown(path, messages)
    elif fmt == "txt":
        _write_txt(path, messages)
    else:
        raise ValueError(f"Unsupported format for combined write: {fmt}")
    return path
