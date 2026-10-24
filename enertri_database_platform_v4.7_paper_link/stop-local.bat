@echo off
setlocal
cd /d "%~dp0"
title EnerTri Local Docker Stop

echo Stopping EnerTri local containers...
docker compose -f docker-compose.local.yml down
echo Done.
pause
