@echo off
setlocal EnableExtensions DisableDelayedExpansion
if not defined MB_NATIVE_CHECKOUT (
  echo ERROR: set MB_NATIVE_CHECKOUT to the isolated native reliability checkout.
  exit /b 2
)
if not defined MB_COORD_CHECKOUT (
  echo ERROR: set MB_COORD_CHECKOUT to the isolated Coordinator reliability checkout.
  exit /b 2
)
python -B "%~dp0verify.py" --native "%MB_NATIVE_CHECKOUT%" --coordinator "%MB_COORD_CHECKOUT%"
exit /b %errorlevel%
