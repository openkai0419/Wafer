@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "USERDATA=%LOCALAPPDATA%\Wafer"
set "DRY_RUN=0"
set "YES=0"
set "MODE="

:parse_args
if "%~1"=="" goto :check_mode
if /i "%~1"=="--repo" set "MODE=repo" & shift & goto :parse_args
if /i "%~1"=="--userdata" set "MODE=userdata" & shift & goto :parse_args
if /i "%~1"=="--all" set "MODE=all" & shift & goto :parse_args
if /i "%~1"=="--dry-run" set "DRY_RUN=1" & shift & goto :parse_args
if /i "%~1"=="--yes" set "YES=1" & shift & goto :parse_args
if /i "%~1"=="-y" set "YES=1" & shift & goto :parse_args
echo Unknown option: %~1
goto :usage

:check_mode
if "%MODE%"=="" goto :interactive

if "%MODE%"=="repo" goto :run_repo
if "%MODE%"=="userdata" goto :run_userdata
if "%MODE%"=="all" goto :run_all
goto :usage

:interactive
echo.
echo   Wafer Cleanup
echo   =============
echo.
echo   [1] Clean repository artifacts
echo       (extensions/lib, .packages, __pycache__, build, dist, .temp, etc.)
echo.
echo   [2] Clean user data
echo       (%USERDATA%)
echo.
echo   [3] Clean all (repository + user data)
echo.
echo   [0] Cancel
echo.
set /p "CHOICE=  Select [0-3]: "
if "%CHOICE%"=="1" goto :run_repo
if "%CHOICE%"=="2" goto :run_userdata
if "%CHOICE%"=="3" goto :run_all
if "%CHOICE%"=="0" goto :done
echo Invalid choice.
goto :interactive

:run_all
call :do_repo
call :do_userdata
goto :confirm_and_execute

:run_repo
call :do_repo
goto :confirm_and_execute

:run_userdata
call :do_userdata
goto :confirm_and_execute

:do_repo
set "REPO_TARGETS="
set "REPO_COUNT=0"

for /d %%D in ("%ROOT%\extensions\*") do (
    if exist "%%D\lib" (
        set /a REPO_COUNT+=1
        set "REPO_TARGETS=!REPO_TARGETS! "%%D\lib""
        echo   [repo] %%~nxD\lib
    )
    if exist "%%D\.packages" (
        set /a REPO_COUNT+=1
        set "REPO_TARGETS=!REPO_TARGETS! "%%D\.packages""
        echo   [repo] %%~nxD\.packages
    )
)
if exist "%ROOT%\extensions\.shared_packages" (
    set /a REPO_COUNT+=1
    set "REPO_TARGETS=!REPO_TARGETS! "%ROOT%\extensions\.shared_packages""
    echo   [repo] extensions\.shared_packages
)

for %%D in (build dist .temp .pytest_cache .ruff_cache) do (
    if exist "%ROOT%\%%D" (
        set /a REPO_COUNT+=1
        set "REPO_TARGETS=!REPO_TARGETS! "%ROOT%\%%D""
        echo   [repo] %%D
    )
)

if exist "%ROOT%\__pycache__" (
    set /a REPO_COUNT+=1
    set "REPO_TARGETS=!REPO_TARGETS! "%ROOT%\__pycache__""
    echo   [repo] __pycache__
)
for %%S in (wafer extensions tests tests-unit scripts) do (
    if exist "%ROOT%\%%S" (
        call :scan_pycache "%ROOT%\%%S"
    )
)

for %%P in (*.db *.db-shm *.db-wal *.ini) do (
    if exist "%ROOT%\%%P" (
        set /a REPO_COUNT+=1
        set "REPO_TARGETS=!REPO_TARGETS! "%ROOT%\%%P""
        echo   [repo] %%P
    )
)

if %REPO_COUNT%==0 (
    echo   [repo] Nothing to clean.
)
goto :eof

:scan_pycache
for /d /r %1 %%D in (__pycache__) do (
    set "REL=%%D"
    set "REL=!REL:%ROOT%\=!"
    set /a REPO_COUNT+=1
    set "REPO_TARGETS=!REPO_TARGETS! "%%D""
    echo   [repo] !REL!
)
goto :eof

:do_userdata
set "UD_EXISTS=0"
if exist "%USERDATA%" (
    set "UD_EXISTS=1"
    echo   [userdata] %USERDATA%
) else (
    echo   [userdata] Not found: %USERDATA%
)
goto :eof

:confirm_and_execute
echo.

if %REPO_COUNT% gtr 0 set "HAS_TARGETS=1"
if %UD_EXISTS%==1 set "HAS_TARGETS=1"

if not defined HAS_TARGETS (
    echo   Nothing to clean.
    goto :done
)

if %DRY_RUN%==1 (
    echo   [dry-run] No files were deleted.
    goto :done
)

if %YES%==1 goto :execute

set /p "CONFIRM=  Proceed with deletion? [y/N]: "
if /i not "%CONFIRM%"=="y" (
    echo   Cancelled.
    goto :done
)

:execute
echo.

if %REPO_COUNT% gtr 0 (
    for %%T in (%REPO_TARGETS%) do (
        if exist %%T (
            if exist %%T\* (
                rd /s /q %%T 2>nul
            ) else (
                del /q %%T 2>nul
            )
        )
    )
    echo   [repo] Removed %REPO_COUNT% item(s).
)

if %UD_EXISTS%==1 (
    rd /s /q "%USERDATA%" 2>nul
    echo   [userdata] Removed: %USERDATA%
)

echo.
echo   Done.
goto :done

:usage
echo.
echo   Usage: cleanup.bat [options]
echo.
echo   Options:
echo     --repo       Remove repository artifacts
echo     --userdata   Remove user data (%LOCALAPPDATA%\Wafer)
echo     --all        Remove both
echo     --dry-run    Show targets without deleting
echo     --yes, -y    Skip confirmation prompt
echo.
echo   No arguments: interactive menu
echo.

:done
if %YES%==0 pause
endlocal
