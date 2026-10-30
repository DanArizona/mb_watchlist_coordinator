@echo off
python -I -B "%~dp0run.py" live %*
exit /b %errorlevel%
