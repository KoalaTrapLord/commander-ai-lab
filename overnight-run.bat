@echo off
REM ═══════════════════════════════════════════════════════════
REM  Commander AI Lab — Overnight AFK Runner
REM ═══════════════════════════════════════════════════════════
REM
REM  Runs batch simulations for ~11.5 hours, then auto-trains
REM  the ML policy network. Designed to run while you sleep.
REM
REM  PREREQUISITES:
REM    1. Lab server must already be running (start-lab.bat)
REM    2. LM Studio must be running with DeepSeek loaded
REM    3. At least 1 deck available in the lab
REM
REM  USAGE:
REM    Double-click this file, or run from command prompt:
REM      overnight-run.bat
REM
REM  To customize, edit the settings below or pass arguments:
REM      overnight-run.bat --games 50 --hours 8 --epochs 200
REM ═══════════════════════════════════════════════════════════

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   Commander AI Lab — Overnight AFK Runner        ║
echo  ╠══════════════════════════════════════════════════╣
echo  ║                                                  ║
echo  ║   This will run batch simulations for ~11.5h     ║
echo  ║   then auto-train the ML policy network.         ║
echo  ║                                                  ║
echo  ║   Make sure:                                     ║
echo  ║    - Lab server is running (start-lab.bat)       ║
echo  ║    - LM Studio has DeepSeek loaded               ║
echo  ║    - Power settings: prevent sleep                ║
echo  ║                                                  ║
echo  ║   Press Ctrl+C at any time to stop early.        ║
echo  ║                                                  ║
echo  ╚══════════════════════════════════════════════════╝
echo.

REM ── Pause to let user read the message ─────────────────
timeout /t 5 /nobreak >nul

REM ── Run the Python overnight script ────────────────────
python "%~dp0overnight-run.py" %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo  Overnight run ended with errors. Check the output above.
    echo.
)

echo.
echo  Overnight run complete. Press any key to close.
pause >nul
