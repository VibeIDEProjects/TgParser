"""Storage writers — JSON, CSV, TXT, SQLite."""

from tgparser.storage.writer import (
    OutputFormat,
    SUPPORTED_FILE_FORMATS,
    SUPPORTED_OUTPUT_FORMATS,
    get_last_message_id,
    save_messages,
    save_messages_incremental,
)

__all__ = [
    "save_messages",
    "save_messages_incremental",
    "get_last_message_id",
    "OutputFormat",
    "SUPPORTED_OUTPUT_FORMATS",
    "SUPPORTED_FILE_FORMATS",
]
