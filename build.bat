@echo off
chcp 65001 >nul
setlocal
set ERRFLAG=0

set VENV=.venv\Scripts\activate.bat

set APPNAME=Wafer

REM Activate virtual environment
if exist "%VENV%" (
    call "%VENV%"
) else (
    echo Virtual environment not found: %VENV%
    set ERRFLAG=1
    goto END
)

REM Ensure PyInstaller is available
pip show pyinstaller >nul 2>&1 || (
    echo Installing PyInstaller...
    pip install pyinstaller || (
        echo Failed to install PyInstaller.
        set ERRFLAG=1
        goto END
    )
)

REM Remove previous build
echo Cleaning previous build...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

REM Build
pyinstaller --noconfirm --clean main.spec


REM Verify build result
if errorlevel 1 (
    echo Build failed.
    set ERRFLAG=1
    goto END
)

echo.
echo Build succeeded. See dist\%APPNAME%\main.exe

robocopy _resources dist\%APPNAME%\_resources /E
robocopy extensions  dist\%APPNAME%\extensions  /E /XD .packages .shared_packages __pycache__ lib

:END
if %ERRFLAG%==1 (
    echo.
    echo Stopped due to errors. Press Enter to close.
    pause >nul
)
endlocal
