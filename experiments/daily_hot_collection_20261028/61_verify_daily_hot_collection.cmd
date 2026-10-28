@echo off
setlocal
cd /d "%~dp0"
python -I -B "%~dp0run.py" verify
exit /b %ERRORLEVEL%
