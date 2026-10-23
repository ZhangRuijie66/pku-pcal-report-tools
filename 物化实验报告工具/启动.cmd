@echo off
rem Start this tool in the background with no console window.
rem To stop it again: open the portal page and click the stop button,
rem or run the stop entry that sits in the project root.
wscript.exe //NoLogo "%~dp0..\_tools\hidden-launch.vbs" "%~dp0."
