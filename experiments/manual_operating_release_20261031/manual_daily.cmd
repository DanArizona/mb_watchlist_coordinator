@echo off
setlocal DisableDelayedExpansion
python -B "%~dp0run.py" %*
exit /b %errorlevel%
