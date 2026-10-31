@echo off
setlocal DisableDelayedExpansion
python -B "%~dp0run.py" verify
exit /b %errorlevel%
