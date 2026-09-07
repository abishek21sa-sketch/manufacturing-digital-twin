@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if "%MDT_PORT%"=="" set "MDT_PORT=8010"

echo [MDT DEMO] Deterministic portfolio scenario - Python 3.14
where py >nul 2>nul || exit /b 2
py -3.14 -c "import sys; assert sys.version_info[:2]==(3,14); print(sys.version)" || exit /b 3

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,14) else 1)" >nul 2>nul
  if errorlevel 1 rmdir /s /q .venv
)
if not exist ".venv\Scripts\python.exe" py -3.14 -m venv .venv || exit /b 1
set "PY=%CD%\.venv\Scripts\python.exe"
set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
set "OMP_NUM_THREADS=1"
set "OPENBLAS_NUM_THREADS=1"
set "MKL_NUM_THREADS=1"
set "MDT_DATABASE_URL=sqlite:///runtime/mdt_demo.db"

"%PY%" -m pip install --upgrade pip setuptools wheel || exit /b 1
"%PY%" -m pip install -r requirements-windows-tested.txt || exit /b 1
"%PY%" -m pip install -e . --no-deps --no-build-isolation || exit /b 1
"%PY%" -I scripts\windows_native_runtime_smoke.py || exit /b 1
"%PY%" scripts\portfolio_demo.py --reset --build-evidence || exit /b 1
"%PY%" scripts\launch_workspace.py --demo
exit /b %errorlevel%
