@echo off
setlocal DisableDelayedExpansion
python -B "%~dp0run.py" review-release
exit /b %errorlevel%
