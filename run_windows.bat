@echo off
setlocal
cd /d "%~dp0"

echo [MDT] Manufacturing Digital Twin V1.0
if not exist ".venv\Scripts\python.exe" (
  echo [MDT] Creating Windows virtual environment...
  py -3.14 -m venv .venv 2>nul || python -m venv .venv || exit /b 1
)
call .venv\Scripts\activate.bat || exit /b 1
python -m pip install -r requirements-windows-tested.txt || exit /b 1
python -m pip install -e . --no-deps || exit /b 1
python scripts\static_gate.py || exit /b 1
python scripts\frontend_check.py || exit /b 1
python scripts\launch_workspace.py
exit /b %errorlevel%
