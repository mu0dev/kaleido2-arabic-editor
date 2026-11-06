@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "editor_dir=%~dp0"
set "editor_port=%~1"
if not defined editor_port set "editor_port=8778"

if not exist "%editor_dir%config.local.json" (
  echo Missing config.local.json. Copy config.example.json to config.local.json and set your local paths. 1>&2
  exit /b 1
)

echo Open http://127.0.0.1:%editor_port%/ in your browser. Press Ctrl+C to stop the editor.

if exist "%editor_dir%.venv\Scripts\python.exe" goto venv
where py >nul 2>&1
if not errorlevel 1 goto pylauncher
where python >nul 2>&1
if not errorlevel 1 goto python

echo Python 3 was not found. Install Python 3.10 or newer, or create .venv in this directory. 1>&2
exit /b 1

:venv
"%editor_dir%.venv\Scripts\python.exe" "%editor_dir%app.py" --config "%editor_dir%config.local.json" --port "%editor_port%"
exit /b %ERRORLEVEL%

:pylauncher
py -3 "%editor_dir%app.py" --config "%editor_dir%config.local.json" --port "%editor_port%"
exit /b %ERRORLEVEL%

:python
python "%editor_dir%app.py" --config "%editor_dir%config.local.json" --port "%editor_port%"
exit /b %ERRORLEVEL%
