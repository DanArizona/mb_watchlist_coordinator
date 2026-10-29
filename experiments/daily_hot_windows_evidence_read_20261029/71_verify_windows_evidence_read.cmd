@echo off
python -I -B "%~dp0run.py" verify
exit /b %errorlevel%
