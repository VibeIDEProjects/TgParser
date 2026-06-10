#!/usr/bin/env python
"""Cross-platform launcher for the TgParser Textual GUI.

This script is the entry point invoked by ``bin/run_gui.sh`` (Linux/macOS)
and ``bin/run_gui.bat`` (Windows).  It:

1. Locates the project root (the directory that contains ``src/``).
2. Prefers the project's local virtual environment (``.venv``) when present.
3. Falls back to the active Python interpreter if no venv is found.
4. Runs ``python -m tgparser.gui``.

Usage:
    python bin/run_gui.py
    bin/run_gui.py            # if executable bit is set
    bin/run_gui.sh            # Linux/macOS
    bin\\run_gui.bat          # Windows
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path


def _project_root() -> Path:
    """Return the absolute path to the project root (parent of ``bin/``)."""
    return Path(__file__).resolve().parent.parent


def _resolve_python(project_root: Path) -> str:
    """Return the path to the Python interpreter to use.

    Preference order:
    1. ``.venv`` located inside the project root.
    2. The interpreter that is currently running this script.
    """
    venv = project_root / ".venv"
    if venv.is_dir():
        if os.name == "nt":
            candidate = venv / "Scripts" / "python.exe"
        else:
            candidate = venv / "bin" / "python"
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def main() -> int:
    project_root = _project_root()
    python = _resolve_python(project_root)

    # Make ``import tgparser`` work regardless of where the user is
    # invoking the script from.
    src_dir = project_root / "src"
    if not src_dir.is_dir():
        print(f"ERROR: {src_dir} does not exist. Are you running from the project root?",
              file=sys.stderr)
        return 2

    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(src_dir) + (os.pathsep + existing_pp if existing_pp else "")
    )

    cmd = [python, "-m", "tgparser.gui"]
    print(f"[run_gui] {' '.join(cmd)}  (cwd={project_root})")
    return subprocess.call(cmd, cwd=str(project_root), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
