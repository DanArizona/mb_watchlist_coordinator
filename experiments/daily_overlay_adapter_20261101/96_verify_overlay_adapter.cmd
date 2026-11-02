@echo off
setlocal
echo OFFLINE read-only daily Overlay: 97 focused and existing-chart checks. Synthetic journals and RSS; no password, API or production access.
python -I -B "%~dp0run.py" verify
exit /b %errorlevel%
