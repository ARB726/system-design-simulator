@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup instructions are in fullstack\README.md.
  echo Create a Python virtual environment and install the backend requirements.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" tools\run_fullstack.py
pause
