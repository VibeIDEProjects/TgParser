"""Quick parse smoke-test."""
import sys

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from tgparser.parsers.web_parser import WebParser
from tgparser.storage.writer import save_messages

parser = WebParser()
print("Starting parse, limit=3...", flush=True)
messages = parser.parse(
    channel_url="https://web.telegram.org/a/#-1003929682471",
    limit=3,
)
print(f"GOT {len(messages)} messages", flush=True)
for m in messages:
    print("---")
    print(repr(m))

# Export as markdown + save state
fp = save_messages(
    messages,
    output_dir=".tgparser_test_output",
    channel_name="точка_фарма",
    fmt="md",
)
print(f"\nExported to: {fp}")
print("===DONE===")
