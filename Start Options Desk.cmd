@echo off
rem Starts Options Desk in the background and opens it in the browser.
cd /d "%~dp0"
start "" /min pythonw app.py
