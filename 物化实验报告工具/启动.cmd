@echo off
setlocal enabledelayedexpansion
title Physical Chemistry Lab Report Generator
cd /d "%~dp0"

echo.
echo  ==============================================
echo   Physical Chemistry Lab Report Generator
echo  ==============================================
echo.

rem ---- locate a usable Python interpreter -------------------------------
rem Deliberately use absolute paths first: resolving "python" through PATH is
rem unreliable on this machine, and a wrong hit makes run.py open in an editor.
set "PY="

if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if not defined PY if exist "C:\Python310\python.exe" set "PY=C:\Python310\python.exe"
if not defined PY if exist "C:\Python39\python.exe"  set "PY=C:\Python39\python.exe"

if not defined PY (
  for %%V in (313 312 311 310 39) do (
    if not defined PY (
      if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
      )
    )
  )
)

rem Fall back to whatever "python" is, but only if it really starts.
if not defined PY (
  python -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  py -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY=py"
)

if not defined PY (
  echo  [ERROR] Python 3 was not found.
  echo.
  echo  Install Python 3 from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" during setup.
  echo.
  pause
  exit /b 1
)

echo  Python : %PY%
"%PY%" -c "import sys; print('  Version:', sys.version.split()[0])"

rem ---- dependencies ------------------------------------------------------
"%PY%" -c "import numpy, scipy, matplotlib, docx" >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Installing dependencies ^(first run only, needs network^) ...
  echo.
  "%PY%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple numpy scipy matplotlib python-docx
  if errorlevel 1 (
    echo.
    echo  [ERROR] Could not install dependencies. Check the network and retry.
    echo.
    pause
    exit /b 1
  )
)

echo.
echo  Starting the local server; the browser will open automatically.
echo  Close this window to stop the program.
echo.

"%PY%" "%~dp0run.py"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" echo  The program exited with code %RC%.
pause
exit /b %RC%
