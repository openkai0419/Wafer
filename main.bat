@echo off
call .venv\Scripts\activate.bat
python main.py %*
if %ERRORLEVEL% neq 0 pause
