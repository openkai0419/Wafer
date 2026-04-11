@echo off
call %~dp0..\.\.venv\Scripts\activate.bat
python %~dp0test.py %*
