@echo off
rem Runs setup_claude_code.ps1 without changing the machine's PowerShell execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_claude_code.ps1"
set "SETUP_EXIT=%ERRORLEVEL%"
if not "%SETUP_EXIT%"=="0" (
    echo.
    echo ==^> El setup fallo. Revisa los mensajes de arriba.
)
pause
exit /b %SETUP_EXIT%
