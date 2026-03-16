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

REM Default: standard preset (200 images, 5 videos, 30 animated)
REM Override: download_sample.bat --preset large
REM          download_sample.bat --images 500 --animated 50
.venv\Scripts\python.exe tests\dataset_downloader.py download --preset standard %*

echo.
echo === Status ===
.venv\Scripts\python.exe tests\dataset_downloader.py status

pause
