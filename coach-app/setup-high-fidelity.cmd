@echo off
setlocal
cd /d "%~dp0"
echo.
echo REPLAY LAB - High-Fidelity 3D Viewer (one-time setup)
echo ==================================================
where node >nul 2>&1
if errorlevel 1 goto :no_node
node -e "if(Number(process.versions.node.split('.')[0])<22)process.exit(1)"
if errorlevel 1 goto :old_node
where npm >nul 2>&1
if errorlevel 1 goto :no_node
pushd "high-fidelity"
echo Installing pinned replay-engine dependencies from npm...
call npm install --no-audit --no-fund
if errorlevel 1 goto :failed
echo Building the local browser viewer...
call npm run build
if errorlevel 1 goto :failed
popd
echo.
echo High-Fidelity 3D Viewer is ready.
echo Start Replay Lab as usual, then open http://127.0.0.1:8000/hd
echo.
pause
goto :end
:no_node
echo Node.js 22 or newer is required. Install it from https://nodejs.org/
goto :stop
:old_node
echo Please upgrade Node.js to version 22 or newer.
goto :stop
:failed
popd
echo.
echo Build failed. The original Replay Lab is unchanged.
:stop
pause
:end
endlocal
