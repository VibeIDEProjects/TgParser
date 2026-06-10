"""Dump all def lines from web_auth.py."""
import sys
import io

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

path = r"d:\Projects\VibeCode\VibeIDEProjects\projects\TgParser\src\tgparser\auth\web_auth.py"
with open(path, encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "def " in line:
            sys.stdout.write(f"{i} {line}")
            sys.stdout.flush()
print("---END---", flush=True)
