@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "USERDATA=%LOCALAPPDATA%\Wafer"
set "DRY_RUN=0"
set "YES=0"
set "MODE="
set "REPO_COUNT=0"
set "UD_EXISTS=0"

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
echo(
echo   Wafer Cleanup
echo   =============
echo(
echo   [1] Clean repository artifacts
echo       (extensions/lib, .packages, __pycache__, build, dist, .temp, etc.)
echo(
echo   [2] Clean user data
echo       (%USERDATA%)
echo(
echo   [3] Clean all (repository + user data)
echo(
echo   [0] Cancel
echo(
set /p "CHOICE=  Select [0-3]: "
if "%CHOICE%"=="1" goto :run_repo
if "%CHOICE%"=="2" goto :run_userdata
if "%CHOICE%"=="3" goto :run_all
if "%CHOICE%"=="0" goto :done
echo Invalid choice.
goto :interactive

:run_all
call :scan_repo
call :scan_userdata
goto :confirm

:run_repo
call :scan_repo
goto :confirm

:run_userdata
call :scan_userdata
goto :confirm

:scan_repo
set "REPO_COUNT=0"

for /d %%D in ("%ROOT%\extensions\*") do (
    if exist "%%D\lib" (
        set /a REPO_COUNT+=1
        echo   [repo] %%~nxD\lib
    )
    if exist "%%D\.packages" (
        set /a REPO_COUNT+=1
        echo   [repo] %%~nxD\.packages
    )
)
if exist "%ROOT%\extensions\.packages" (
    set /a REPO_COUNT+=1
    echo   [repo] extensions\.packages
)

for %%D in (build dist .temp .pytest_cache .ruff_cache) do (
    if exist "%ROOT%\%%D" (
        set /a REPO_COUNT+=1
        echo   [repo] %%D
    )
)

if exist "%ROOT%\__pycache__" (
    set /a REPO_COUNT+=1
    echo   [repo] __pycache__
)
for %%S in (wafer tests tests-unit scripts) do (
    if exist "%ROOT%\%%S" (
        call :count_pycache "%ROOT%\%%S"
    )
)

for %%P in (*.db *.db-shm *.db-wal *.ini) do (
    if exist "%ROOT%\%%P" (
        set /a REPO_COUNT+=1
        echo   [repo] %%P
    )
)

if %REPO_COUNT%==0 (
    echo   [repo] Nothing to clean.
)
goto :eof

:count_pycache
for /d /r %1 %%D in (__pycache__) do (
    set "_skip=0"
    for %%P in ("%%~dpD.") do if /i "%%~nxP"=="__pycache__" set "_skip=1"
    if !_skip!==0 (
        set "REL=%%D"
        set "REL=!REL:%ROOT%\=!"
        set /a REPO_COUNT+=1
        echo   [repo] !REL!
    )
)
goto :eof

:scan_userdata
set "UD_EXISTS=0"
if exist "%USERDATA%" (
    set "UD_EXISTS=1"
    echo   [userdata] %USERDATA%
) else (
    echo   [userdata] Not found: %USERDATA%
)
goto :eof

:confirm
echo(

set "HAS_TARGETS=0"
if %REPO_COUNT% gtr 0 set "HAS_TARGETS=1"
if %UD_EXISTS%==1 set "HAS_TARGETS=1"

if %HAS_TARGETS%==0 (
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
echo(

if %REPO_COUNT% gtr 0 (
    call :delete_repo
    echo   [repo] Removed !REPO_COUNT! item(s^).
)

if %UD_EXISTS%==1 (
    rd /s /q "%USERDATA%" 2>nul
    echo   [userdata] Removed: %USERDATA%
)

echo(
echo   Done.
goto :done

:delete_repo
for /d %%D in ("%ROOT%\extensions\*") do (
    if exist "%%D\lib" (
        call :rm "%%D\lib"
        echo     removed %%~nxD\lib
    )
    if exist "%%D\.packages" (
        call :rm "%%D\.packages"
        echo     removed %%~nxD\.packages
    )
)
if exist "%ROOT%\extensions\.packages" (
    call :rm "%ROOT%\extensions\.packages"
    echo     removed extensions\.packages
)

for %%D in (build dist .temp .pytest_cache .ruff_cache) do (
    if exist "%ROOT%\%%D" (
        call :rm "%ROOT%\%%D"
        echo     removed %%D
    )
)

if exist "%ROOT%\__pycache__" (
    call :rm "%ROOT%\__pycache__"
    echo     removed __pycache__
)
set "_PC_COUNT=0"
for %%S in (wafer tests tests-unit scripts) do (
    if exist "%ROOT%\%%S" call :rm_pycache "%ROOT%\%%S"
)
if !_PC_COUNT! gtr 0 echo     removed !_PC_COUNT! __pycache__ dirs

for %%P in (*.db *.db-shm *.db-wal *.ini) do (
    if exist "%ROOT%\%%P" (
        del /q "%ROOT%\%%P" 2>nul
        echo     removed %%P
    )
)
goto :eof

:rm_pycache
for /d /r %1 %%D in (__pycache__) do (
    set "_skip=0"
    for %%P in ("%%~dpD.") do if /i "%%~nxP"=="__pycache__" set "_skip=1"
    if !_skip!==0 (
        if exist "%%D" (
            rd /s /q "%%D" 2>nul
            set /a _PC_COUNT+=1
        )
    )
)
goto :eof

:rm
if exist %1 rd /s /q %1 2>nul
if exist %1 del /q %1 2>nul
goto :eof

:usage
echo(
echo   Usage: cleanup.bat [options]
echo(
echo   Options:
echo     --repo       Remove repository artifacts
echo     --userdata   Remove user data (%LOCALAPPDATA%\Wafer)
echo     --all        Remove both
echo     --dry-run    Show targets without deleting
echo     --yes, -y    Skip confirmation prompt
echo(
echo   No arguments: interactive menu
echo(

:done
pause
endlocal
