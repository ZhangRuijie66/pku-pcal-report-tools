@echo off
rem One click: start the whole toolset in the background, no console window.
rem hidden-launch.vbs with no argument starts the portal (see _tools\launcher.py).
wscript.exe //NoLogo "%~dp0_tools\hidden-launch.vbs"
