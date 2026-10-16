@echo off
title COORDINATOR-SOURCE-REQUESTS
cd /d "%~dp0"
if errorlevel 1 exit /b 1
python -I -B "%~dp0experiments\sampling_requests_20261016\run_request_proof.py"
exit /b %errorlevel%
