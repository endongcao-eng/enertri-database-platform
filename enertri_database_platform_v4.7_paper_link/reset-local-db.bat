@echo off
setlocal
cd /d "%~dp0"
title EnerTri Local Docker Reset

echo WARNING: This will stop containers and delete the local PostgreSQL volume.
echo All local database data will be removed.
echo.
set /p CONFIRM=Type RESET to continue: 
if not "%CONFIRM%"=="RESET" (
    echo Cancelled.
    pause
    exit /b 0
)

docker compose -f docker-compose.local.yml down -v
echo Reset complete. Run start-local.bat again.
pause
