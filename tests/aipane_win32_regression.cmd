@echo off
setlocal
if "%~1"=="" (
  echo Usage: tests\aipane_win32_regression.cmd "C:\SlidePilot\SlidePilot.PowerPoint.dll"
  echo Exit 77 means the environment could not create an isolated desktop.
  exit /b 2
)
set "SlidePilotWin32TestRoot=%~dp0..\.build\native-regression"
if not exist "%SlidePilotWin32TestRoot%" mkdir "%SlidePilotWin32TestRoot%"
"%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe" /nologo /optimize+ /platform:anycpu /target:exe /reference:System.Drawing.dll /reference:System.Windows.Forms.dll "/out:%SlidePilotWin32TestRoot%\aipane_win32_regression.exe" "%~dp0aipane_win32_regression.cs"
if errorlevel 1 exit /b %errorlevel%
"%SlidePilotWin32TestRoot%\aipane_win32_regression.exe" "%~f1"
exit /b %errorlevel%
