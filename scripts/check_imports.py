"""Check that every widget class used in `yield X(` is imported."""
import re

files = [
    "src/tgparser/gui/screens/result_screen.py",
    "src/tgparser/gui/screens/main_screen.py",
    "src/tgparser/gui/screens/auth_screen.py",
    "src/tgparser/gui/screens/parse_screen.py",
]

for f in files:
    src = open(f, encoding="utf-8").read()
    used = set(m.group(1) for m in re.finditer(r"\byield\s+(\w+)\(", src))
    imp_block = re.search(
        r"from textual\.widgets import \((.*?)\)", src, re.DOTALL
    )
    imported = set()
    if imp_block:
        for line in imp_block.group(1).split("\n"):
            m = re.match(r"\s*(\w+)", line)
            if m:
                imported.add(m.group(1))
    # Also check `textual.containers` etc.
    for pat in [r"from textual\.\w+ import \((.*?)\)"]:
        for m2 in re.finditer(pat, src, re.DOTALL):
            for line in m2.group(1).split("\n"):
                m = re.match(r"\s*(\w+)", line)
                if m:
                    imported.add(m.group(1))
    missing = used - imported
    print(f"{f}: missing={missing}")
