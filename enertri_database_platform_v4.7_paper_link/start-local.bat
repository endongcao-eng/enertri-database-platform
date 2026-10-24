@echo off
setlocal
cd /d "%~dp0"
title EnerTri Local Docker Start

echo ============================================================
echo EnerTri Local Docker Start
echo ============================================================
echo Current folder: %cd%
echo.
echo Please make sure this ZIP was fully extracted before running.
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker command was not found.
    echo Install and start Docker Desktop, then run this file again.
    pause
    exit /b 1
)

docker version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running or Docker is not accessible.
    echo Start Docker Desktop and wait until it says Running.
    pause
    exit /b 1
)

docker compose version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] docker compose is not available.
    echo Please update Docker Desktop.
    pause
    exit /b 1
)

if not exist "docker-compose.local.yml" (
    echo [ERROR] docker-compose.local.yml was not found in this folder.
    echo Run this script from the project root folder.
    pause
    exit /b 1
)

set "ENV_FILE_ARG="
if exist "backend\.env" (
    set "ENV_FILE_ARG=--env-file backend\.env"
    echo Loading optional settings from backend\.env
) else (
    echo [INFO] backend\.env not found. AI and licensed CAE execution stay disabled.
)

echo Starting containers...
docker compose %ENV_FILE_ARG% -f docker-compose.local.yml up -d --build
if errorlevel 1 (
    echo.
    echo [ERROR] Docker Compose failed. Recent logs:
    docker compose %ENV_FILE_ARG% -f docker-compose.local.yml logs --tail=120
    pause
    exit /b 1
)

echo.
echo Container status:
docker compose %ENV_FILE_ARG% -f docker-compose.local.yml ps

echo.
echo Checking http://127.0.0.1:8080 ...
curl -fsS http://127.0.0.1:8080 >nul 2>nul
if errorlevel 1 (
    echo [WARN] The site is not reachable yet.
    echo Run diagnose-local.bat to see logs.
) else (
    echo [OK] The site is reachable.
    start "" http://127.0.0.1:8080
)

echo.
echo URL: http://127.0.0.1:8080
echo API docs: http://127.0.0.1:8080/api/docs
echo.
pause
