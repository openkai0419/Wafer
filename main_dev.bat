@echo off
setlocal
rem set "WAFER_DEV=1"
set "WAFER_MEMWATCH=trace"
pushd "%~dp0"
call main.bat %*
set "EXITCODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXITCODE%