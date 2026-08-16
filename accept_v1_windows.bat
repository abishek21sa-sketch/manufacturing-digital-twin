@echo off
setlocal
cd /d "%~dp0"
echo [MDT] Final V1.0 Windows acceptance - version 1.0.0
if not exist ".venv\Scripts\python.exe" (
  py -3.14 -m venv .venv 2>nul || python -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail
python -m pip install -r requirements-windows-tested.txt || goto :fail
python -m pip install -e . --no-deps || goto :fail

rem Fail fast on local contamination, missing Gemini configuration, Gurobi
rem license problems, or a busy workspace port BEFORE any long test suite.
python scripts\public_release_check.py || goto :fail
python scripts\windows_preflight.py || goto :fail

rem External/Windows-specific gates run before the 71+ test release suite so
rem a provider/license/startup issue cannot waste a full computational cycle.
python scripts\gemini_acceptance.py || goto :fail
python scripts\gurobi_acceptance.py || goto :fail
python scripts\windows_v1_acceptance.py || goto :fail
python scripts\launch_workspace.py --no-browser --exit-after-ready || goto :fail

rem release_check itself now runs public/runtime smoke before the isolated suite.
python scripts\release_check.py || goto :fail

echo WINDOWS_V1_ACCEPTANCE=PASS
exit /b 0
:fail
echo WINDOWS_V1_ACCEPTANCE=FAIL
exit /b 1
