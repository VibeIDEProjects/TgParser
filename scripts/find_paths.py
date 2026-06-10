"""Find file-system paths used by the parser."""
import re

files = [
    "src/tgparser/storage/writer.py",
    "src/tgparser/storage/sqlite.py",
    "src/tgparser/cli.py",
    "src/tgparser/config.py",
    "src/tgparser/auth/web_auth.py",
    "src/tgparser/gui/screens/result_screen.py",
]

for fn in files:
    src = open(fn, encoding="utf-8").read()
    print(f"\n=== {fn} ===")
    # Find Path() calls, 'data/', '.tgparser' and default settings
    for m in re.finditer(r"Path\([^)]+\)|data/[a-zA-Z_/.]+|~/\.tgparser[^\"'\)]*|default=\"[^\"]+\"|default=\"[^\"]+\"|get_setting\(\"[a-z_]+\"", src):
        line_no = src[:m.start()].count("\n") + 1
        print(f"  L{line_no}: {m.group(0)[:120]}")
