@echo off
setlocal
title Install dependencies
cd /d "%~dp0"

set "PY="
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if not defined PY if exist "C:\Python310\python.exe" set "PY=C:\Python310\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY (
  python -c "import sys" >/dev/null 2>/dev/null
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo  [ERROR] Python 3.10+ not found. Install it from python.org and
  echo          tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)

echo  Installing / refreshing dependencies (Tsinghua mirror) ...
"%PY%" -m pip install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo.
  echo  [ERROR] Install failed. Check the network and try again.
  pause
  exit /b 1
)
echo.
echo  Done. Start the tools with the desktop shortcut, or with the .vbs
echo  entry files in this folder / in each tool folder.
pause
