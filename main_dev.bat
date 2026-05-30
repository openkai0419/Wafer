@echo off
setlocal
set "WAFER_DEV=1"
pushd "%~dp0"
call main.bat %*
set "EXITCODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXITCODE%