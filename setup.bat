@echo off
setlocal
set ERRFLAG=0

rem python version 3.10
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements-dev.txt || set ERRFLAG=1

if %ERRFLAG%==1 (
    echo.
    echo Stopped due to errors. Press Enter to close.
    pause >nul
)
endlocal