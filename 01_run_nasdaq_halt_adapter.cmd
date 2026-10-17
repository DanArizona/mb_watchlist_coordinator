@echo off
title NASDAQ-COORDINATOR-REVIEW
cd /d "%~dp0"
if errorlevel 1 exit /b 1
python -I -B "%~dp0experiments\nasdaq_halt_adapter_20261016\run_recorded_proof.py"
exit /b %errorlevel%
