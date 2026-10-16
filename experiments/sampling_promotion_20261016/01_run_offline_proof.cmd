@echo off
title COORDINATOR-PROMOTION-PROOF
cd /d "%~dp0"
if errorlevel 1 exit /b 1
python -I -B "%~dp0run_offline_proof.py"
exit /b %errorlevel%
