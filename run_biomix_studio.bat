@echo off
setlocal enabledelayedexpansion
title BioMix-STR - Ansys Fluent 2026 R1 CFD Studio
cd /d "%~dp0"

echo ============================================================================
echo   BioMix-STR - Stirred Tank Bioreactor CFD Studio Launcher
echo   Authoritative Ansys Fluent 2026 R1 (v261) Engineering Workbench
echo ============================================================================
echo.

:: 1. Locate and activate virtual environment
set "VENV_DIR="
if exist "%~dp0.venv\Scripts\activate.bat" set "VENV_DIR=%~dp0.venv"
if not defined VENV_DIR if exist "%~dp0biomix_str\.venv\Scripts\activate.bat" set "VENV_DIR=%~dp0biomix_str\.venv"

if not defined VENV_DIR (
    echo [ERROR] Python virtual environment .venv not found.
    echo Please ensure .venv exists in "%~dp0" or "%~dp0biomix_str".
    pause
    exit /b 1
)

echo [1/3] Activating virtual environment: !VENV_DIR!
call "!VENV_DIR!\Scripts\activate.bat"

:: 2. Check and terminate any stale process on port 8000
echo [2/3] Checking port 8000 for stale listeners...
for /f "tokens=5" %%a in ('netstat -a -n -o ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    echo   Terminating stale process on port 8000 [PID: %%a]...
    taskkill /F /PID %%a >nul 2>&1
)

:: 3. Change directory to package root so relative data and output directories resolve
if exist "%~dp0biomix_str\pyproject.toml" (
    cd /d "%~dp0biomix_str"
)

:: 4. Launch browser after a brief delay and start Uvicorn
echo [3/3] Launching web browser and starting Uvicorn server on http://127.0.0.1:8000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"

python -m uvicorn biomix.server:app --host 127.0.0.1 --port 8000

if errorlevel 1 (
    echo.
    echo [ERROR] BioMix-STR server terminated with an error code.
    pause
)
