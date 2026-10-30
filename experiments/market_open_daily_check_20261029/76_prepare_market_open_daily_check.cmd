@echo off
python -I -B "%~dp0run.py" prepare %*
exit /b %errorlevel%
