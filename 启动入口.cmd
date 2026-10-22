@echo off
setlocal
title 物理化学实验报告工具
cd /d "%~dp0"

set "PY="
if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "C:\Python310\python.exe" set "PY=C:\Python310\python.exe"
if not defined PY (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  py -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=py"
)
if not defined PY (
  echo  [ERROR] Python 3.10+ not found. Install it and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

"%PY%" -c "import docx, numpy, scipy, matplotlib" >nul 2>nul
if errorlevel 1 (
  echo  Installing dependencies ^(first run only^) ...
  "%PY%" -m pip install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
)

"%PY%" "%~dp0物化实验报告工具\run.py"
pause
