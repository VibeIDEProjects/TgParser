@echo off
REM Launch the TgParser Textual GUI on Windows.
REM
REM Usage:
REM   bin\run_gui.bat
REM
REM Delegates to bin\run_gui.py which handles venv detection and
REM PYTHONPATH setup in a cross-platform way.

setlocal

set "SCRIPT_DIR=%~dp0"
python "%SCRIPT_DIR%run_gui.py" %*

endlocal
