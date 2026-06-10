"""Quick incremental-parse smoke-test."""
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from tgparser.config import resolve_path
from tgparser.models.message import Message
from tgparser.storage.writer import (
    get_seen_message_ids,
    save_messages_incremental,
)

out = resolve_path("output_dir")
print(f"Output dir: {out}", flush=True)

m1 = Message(
    id=433460709,
    channel="точка_фарма",
    date=datetime(2026, 6, 8, 18, 28, tzinfo=UTC),
    text="Уже известное сообщение",
    media_urls=["https://www.python.org"],
    raw_source="web",
)
m2 = Message(
    id=999999999,
    channel="точка_фарма",
    date=datetime(2026, 6, 8, 20, 0, tzinfo=UTC),
    text="Совершенно новое сообщение!",
    media_urls=["https://example.com"],
    raw_source="web",
)

# Round 1
fp = save_messages_incremental([m1], out, "точка_фарма", fmt="md")
print(f"Round 1 -> {fp}", flush=True)
print(f"  seen: {sorted(get_seen_message_ids(out, 'точка_фарма'))}", flush=True)

# Round 2
fp = save_messages_incremental([m1, m2], out, "точка_фарма", fmt="md")
print(f"Round 2 -> {fp}", flush=True)
print(f"  seen: {sorted(get_seen_message_ids(out, 'точка_фарма'))}", flush=True)

# Round 3
fp = save_messages_incremental([m1, m2], out, "точка_фарма", fmt="md")
print(f"Round 3 (no new) -> {fp}", flush=True)
print(f"  seen: {sorted(get_seen_message_ids(out, 'точка_фарма'))}", flush=True)

print("\n=== Combined file ===", flush=True)
combined = next(out.glob("точка_фарма_all.md"))
print(combined.read_text(encoding="utf-8")[:1000], flush=True)

print("\n=== State file ===", flush=True)
state = next(out.glob("точка_фарма_state.json"))
print(state.read_text(encoding="utf-8"), flush=True)
