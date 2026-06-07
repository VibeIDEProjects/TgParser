#!/usr/bin/env python3
"""Build a standalone executable for TgParser using PyInstaller.

Usage:
    python build_standalone.py          # one-file executable
    python build_standalone.py --onedir # one-directory bundle

Requires PyInstaller installed (pip install pyinstaller).
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Build TgParser standalone executable")
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="Build as one-directory bundle (faster startup, larger footprint)",
    )
    args = parser.parse_args()

    dist_dir = "dist"
    spec_file = "tgparser.spec"

    # Clean previous build artifacts
    for d in ["build", dist_dir]:
        if os.path.isdir(d):
            shutil.rmtree(d)
    for f in [spec_file]:
        if os.path.isfile(f):
            os.unlink(f)

    # Determine the entry point
    entry_point = "src/tgparser/gui/__main__.py"
    if not os.path.isfile(entry_point):
        # Fallback to cli
        entry_point = "src/tgparser/cli.py"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=TgParser",
        "--icon=",  # No icon yet
        f"--distpath={dist_dir}",
        "--noconfirm",
        "--clean",
    ]

    if args.onedir:
        cmd.append("--onedir")
    else:
        cmd.append("--onefile")

    # Common hidden imports for Telethon and dependencies
    hidden_imports = [
        "tgparser",
        "tgparser.cli",
        "tgparser.gui",
        "tgparser.gui.app",
        "tgparser.gui.screens",
        "tgparser.gui.screens.main_screen",
        "tgparser.gui.screens.auth_screen",
        "tgparser.gui.screens.parse_screen",
        "tgparser.gui.screens.result_screen",
        "tgparser.web",
        "tgparser.web.web_parser",
        "tgparser.web.web_auth",
        "tgparser.mtproto",
        "tgparser.mtproto.mtproto_auth",
        "tgparser.mtproto.mtproto_parser",
        "tgparser.storage",
        "tgparser.storage.database",
        "tgparser.storage.exporter",
        "tgparser.utils",
        "tgparser.utils.logger",
        "tgparser.utils.config",
        # Telethon dependencies
        "cryptg",
        "PIL",
        "lottie",
        "emoji",
        "aiofiles",
        "qrcode",  # used by web auth
    ]

    for mod in hidden_imports:
        cmd.extend(["--hidden-import", mod])

    # Add data files (config templates, etc.)
    # cmd.extend(["--add-data", "src/tgparser/config:tgparser/config"])

    cmd.append(entry_point)

    print("Running PyInstaller...")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)

    print("\nBuild complete!")
    if args.onedir:
        print(f"Executable is in: {dist_dir}/TgParser/")
    else:
        print(f"Executable is: {dist_dir}/TgParser.exe (Windows) or {dist_dir}/TgParser (Linux/macOS)")


if __name__ == "__main__":
    main()
