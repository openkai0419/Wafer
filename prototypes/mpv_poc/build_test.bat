@echo off
chcp 65001 >nul
setlocal

echo === mpv PyInstaller Build Test ===
echo.

cd /d "%~dp0"

if not exist "libmpv-2.dll" (
    echo [ERROR] libmpv-2.dll not found in %~dp0
    echo Please place libmpv-2.dll here first.
    echo Download from: https://sourceforge.net/projects/mpv-player-windows/files/libmpv/
    goto END
)

echo [1/3] Building with PyInstaller...
pyinstaller --noconfirm --clean test_build.spec
if errorlevel 1 (
    echo [ERROR] Build failed.
    goto END
)

echo.
echo [2/3] Checking dist contents...
if exist "dist\mpv_test\libmpv-2.dll" (
    echo [OK] libmpv-2.dll found in dist
) else (
    echo [NG] libmpv-2.dll NOT found in dist
    goto END
)

if exist "dist\mpv_test\mpv_test.exe" (
    echo [OK] mpv_test.exe found in dist
) else (
    echo [NG] mpv_test.exe NOT found in dist
    goto END
)

echo.
echo [3/3] Launching test app...
echo (Close the window to end the test)
start "" "dist\mpv_test\mpv_test.exe"

echo.
echo === Build test complete ===

:END
echo.
pause
