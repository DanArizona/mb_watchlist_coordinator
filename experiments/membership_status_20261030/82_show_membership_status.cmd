@echo off
setlocal
python -I -B "%~dp0run.py" show %*
exit /b %errorlevel%
