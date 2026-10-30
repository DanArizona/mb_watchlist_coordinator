@echo off
setlocal
python -I -B "%~dp0run.py" verify
exit /b %errorlevel%
