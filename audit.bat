@echo off
setlocal enabledelayedexpansion
call .venv\Scripts\activate.bat

set ERRFLAG=0
set REQ_FILES=requirements.txt

for /d %%D in (extensions\*) do (
    if exist "%%D\requirements.txt" (
        set "REQ_FILES=!REQ_FILES! %%D\requirements.txt"
    )
)

echo === pip-audit: dependency vulnerability scan ===
echo.

for %%F in (!REQ_FILES!) do (
    echo --- %%F ---
    python -m pip_audit -r "%%F" --no-deps -f columns
    if errorlevel 1 set ERRFLAG=1
    echo.
)

for /f "usebackq delims=" %%P in (`python scripts\extract_dynamic_deps.py`) do (
    echo --- dynamic deps: %%P ---
    python -m pip_audit -r "%%P" --no-deps -f columns
    if errorlevel 1 set ERRFLAG=1
    echo.
)

if !ERRFLAG!==1 (
    echo.
    echo Vulnerabilities found. Press Enter to close.
    pause >nul
    exit /b 1
)

echo All clear.
endlocal
