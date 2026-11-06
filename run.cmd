@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "editor_port=%~1"
if not defined editor_port set "editor_port=8778"

if not exist "config.local.json" (
  call "%~dp0setup.cmd"
  if errorlevel 1 exit /b 1
  echo.
  echo Set the data_rom path in config.local.json, then run this file again.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  call "%~dp0setup.cmd"
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -c "import PIL, fontTools, arabic_reshaper, bidi" >nul 2>&1
if errorlevel 1 (
  echo Python packages are missing. Run setup.cmd, then try again. 1>&2
  exit /b 1
)

echo Open http://127.0.0.1:%editor_port%/ in your browser. Press Ctrl+C to stop the editor.
".venv\Scripts\python.exe" "app.py" --config "config.local.json" --port "%editor_port%"
exit /b %ERRORLEVEL%
