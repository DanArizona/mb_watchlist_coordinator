@echo off
setlocal DisableDelayedExpansion
python -I -B "%~dp0run.py" %*
exit /b %errorlevel%
