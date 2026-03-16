@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Run setup.bat first.
    pause
    exit /b 1
)

echo === Dataset Downloader ===
echo.
echo Destination: .sample\
echo.

.venv\Scripts\python.exe tests\dataset_downloader.py download %*

echo.
echo === Status ===
.venv\Scripts\python.exe tests\dataset_downloader.py status

pause
