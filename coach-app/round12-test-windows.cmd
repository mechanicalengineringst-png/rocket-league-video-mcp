@echo off
setlocal
cd /d "%~dp0"

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Replay Lab Python environment is missing.
  echo Run start-windows.cmd first to install dependencies.
  pause
  exit /b 2
)
if "%~1"=="" (
  echo.
  echo Drag one original Rocket League .replay file onto this file,
  echo or run: round12-test-windows.cmd "C:\path\to\game.replay"
  echo.
  echo This checks local decoding, source-backed coaching, and viewer setup.
  echo It does NOT call an AI model or send native-game commands.
  echo See docs\round12\TESTING_GUIDE.md for opt-in model/native checks.
  pause
  exit /b 2
)
echo.
echo Round 12 local replay acceptance checks.
echo No model calls, no native commands, no settings changes.
echo.
"%PY%" -m scripts.round12_acceptance --replay "%~1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Structural replay coaching tests passed. Expert quality is NOT verified.
) else (
  echo Some structural acceptance checks need attention.
)
echo.
pause
exit /b %EXIT_CODE%
