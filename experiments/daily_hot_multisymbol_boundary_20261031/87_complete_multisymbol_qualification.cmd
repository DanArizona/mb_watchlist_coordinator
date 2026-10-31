@echo off
setlocal DisableDelayedExpansion
python -I -B "%~dp0complete.py" %*
set "MB_COMPLETION_EXIT=%ERRORLEVEL%"
endlocal & exit /b %MB_COMPLETION_EXIT%
