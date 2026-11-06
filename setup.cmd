@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

call :setup
set "setup_exit=%errorlevel%"
echo.
if "%setup_exit%"=="0" (
  echo Setup finished successfully. You can close this window.
) else (
  echo Setup stopped with an error. Read the message above before closing this window. 1>&2
)
if /I not "%~1"=="--no-pause" pause
exit /b %setup_exit%

:setup
echo [1/4] Checking for Python 3.12 x64...
set "found_python="
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3.12 -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32)" >nul 2>&1
    if not errorlevel 1 (
      set "found_python=1"
      echo Creating .venv with the Python launcher...
      py -3.12 -m venv ".venv"
    )
  )
)

if not exist ".venv\Scripts\python.exe" (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32)" >nul 2>&1
    if not errorlevel 1 (
      set "found_python=1"
      echo Creating .venv with python.exe...
      python -m venv ".venv"
    )
  )
)

if not exist ".venv\Scripts\python.exe" (
  if defined found_python (
    echo ERROR: Python 3.12 x64 was found, but .venv could not be created. 1>&2
    echo Read the Python error above. Check that this folder is writable, then run setup.cmd again. 1>&2
  ) else (
    echo ERROR: .venv was not created because Python 3.12 x64 was not found. 1>&2
    echo Install Python 3.12 x64 from https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe 1>&2
    echo During installation, enable "Add python.exe to PATH" and "Python launcher". 1>&2
    echo Then reopen this folder and run setup.cmd again. 1>&2
  )
  exit /b 1
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32)" >nul 2>&1
if errorlevel 1 (
  echo ERROR: The existing .venv is not Python 3.12 x64. 1>&2
  echo Rename the .venv folder, then run setup.cmd again. 1>&2
  exit /b 1
)

echo [2/4] Installing Python packages...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 (
  echo ERROR: Python package installation failed. Check the error above and run setup.cmd again. 1>&2
  exit /b 1
)

echo [3/4] Downloading and checking build tools...
".venv\Scripts\python.exe" "bootstrap_tools.py"
if errorlevel 1 (
  echo ERROR: Build tool installation failed. Check the error above and run setup.cmd again. 1>&2
  exit /b 1
)

echo [4/4] Creating the local configuration...
if not exist "config.local.json" (
  copy /y "config.example.json" "config.local.json" >nul
  if errorlevel 1 (
    echo ERROR: Could not create config.local.json. 1>&2
    exit /b 1
  )
  echo Created config.local.json. Edit its game file paths before using run.cmd.
)

echo Setup complete. The .venv folder is ready. Edit config.local.json, then run run.cmd.
exit /b 0
