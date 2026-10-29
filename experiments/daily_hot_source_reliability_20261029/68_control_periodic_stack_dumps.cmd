@echo off
python -I -B "%~dp0trace_control.py"
exit /b %errorlevel%
