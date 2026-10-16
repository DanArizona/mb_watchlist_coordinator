@echo off
title COORDINATOR-RESTRICTIONS-DEMOTION
cd /d "%~dp0"
if errorlevel 1 exit /b 1
python -I -B "%~dp0experiments\sampling_policy_20261016\run_policy_proof.py"
exit /b %errorlevel%
