@echo off
rem Double-click to turn the bot on; double-click again to turn it off.
rem Optional argument: start | stop | status | log
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0voxcord.ps1" %*
