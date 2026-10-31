@echo off
setlocal DisableDelayedExpansion
python -I -B "%~dp0run.py" verify
exit /b %errorlevel%
