@echo off
setlocal
set "SlidePilotRoot=%~dp0.."
set "SlidePilotCsc=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%SlidePilotCsc%" (
  echo Install .NET Framework 4.8 developer tools to compile these source tests.
  exit /b 2
)
if not exist "%SlidePilotRoot%\.build\native-regression" mkdir "%SlidePilotRoot%\.build\native-regression"
"%SlidePilotCsc%" /nologo /optimize+ /codepage:65001 /platform:anycpu /target:exe /reference:Microsoft.CSharp.dll "/out:%SlidePilotRoot%\.build\native-regression\native_regression.exe" "%SlidePilotRoot%\native\Live.cs" "%SlidePilotRoot%\native\OfficeGraph.cs" "%~dp0native_regression.cs"
if errorlevel 1 exit /b %errorlevel%
"%SlidePilotRoot%\.build\native-regression\native_regression.exe"
exit /b %errorlevel%
