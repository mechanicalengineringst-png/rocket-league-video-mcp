@echo off
setlocal
cd /d "%~dp0"

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Creating a private Python 3.12 environment for Replay Coach...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failed
)

echo Checking Replay Coach dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

if not exist "%CD%\coach_app\static\hd-player\index.html" (
  echo Building High-Fidelity 3D Viewer bundle...
  where npm >nul 2>&1
  if not errorlevel 1 (
    pushd "high-fidelity"
    call npm run build
    popd
  ) else (
    echo Note: Node.js was not found. High-Fidelity stadium assets will not be rebuilt.
    echo Install Node.js 22+ and run setup-high-fidelity.cmd for full 3D playback.
  )
)

echo.
echo Your replay coach is starting locally.
echo Open http://127.0.0.1:8000 in your browser and upload a .replay file.
echo To stop the coach, close this window or press Ctrl+C.
echo.
"%PY%" -m uvicorn coach_app.main:app --host 127.0.0.1 --port 8000
goto :end

:failed
echo.
echo Setup failed. Check that Python 3.12 is installed and available with: py -3.12 --version
pause

:end
endlocal
