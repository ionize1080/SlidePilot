@echo off
setlocal
if exist "%~dp0SlidePilot.Setup.exe" (
  start "" "%~dp0SlidePilot.Setup.exe"
  exit /b 0
)
if exist "%~dp0dist\SlidePilot-0.1.0-rc.3\SlidePilot\SlidePilot.Setup.exe" (
  start "" "%~dp0dist\SlidePilot-0.1.0-rc.3\SlidePilot\SlidePilot.Setup.exe"
  exit /b 0
)
echo SlidePilot setup was not found.
echo Extract the COMPLETE portable ZIP, then open SlidePilot.Setup.exe.
echo This source folder must be built before it can be enabled.
pause
exit /b 1
