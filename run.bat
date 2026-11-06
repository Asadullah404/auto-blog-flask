@echo off
title Auto Content Pipeline - Flask Web Control Panel
color 0A
cls
cd /d "%~dp0"
echo =====================================================================
echo           AUTO CONTENT PIPELINE — FLASK CONTROL PANEL
echo =====================================================================
echo.
echo [*] Launching Python runner and web interface...
python run.py
if %errorlevel% neq 0 (
    echo.
    echo [x] An error occurred. Pausing so you can inspect output...
    pause
)
