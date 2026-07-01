@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set NODE_DISABLE_COLORS=0
set SIERRA_WORKSPACE=%CD%
cd /d "%~dp0"

if /I "%~1"=="web" (
  shift
  goto run_web
)

.\tui\node_modules\.bin\tsx.cmd tui\src\entry.tsx
exit /b %errorlevel%

:run_web
set SIERRA_WEB_ARGS=
:collect_web_args
if "%~1"=="" goto start_web
set SIERRA_WEB_ARGS=%SIERRA_WEB_ARGS% "%~1"
shift
goto collect_web_args

:start_web
  echo Building Sierra Web...
  pushd web
  call npm.cmd run build
  if errorlevel 1 (
    popd
    exit /b 1
  )
  popd
  if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run_dashboard.py %SIERRA_WEB_ARGS%
  ) else (
    python run_dashboard.py %SIERRA_WEB_ARGS%
  )
  exit /b %errorlevel%
