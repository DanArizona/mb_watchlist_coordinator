@echo off
title COORDINATOR-PUBLICATION-REVIEW
cd /d "%~dp0"
if errorlevel 1 exit /b 1
python -I -B "%~dp0experiments\sampling_service_20261017\run_service_proof.py"
exit /b %errorlevel%
