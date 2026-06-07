#!/usr/bin/env python3
"""Build and publish TgParser to PyPI.

Usage:
    python publish_to_pypi.py            # dry-run (show what would be uploaded)
    python publish_to_pypi.py --upload   # actually upload to PyPI
    python publish_to_pypi.py --test     # upload to TestPyPI first

Prerequisites:
    - pip install build twine
    - PyPI account with API token stored in ~/.pypirc or keyring
    - Or set env variable TWINE_USERNAME / TWINE_PASSWORD
"""

import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Publish TgParser to PyPI")
    parser.add_argument("--upload", action="store_true", help="Actually upload (default: dry-run)")
    parser.add_argument("--test", action="store_true", help="Upload to TestPyPI instead of PyPI")
    parser.add_argument("--repository", default="pypi", choices=["pypi", "testpypi"], help="Target repository")
    args = parser.parse_args()

    # Determine target
    if args.test:
        repository = "testpypi"
    elif args.repository:
        repository = args.repository
    else:
        repository = "pypi"

    # 1. Build
    print("Building package...")
    subprocess.run([sys.executable, "-m", "build"], check=True)

    # 2. Find dist files
    dist_dir = "dist"
    files = sorted(os.listdir(dist_dir))
    print(f"Files to upload: {files}")

    if not args.upload:
        print("\nThis was a dry-run. Use --upload to actually publish.")
        return

    # 3. Upload
    print(f"Uploading to {repository}...")
    cmd = [sys.executable, "-m", "twine", "upload", f"--repository={repository}"]
    cmd.extend(f"{dist_dir}/{f}" for f in files)
    subprocess.run(cmd, check=True)

    print("\nDone!")


if __name__ == "__main__":
    main()
