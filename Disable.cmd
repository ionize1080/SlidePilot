@echo off
"%~dp0SlidePilot.Manager.exe" disable
set "SlidePilotExit=%errorlevel%"
if not "%SlidePilotExit%"=="0" pause
exit /b %SlidePilotExit%
