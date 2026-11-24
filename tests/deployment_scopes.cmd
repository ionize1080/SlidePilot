@echo off
setlocal
if "%~1"=="" (
  echo Usage: tests\deployment_scopes.cmd "C:\SlidePilot"
  exit /b 2
)
set "SlidePilotRoot=%~dp0.."
if not exist "%SlidePilotRoot%\.build\deployment-scope-tests" mkdir "%SlidePilotRoot%\.build\deployment-scope-tests"
"%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe" /nologo /codepage:65001 /target:exe /main:MachineScopeTest /out:"%SlidePilotRoot%\.build\deployment-scope-tests\deployment_scopes.exe" "%SlidePilotRoot%\native\Manager.cs" "%~dp0deployment_scopes.cs"
if errorlevel 1 exit /b 1
if "%~1"=="--files" (
  "%SlidePilotRoot%\.build\deployment-scope-tests\deployment_scopes.exe" --files
) else if "%~1"=="--paths" (
  "%SlidePilotRoot%\.build\deployment-scope-tests\deployment_scopes.exe" --paths
) else (
  "%SlidePilotRoot%\.build\deployment-scope-tests\deployment_scopes.exe" "%~f1"
)
exit /b %errorlevel%
