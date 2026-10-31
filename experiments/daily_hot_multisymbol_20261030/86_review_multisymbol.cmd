@echo off
setlocal DisableDelayedExpansion
python -I -B "%~dp0run.py" review-release %*
exit /b %errorlevel%
