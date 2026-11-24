@echo off
setlocal
if "%~1"=="" (
  echo Usage: tests\host_state_regression.cmd "C:\SlidePilot\SlidePilot.PowerPoint.dll"
  exit /b 2
)
set "SlidePilotTestRoot=%~dp0..\.build\native-regression"
if not exist "%SlidePilotTestRoot%" mkdir "%SlidePilotTestRoot%"
"%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe" /nologo /optimize+ /platform:anycpu /target:exe /reference:System.Drawing.dll "/out:%SlidePilotTestRoot%\host_state_regression.exe" "%~dp0host_state_regression.cs"
if errorlevel 1 exit /b %errorlevel%
"%SlidePilotTestRoot%\host_state_regression.exe" "%~f1"
exit /b %errorlevel%
