@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Install Python 3.12 or 3.13 x64, or use the self-contained installer.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" scripts\check_runtime.py
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 (
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" scripts\check_runtime.py
  if errorlevel 1 (
    echo Runtime validation failed. See the dependency messages above.
    pause
    exit /b 1
  )
)
start "ChessStream PGN Recorder" ".venv\Scripts\pythonw.exe" -m chessstream
