@echo off
setlocal
echo SYNTHETIC browser preview. Stays open until Stop display or Ctrl+C. No password, API, controller launch or production access.
python -I -B "%~dp0run.py" preview %*
exit /b %errorlevel%
