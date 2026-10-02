@echo off
setlocal
set "CURRENT_DIR=%~dp0"
cd /d "%CURRENT_DIR%"
set "PYTHONPATH=%CURRENT_DIR%"
if not defined LONGFORGE_HOST set "LONGFORGE_HOST=127.0.0.1"
if not defined LONGFORGE_PORT set "LONGFORGE_PORT=8510"

if exist "%CURRENT_DIR%\.venv\Scripts\python.exe" (
  set "CMD=\"%CURRENT_DIR%\.venv\Scripts\python.exe\" -m streamlit"
) else (
  where uv >nul 2>nul
  if not errorlevel 1 set "CMD=uv run streamlit"
)
if not defined CMD set "CMD=streamlit"

echo ***** LongForge Workbench: http://%LONGFORGE_HOST%:%LONGFORGE_PORT% *****
%CMD% run .\longforge_app.py --server.address=%LONGFORGE_HOST% --server.port=%LONGFORGE_PORT% --browser.gatherUsageStats=False --client.toolbarMode=minimal
