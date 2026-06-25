@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set NODE_DISABLE_COLORS=0
set SIERRA_WORKSPACE=%CD%
cd /d "%~dp0"
.\tui\node_modules\.bin\tsx.cmd tui\src\entry.tsx
