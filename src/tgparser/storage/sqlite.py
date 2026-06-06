"""SQLite storage for parsed messages — optional dependency (sqlite3 built-in)."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from tgparser.models.message import Message

logger = logging.getLogger("tgparser")

# SQLite table schema
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER NOT NULL,
    channel     TEXT NOT NULL,
    date        TEXT NOT NULL,
    author      TEXT,
    text        TEXT NOT NULL,
    media_urls  TEXT,          -- JSON array stored as text
    reactions   TEXT,          -- JSON object stored as text
    is_forwarded INTEGER DEFAULT 0,
    raw_source  TEXT DEFAULT 'unknown',
    saved_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (id, channel)
);
"""

CREATE_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    channel TEXT PRIMARY KEY,
    last_message_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _ensure_tables(db: sqlite3.Connection) -> None:
    db.execute(CREATE_TABLE_SQL)
    db.execute(CREATE_METADATA_SQL)
    db.commit()


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a connection and ensure tables exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    _ensure_tables(db)
    return db


def save_messages(db_path: Path, messages: list[Message]) -> None:
    """Insert *messages* into the SQLite database, ignoring duplicates (id+channel)."""
    db = _get_connection(db_path)
    try:
        for m in messages:
            db.execute(
                """
                INSERT OR IGNORE INTO messages
                    (id, channel, date, author, text, media_urls, reactions,
                     is_forwarded, raw_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m.id,
                    m.channel,
                    m.date.isoformat(),
                    m.author,
                    m.text,
                    json.dumps(m.media_urls, ensure_ascii=False),
                    json.dumps(m.reactions, ensure_ascii=False) if m.reactions else None,
                    int(m.is_forwarded),
                    m.raw_source,
                ),
            )
        db.commit()
    finally:
        db.close()


def get_last_message_id(db_path: Path, channel: str) -> int | None:
    """Return the highest message id stored for *channel*, or ``None``."""
    db = _get_connection(db_path)
    try:
        row = db.execute(
            "SELECT last_message_id FROM metadata WHERE channel = ?", (channel,)
        ).fetchone()
        if row is not None:
            return row["last_message_id"]
        # Fallback: scan messages table
        row = db.execute(
            "SELECT MAX(id) AS max_id FROM messages WHERE channel = ?", (channel,)
        ).fetchone()
        return row["max_id"] if row and row["max_id"] is not None else None
    finally:
        db.close()


def update_last_message_id(db_path: Path, channel: str, last_id: int) -> None:
    """Update (or insert) the last message id metadata for *channel*."""
    db = _get_connection(db_path)
    try:
        db.execute(
            """
            INSERT INTO metadata (channel, last_message_id, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(channel) DO UPDATE SET
                last_message_id = excluded.last_message_id,
                updated_at = excluded.updated_at
            """,
            (channel, last_id),
        )
        db.commit()
    finally:
        db.close()
