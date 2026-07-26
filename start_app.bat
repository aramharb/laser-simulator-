@echo off
echo ===================================================
echo Starting ShootOFF-legacy Backend and Angular Frontend
echo ===================================================

echo.
echo Starting Python Backend...
start "ShootOFF API" cmd /k "cd backend && py api.py"

echo.
echo Starting Angular Frontend...
start "ShootOFF Frontend" cmd /k "cd "front_end" && npm start -- --open"

echo.
echo Services are launching in separate windows!
echo The frontend will automatically open in your default browser once compiled.
