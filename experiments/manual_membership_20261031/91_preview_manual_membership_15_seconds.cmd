@echo off
setlocal
python -B "%~dp0run.py" preview15
exit /b %errorlevel%
