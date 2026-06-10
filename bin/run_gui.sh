#!/usr/bin/env bash
# Launch the TgParser Textual GUI on Linux/macOS.
#
# Usage:
#   bin/run_gui.sh
#
# This script delegates to ``bin/run_gui.py`` which handles venv detection
# and PYTHONPATH setup in a cross-platform way.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python "$SCRIPT_DIR/run_gui.py" "$@"
