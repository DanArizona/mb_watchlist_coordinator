@echo off
setlocal
python -I -B "%~dp0diagnose.py"
exit /b %errorlevel%
