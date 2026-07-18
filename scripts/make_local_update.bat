@echo off
call %~dp0..\.\.venv\Scripts\activate.bat
python %~dp0make_local_update.py %*
pause
