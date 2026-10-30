@echo off
python -I -B "%~dp0run.py" prepare --packet-root "C:\Users\danla\hot75\p75" --failed-trial-root "C:\Users\danla\hot75\p75\runs\market_open_daily_20261030_f3beaf98" --baseline-export "%~dp0runs\opening_20261030.json"
exit /b %errorlevel%
