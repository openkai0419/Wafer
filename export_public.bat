@echo off
setlocal

set SRC=F:\codes\NAI_image_viewer
set DST=F:\codes\Wafer
set ERR=0

if exist "%DST%" (
    echo Cleaning %DST% ...
    for /d %%d in ("%DST%\*") do (
        if /i not "%%~nxd"==".git" rd /s /q "%%d"
    )
    for %%f in ("%DST%\*") do del /q "%%f"
)

set COMMON_XD=/XD __pycache__ .pytest_cache .prototypes .packages .shared_packages .venv venv env build dist .eggs
set COMMON_XF=/XF *.pyc *.pyo *.pyd *.db *.db-shm *.db-wal *.ini *.-workspace

if not exist "%DST%" mkdir "%DST%"

for %%f in (
    .gitignore
    main.py
    main.spec
    pyproject.toml
    requirements.txt
    requirements-dev.txt
    setup.bat
    build.bat
    audit.bat
) do (
    if exist "%SRC%\%%f" copy /y "%SRC%\%%f" "%DST%\" >nul
)

robocopy "%SRC%\wafer"       "%DST%\wafer"       /E /NP %COMMON_XD% %COMMON_XF%
if %ERRORLEVEL% GEQ 8 set ERR=%ERRORLEVEL%

robocopy "%SRC%\extensions"  "%DST%\extensions"   /E /NP %COMMON_XD% /XD lib %COMMON_XF%
if %ERRORLEVEL% GEQ 8 set ERR=%ERRORLEVEL%

robocopy "%SRC%\tests"       "%DST%\tests"        /E /NP %COMMON_XD% %COMMON_XF%
if %ERRORLEVEL% GEQ 8 set ERR=%ERRORLEVEL%

robocopy "%SRC%\_resources"  "%DST%\_resources"    /E /NP %COMMON_XD% %COMMON_XF%
if %ERRORLEVEL% GEQ 8 set ERR=%ERRORLEVEL%

if %ERR% GEQ 8 (
    echo ERROR: robocopy failed with exit code %ERR%
    exit /b %ERR%
)

echo.
echo Export complete: %DST%
