@echo off
setlocal
cd /d "%~dp0"
title EnerTri Local Docker Diagnose

echo ============================================================
echo EnerTri Local Docker Diagnose
echo ============================================================
echo Current folder: %cd%
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker command was not found.
    pause
    exit /b 1
)

docker version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker Desktop is not running or Docker is not accessible.
    pause
    exit /b 1
)

echo Docker version:
docker version --format "Client: {{.Client.Version}}  Server: {{.Server.Version}}"
echo.

echo Docker Compose version:
docker compose version
echo.

if not exist "docker-compose.local.yml" (
    echo [ERROR] docker-compose.local.yml was not found in this folder.
    echo Current folder is not the project root.
    pause
    exit /b 1
)

echo Container status:
docker compose -f docker-compose.local.yml ps
echo.

echo Recent logs:
docker compose -f docker-compose.local.yml logs --tail=160
echo.

echo Port check:
curl -fsS http://127.0.0.1:8080 >nul 2>nul
if errorlevel 1 (
    echo [FAIL] http://127.0.0.1:8080 is not reachable.
) else (
    echo [OK] http://127.0.0.1:8080 is reachable.
)

echo.
pause
