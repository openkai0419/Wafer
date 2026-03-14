@echo off
setlocal

set SRC=F:\codes\NAI_image_viewer
set DST=F:\codes\Public_image_viewer

if exist "%DST%" (
    echo Cleaning %DST% ...
    for /d %%d in ("%DST%\*") do (
        if /i not "%%~nxd"==".git" rd /s /q "%%d"
    )
    for %%f in ("%DST%\*") do del /q "%%f"
)

robocopy "%SRC%" "%DST%" /MIR /NP ^
  /XD .git .venv venv .env .pytest_cache .log .temp .packages .vscode .github .prototypes build dist __pycache__ lib ^
  /XF *.pyc *.pyo *.pyd *.db *.db-shm *.db-wal *.ini *.-workspace AGENTS.md README.md export_public.bat

if %ERRORLEVEL% GEQ 8 (
    echo ERROR: robocopy failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

echo.
echo Export complete: %DST%
