@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Creating a private Python 3.12 environment for Replay Lab...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :python_failed
)

echo Checking Replay Lab backend dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :python_failed

rem Round 13 full acceptance requires a CURRENT HD bundle, not a stale
rem build left over from another Git branch. Rebuild on every launch.
echo Checking Node.js 22+ for the full Replay Lab HD experience...
where node >nul 2>&1
if errorlevel 1 goto :hd_failed
node -e "if(Number(process.versions.node.split('.')[0])<22)process.exit(1)"
if errorlevel 1 goto :hd_failed
where npm >nul 2>&1
if errorlevel 1 goto :hd_failed

pushd "high-fidelity"
rem npm ci is needed on the first run or when node_modules is missing.
if not exist "node_modules\vite\bin\vite.js" (
  echo Installing pinned HD viewer dependencies...
  call npm ci --no-audit --no-fund
  if errorlevel 1 goto :hd_failed_pop
)
echo Building the CURRENT branch's high-fidelity 3D viewer...
call npm run build
if errorlevel 1 (
  echo Build failed; reinstalling pinned dependencies and retrying once...
  call npm ci --no-audit --no-fund
  if errorlevel 1 goto :hd_failed_pop
  call npm run build
  if errorlevel 1 goto :hd_failed_pop
)
popd
if not exist "coach_app\static\hd-player\index.html" goto :hd_failed

echo.
echo Replay Lab Round 13 is starting locally.
echo Open http://127.0.0.1:8000 in your browser.
echo The default coaching and report paths do not call external AI services.
echo Use round13-test-windows.cmd with a real 2v2 replay for a separate API gate.
echo Press Ctrl+C to stop the local server.
echo.
"%PY%" -m uvicorn coach_app.main:app --host 127.0.0.1 --port 8000
goto :end

:hd_failed_pop
popd
:hd_failed
echo.
echo Full HD launch is BLOCKED. Check Node.js 22+, npm and the HD build.
echo This test-ready launcher will not silently run an outdated 3D bundle.
pause
exit /b 2

:python_failed
echo.
echo Python setup failed. Install Python 3.12 and retry.
pause
exit /b 2

:end
endlocal
