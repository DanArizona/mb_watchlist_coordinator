@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM Offline-only; never opens production p85 or production SQLite journal.
REM Point MB_NATIVE_CHECKOUT and MB_COORD_CHECKOUT at separate experimental clones/worktrees.
if not defined MB_NATIVE_CHECKOUT (
  echo ERROR: set MB_NATIVE_CHECKOUT to isolated mb_market_data candidate checkout.
  exit /b 2
)
if not defined MB_COORD_CHECKOUT (
  echo ERROR: set MB_COORD_CHECKOUT to isolated mb_watchlist_coordinator checkout.
  exit /b 2
)
if not exist "%MB_NATIVE_CHECKOUT%\src\mb_market_data\daily_acquisition_cycle.py" (
  echo ERROR: native source checkout missing.
  exit /b 2
)
if not exist "%MB_COORD_CHECKOUT%\src\mb_watchlist_coordinator\daily_collector.py" (
  echo ERROR: coordinator source checkout missing.
  exit /b 2
)
where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: activate the sea-green environment before verification.
  exit /b 2
)
for /f "delims=" %%H in ('git -C "%MB_NATIVE_CHECKOUT%" rev-parse HEAD') do set "NATIVE_HEAD=%%H"
for /f "delims=" %%H in ('git -C "%MB_COORD_CHECKOUT%" rev-parse HEAD') do set "COORD_HEAD=%%H"
echo Native commit: %NATIVE_HEAD%
echo Coordinator commit: %COORD_HEAD%
if /I not "%NATIVE_HEAD%"=="53fc9d62155063b3ae2bc5f0bacfd604866241e0" (
  echo ERROR: native candidate commit differs. Do not run this exact-pair verifier.
  exit /b 2
)
REM This verifier is itself a later commit: require the exact tested source
REM checkpoint to be an ancestor and no subsequent changes to target sources.
git -C "%MB_COORD_CHECKOUT%" merge-base --is-ancestor 7fe7af295e2d5cc5ac91ab30bd6850f98ae8cbd5 HEAD
if errorlevel 1 (
  echo ERROR: coordinator correction baseline missing.
  exit /b 2
)
git -C "%MB_COORD_CHECKOUT%" diff --quiet 7fe7af295e2d5cc5ac91ab30bd6850f98ae8cbd5 HEAD -- src/mb_watchlist_coordinator/daily_collector.py src/mb_watchlist_coordinator/daily_operating.py tests/test_daily_collector.py tests/test_daily_operating.py
if errorlevel 1 (
  echo ERROR: coordinator target sources differ from recorded candidate.
  exit /b 2
)
git -C "%MB_COORD_CHECKOUT%" diff --quiet HEAD -- src/mb_watchlist_coordinator/daily_collector.py src/mb_watchlist_coordinator/daily_operating.py tests/test_daily_collector.py tests/test_daily_operating.py
if errorlevel 1 (
  echo ERROR: uncommitted candidate source changes.
  exit /b 2
)
set "PYTHONPATH=%MB_COORD_CHECKOUT%\src;%MB_NATIVE_CHECKOUT%\src;%MB_COORD_CHECKOUT%\tests;%MB_NATIVE_CHECKOUT%\tests"
echo Offline candidate tests. No credentials or provider calls requested.
python -B -m unittest -v test_schwab_quotes.PreProviderDeadlineTests
if errorlevel 1 exit /b 1
python -B -m unittest -v test_daily_collector.DailyCollectorTests.test_final_local_deadline_is_durable_miss_not_block_or_request_error test_daily_collector.DailyCollectorTests.test_prior_cycle_overrun_has_durable_miss_without_catchup
if errorlevel 1 exit /b 1
python -B -m unittest -v test_daily_operating.DailyOperatingTests.test_driver_progress_distinguishes_fresh_terminal_from_stale
if errorlevel 1 exit /b 1
echo Targeted offline regressions completed with zero test errors.
exit /b 0
