@echo off
title OUTSIDE-UNI-ADMISSION-REVIEW
cd /d "%~dp0"
if errorlevel 1 exit /b 1
python -I -B "%~dp0experiments\sampling_admission_20261017\run_admission_proof.py"
exit /b %errorlevel%
