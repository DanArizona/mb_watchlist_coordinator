@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM Isolated, synthetic source/identity burst and retained-history verification.
REM No credentials, live Nasdaq transport, Schwab API, installed p85 or production journal.
if not defined MB_NATIVE_CHECKOUT (
  echo ERROR: MB_NATIVE_CHECKOUT not configured.
  exit /b 2
)
if not defined MB_COORD_CHECKOUT (
  echo ERROR: MB_COORD_CHECKOUT not configured.
  exit /b 2
)
if not exist "%MB_NATIVE_CHECKOUT%\src\mb_market_data\daily_acquisition_cycle.py" exit /b 2
if not exist "%MB_COORD_CHECKOUT%\src\mb_watchlist_coordinator\daily_collector.py" exit /b 2
git -C "%MB_NATIVE_CHECKOUT%" diff --quiet HEAD --
if errorlevel 1 (
  echo ERROR: native checkout has uncommitted changes.
  exit /b 2
)
git -C "%MB_COORD_CHECKOUT%" diff --quiet HEAD --
if errorlevel 1 (
  echo ERROR: Coordinator checkout has uncommitted changes.
  exit /b 2
)
for /f "delims=" %%H in ('git -C "%MB_NATIVE_CHECKOUT%" rev-parse HEAD') do set "NATIVE_HEAD=%%H"
echo Native: %NATIVE_HEAD%
if /I not "%NATIVE_HEAD%"=="53fc9d62155063b3ae2bc5f0bacfd604866241e0" (
  echo ERROR: wrong native candidate commit.
  exit /b 2
)
git -C "%MB_COORD_CHECKOUT%" merge-base --is-ancestor 85009ebfba506790882331e00babf3075bc153d3 HEAD
if errorlevel 1 (
  echo ERROR: Coordinator recovery candidate baseline missing.
  exit /b 2
)
set "PYTHONPATH=%MB_COORD_CHECKOUT%\src;%MB_NATIVE_CHECKOUT%\src;%MB_COORD_CHECKOUT%\tests;%MB_NATIVE_CHECKOUT%\tests"
echo.
echo [1/2] Synthetic burst admission and exact-prefix history regressions
python -B -m unittest -v test_daily_multisymbol.MultiIdentityTests.test_one_cycle_authorizes_only_one_of_a_burst_and_returns_pending_work test_daily_multisymbol.MultiIdentityTests.test_forty_authorizations_and_nested_membership_then_durable_overflow_without_quote test_daily_multisymbol.MultiNativeTests.test_actual_native_batches_follow_forty_admissions_and_overflow_with_audit_and_replay test_nasdaq_receipt_prefix.ReceiptPrefixTests
if errorlevel 1 exit /b 1
echo.
echo [2/2] 90 synthetic CURRENT captures with 150 rows each
set "REPORT_ROOT=%MB_COORD_CHECKOUT%\output\hot_reliability_load_20261103"
if not exist "%REPORT_ROOT%" mkdir "%REPORT_ROOT%"
if exist "%REPORT_ROOT%\source_history_90_150.json" (
  echo ERROR: preserve existing report. Rename the prior file or choose another test run.
  exit /b 2
)
python -B "%MB_COORD_CHECKOUT%\experiments\daily_hot_failure_20261102\profile_source_history.py" --at-open --captures 90 --rows-per-capture 150 --output "%REPORT_ROOT%\source_history_90_150.json"
if errorlevel 1 exit /b 1
echo.
echo Offline burst and retained-history workloads completed.
echo Evidence: %REPORT_ROOT%\source_history_90_150.json
exit /b 0
