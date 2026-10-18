@echo off
title HOT-ACQUISITION-REVIEW
cd /d "%~dp0"
if errorlevel 1 exit /b 1
python -I -B "%~dp0experiments\hot_acquisition_20261017\run_hot_proof.py"
exit /b %errorlevel%
