@echo off
rem Build the reviewer dashboard and open it. Double-click to run.
rem After any data changes, run it again for an updated page.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-dashboard.ps1"
if errorlevel 1 pause
