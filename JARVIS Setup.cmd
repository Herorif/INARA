@echo off
setlocal DisableDelayedExpansion
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0JARVIS Setup.ps1"
