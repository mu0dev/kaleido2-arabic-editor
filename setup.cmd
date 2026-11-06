@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>&1
  if not errorlevel 1 py -3.12 -m venv ".venv"
)

if not exist ".venv\Scripts\python.exe" (
  where python >nul 2>&1
  if errorlevel 1 goto missing_python
  python -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))"
  if errorlevel 1 goto missing_python
  python -m venv ".venv"
)

if not exist ".venv\Scripts\python.exe" goto failed_venv

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))"
if errorlevel 1 (
  echo The existing .venv does not use Python 3.12. Remove .venv and run setup.cmd again. 1>&2
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 (
  echo Could not install Python packages. Check your internet connection and run setup.cmd again. 1>&2
  exit /b 1
)

".venv\Scripts\python.exe" "bootstrap_tools.py"
if errorlevel 1 (
  echo Could not install sdu.exe and EnterExtractor.exe. Run setup.cmd again. 1>&2
  exit /b 1
)

if not exist "config.local.json" (
  copy /y "config.example.json" "config.local.json" >nul
  if errorlevel 1 exit /b 1
  echo Created config.local.json. Edit its paths before using run.cmd.
)

echo Setup complete. Run run.cmd after configuring your game and tool paths.
exit /b 0

:missing_python
echo Python 3.12 was not found. Install it, then run setup.cmd again. 1>&2
exit /b 1

:failed_venv
echo Could not create the Python 3.12 environment. 1>&2
exit /b 1
