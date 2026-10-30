@echo off
python -I -B "%~dp0run.py" verify --packet-root "C:\Users\danla\hot75\p75"
exit /b %errorlevel%
