@echo off
setlocal
python -I -B "%~dp0run.py" %*
exit /b %errorlevel%
