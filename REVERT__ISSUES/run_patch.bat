@echo off
title Revert Issues Patch - WordPress Slug Reversal
color 0B
cls
cd /d "%~dp0"

echo =====================================================================
echo           REVERT ISSUES PATCH — WORDPRESS SLUG REVERSAL
echo =====================================================================
echo.
echo [*] Running Python slug patch script...
echo.

python patch_revert_slugs.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Process finished with warnings or errors.
) else (
    echo.
    echo [OK] Patch completed successfully!
)

echo.
echo Press any key to close this window...
pause >nul
