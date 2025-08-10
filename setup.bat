rem python version 3.10
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt 

if %ERRFLAG%==1 (
    echo.
    echo Stopped due to errors. Press Enter to close.
    pause >nul
)