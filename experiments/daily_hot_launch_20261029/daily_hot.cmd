@echo off
python -I -B "%~dp0run.py" %*
exit /b %errorlevel%
