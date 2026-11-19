@echo off
setlocal
cd /d "%~dp0"
set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Replay Lab Python environment is missing. Run start-windows.cmd first.
  pause
  exit /b 2
)
if "%~1"=="" (
  echo.
  echo Round 13 complete coaching API test - one real 2v2 .replay.
  echo Drag an original .replay onto this CMD file or use:
  echo     round13-test-windows.cmd "C:\path\match.replay" [player-index 1-4]
  echo The 1-4 roster index is only needed if identity cannot be verified.
  echo No model requests or native game commands will be sent.
  pause
  exit /b 2
)
if "%~2"=="" (
  "%PY%" -m scripts.round13_full_acceptance --replay "%~1"
) else (
  "%PY%" -m scripts.round13_full_acceptance --replay "%~1" --player-index "%~2"
)
set "RESULT=%ERRORLEVEL%"
echo.
echo API tests do not verify browser playback, genuine model quality or GC-level tactics.
echo Inspect the JSON status for any blocked or unavailable capability.
echo.
pause
exit /b %RESULT%
