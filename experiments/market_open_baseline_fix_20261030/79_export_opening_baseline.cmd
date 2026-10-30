@echo off
python -I -B "%~dp0run.py" export --packet-root "C:\Users\danla\hot75\p75" --failed-trial-root "C:\Users\danla\hot75\p75\runs\market_open_daily_20261030_f3beaf98" --journal "C:\Users\danla\Documents\github\mb_market_data\output\quote_observation_journal_v2_api_opening_2026-10-30\2026-10-30.sqlite3" --output "%~dp0runs\opening_20261030.json"
exit /b %errorlevel%
