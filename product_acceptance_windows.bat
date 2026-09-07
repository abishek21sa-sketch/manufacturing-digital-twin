@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo [MDT] Product Runtime acceptance - Python 3.14
where py >nul 2>nul || exit /b 2
py -3.14 -c "import sys; assert sys.version_info[:2]==(3,14); print(sys.version)" || exit /b 3
if not exist ".venv\Scripts\python.exe" py -3.14 -m venv .venv || exit /b 1
set "PY=%CD%\.venv\Scripts\python.exe"
set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
set "OMP_NUM_THREADS=1"
set "OPENBLAS_NUM_THREADS=1"
set "MKL_NUM_THREADS=1"
set "MDT_DATABASE_URL=sqlite:///runtime/mdt_product_acceptance.db"

"%PY%" -m pip install --upgrade pip setuptools wheel || exit /b 1
"%PY%" -m pip install -r requirements-windows-tested.txt || exit /b 1
"%PY%" -m pip install -e . --no-deps --no-build-isolation || exit /b 1
"%PY%" -I scripts\windows_native_runtime_smoke.py || exit /b 1
"%PY%" scripts\product_runtime_acceptance.py || exit /b 1
exit /b 0
