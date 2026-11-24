@echo off
"%~dp0SlidePilot.Manager.exe" status
set "SlidePilotExit=%errorlevel%"
pause
exit /b %SlidePilotExit%
