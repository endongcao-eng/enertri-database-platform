EnerTri local start scripts for Windows

Recommended files:
1. start-local.bat       Start the platform
2. diagnose-local.bat    Show container status and logs
3. stop-local.bat        Stop containers
4. reset-local-db.bat    Delete local database volume and reset demo data

Steps:
1. Fully extract the ZIP file. Do not run BAT files inside the ZIP preview window.
2. Start Docker Desktop and wait until it says Running.
3. Double-click start-local.bat.
4. Open http://127.0.0.1:8080

If 8080 is occupied, edit docker-compose.local.yml and change:
  - "8080:8080"
to:
  - "8090:8080"
Then open http://127.0.0.1:8090
