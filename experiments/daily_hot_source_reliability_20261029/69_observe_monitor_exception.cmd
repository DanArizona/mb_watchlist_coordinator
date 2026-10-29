@echo off
python -I -B "%~dp0observe_monitor.py"
exit /b %errorlevel%
