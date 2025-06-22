@echo off
chcp 65001 >nul
setlocal
set ERRFLAG=0

set VENV=venv\Scripts\activate.bat

REM 仮想環境をアクティブ化
if exist "%VENV%" (
    call "%VENV%"
) else (
    echo ❌ 仮想環境が見つかりません: %VENV%
    set ERRFLAG=1
    goto END
)

REM PyInstallerがインストールされているか確認
pip show pyinstaller >nul 2>&1 || (
    echo Installing PyInstaller...
    pip install pyinstaller || (
        echo ❌ PyInstallerのインストールに失敗しました。
        set ERRFLAG=1
        goto END
    )
)

REM 古いビルドを削除
echo Cleaning previous build...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

REM ビルド分岐：main.spec があればそれを使う
REM 実行
pyinstaller --noconfirm --clean combined.spec


REM ビルド結果の確認
if errorlevel 1 (
    echo ❌ ビルド中にエラーが発生しました。
    set ERRFLAG=1
    goto END
)

echo.
echo ✅ ビルド成功！dist\main\main.exe をご確認ください。

copy fail_fetch_01.png dist\main\
copy fail_fetch_02.png dist\main\

:END
if %ERRFLAG%==1 (
    echo.
    echo ⚠️ エラーが発生したため停止しています。Enterキーで閉じます。
    pause >nul
)
endlocal
