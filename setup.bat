@echo off
setlocal
set ERRFLAG=0

py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements-dev.txt || set ERRFLAG=1

if %ERRFLAG%==1 (
    echo.
    echo Stopped due to errors. Press Enter to close.
    pause >nul
)
endlocal