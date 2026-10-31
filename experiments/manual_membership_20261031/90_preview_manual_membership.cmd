@echo off
setlocal
python -B "%~dp0run.py" preview
exit /b %errorlevel%
