@echo off
setlocal
if "%~1"=="" (
  echo Usage: Test-Qwen.cmd "C:\path\to\token-plan-key.txt"
  echo Sends only the included Harbour example to the configured Qwen Token Plan endpoint.
  echo The report and any generated slides are saved under your local SlidePilot benchmark folder.
  pause
  exit /b 2
)
if not exist "%~dp0Runtime\python.exe" (
  echo Run this command from the fully extracted portable package.
  exit /b 2
)
"%~dp0Runtime\python.exe" -B "%~dp0tests\qwen_live.py" --key-file "%~f1" --validator "%~dp0SlidePilot.Validate.exe" --output "%LOCALAPPDATA%\SlidePilot\benchmarks"
exit /b %errorlevel%
