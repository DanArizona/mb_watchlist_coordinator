@echo off
setlocal
python -B "%~dp0run.py" verify
exit /b %errorlevel%
