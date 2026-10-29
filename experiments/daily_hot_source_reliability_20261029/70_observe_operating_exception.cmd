@echo off
python -I -B "%~dp0observe_operating.py"
exit /b %errorlevel%
