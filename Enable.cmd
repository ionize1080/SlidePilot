@echo off
"%~dp0SlidePilot.Manager.exe" enable
set "SlidePilotExit=%errorlevel%"
if not "%SlidePilotExit%"=="0" pause
exit /b %SlidePilotExit%
