@echo off
REM ═══════════════════════════════════════════════════════════
REM Commander AI Lab — One-Click Launcher (Windows)
REM ═══════════════════════════════════════════════════════════
REM
REM Starts the Python FastAPI server + serves the web UI.
REM Prerequisites:
REM   - Python 3.10+ with: pip install fastapi uvicorn
REM   - Java 17+
REM   - Forge built: mvn package "-DskipTests"
REM
REM All paths are resolved RELATIVE to this script's location.
REM No hardcoded drive letters — works on any machine.
REM ═══════════════════════════════════════════════════════════

REM ── Resolve root from script location (portable, any drive) ─
set SCRIPT_DIR=%~dp0
set FORGE_COMMANDER_ROOT=%SCRIPT_DIR%..

REM ── Forge paths (auto-resolved, no hardcoded drive) ─────────
set FORGE_JAR=%FORGE_COMMANDER_ROOT%\forge-repo\forge-gui-desktop\target\forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar
set FORGE_DIR=%FORGE_COMMANDER_ROOT%\forge-repo
set FORGE_PROFILE=%FORGE_COMMANDER_ROOT%\forge-repo\forge-gui-desktop\target\res\forge.profile.properties

REM ── Deck paths: all inside forge-repo for full portability ──
set FORGE_USER_DATA=%FORGE_COMMANDER_ROOT%\forge-repo\userdata
set FORGE_DECKS_DIR=%FORGE_USER_DATA%\decks
set PRECON_DECKS_DIR=%SCRIPT_DIR%precon-decks

REM ── Lab server port ──────────────────────────────────────────
set LAB_PORT=8080

REM ── API Keys (set via environment variables or .env file) ──
if not defined XIMILAR_API_KEY (
    if exist "%SCRIPT_DIR%.env" (
        for /f "usebackq tokens=1,* delims==" %%A in ("%SCRIPT_DIR%.env") do (
            if "%%A"=="XIMILAR_API_KEY" set XIMILAR_API_KEY=%%B
            if "%%A"=="ANTHROPIC_API_KEY" set ANTHROPIC_API_KEY=%%B
        )
    )
)

REM ═══════════════════════════════════════════════════════════
REM Write forge.profile.properties so Forge resolves decks from
REM forge-repo\userdata instead of %APPDATA%\Forge.
REM Backslashes are doubled as required by .properties format.
REM This is rewritten every launch so it always matches the
REM current machine's absolute path.
REM ═══════════════════════════════════════════════════════════
mkdir "%FORGE_USER_DATA%\decks\commander" 2>nul

REM Build escaped paths for .properties file
set _UD=%FORGE_USER_DATA%
set _DD=%FORGE_DECKS_DIR%
setlocal enabledelayedexpansion
set _UD_ESC=!_UD:\=\\!
set _DD_ESC=!_DD:\=\\!
(echo userDir=!_UD_ESC!) > "%FORGE_PROFILE%"
(echo decksDir=!_DD_ESC!) >> "%FORGE_PROFILE%"
endlocal

REM ── Copy precon .dck files into Forge's commander deck folder
REM    (idempotent — safe to run every launch)
xcopy /Y /Q "%PRECON_DECKS_DIR%\*.dck" "%FORGE_DECKS_DIR%\commander\" >nul 2>&1
echo Synced precon decks to Forge commander folder.

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║       Commander AI Lab — Launcher               ║
echo ╚══════════════════════════════════════════════════╝
echo.
echo Forge JAR:   %FORGE_JAR%
echo Forge Dir:   %FORGE_DIR%
echo Decks Dir:   %FORGE_DECKS_DIR%
echo Precon Dir:  %PRECON_DECKS_DIR%
echo Port:        %LAB_PORT%
if defined XIMILAR_API_KEY (
    echo Ximilar:     Configured
) else (
    echo Ximilar:     Not configured
)
if defined ANTHROPIC_API_KEY (
    echo Claude:      Configured
) else (
    echo Claude:      Not configured ^(set ANTHROPIC_API_KEY for AI features^)
)
echo.

REM ── Check prerequisites ────────────────────────────────────
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found in PATH
    pause
    exit /b 1
)

where java >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Java not found in PATH
    pause
    exit /b 1
)

if not exist "%FORGE_JAR%" (
    echo ERROR: Forge JAR not found at: %FORGE_JAR%
    echo Run Forge build first:
    echo   cd %FORGE_DIR%
    echo   mvn package -pl forge-gui-desktop "-DskipTests" "-Drevision=2.0.12-SNAPSHOT" -am
    pause
    exit /b 1
)

if not exist "%SCRIPT_DIR%lab_api.py" (
    echo ERROR: lab_api.py not found in %SCRIPT_DIR%
    pause
    exit /b 1
)

REM ── Install Python deps if needed ───────────────────────────
python -c "import fastapi" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing FastAPI + Uvicorn...
    pip install fastapi uvicorn
)

REM ── Launch the server ───────────────────────────────────────
echo.
echo Starting Commander AI Lab server...
echo Web UI: http://localhost:%LAB_PORT%
echo API:    http://localhost:%LAB_PORT%/docs
echo Press Ctrl+C to stop.
echo.

if defined ANTHROPIC_API_KEY (
    python "%SCRIPT_DIR%lab_api.py" ^
        --forge-jar "%FORGE_JAR%" ^
        --forge-dir "%FORGE_DIR%" ^
        --forge-decks-dir "%FORGE_DECKS_DIR%" ^
        --precon-dir "%PRECON_DECKS_DIR%" ^
        --port %LAB_PORT% ^
        --ximilar-key "%XIMILAR_API_KEY%" ^
        --anthropic-key "%ANTHROPIC_API_KEY%"
) else (
    python "%SCRIPT_DIR%lab_api.py" ^
        --forge-jar "%FORGE_JAR%" ^
        --forge-dir "%FORGE_DIR%" ^
        --forge-decks-dir "%FORGE_DECKS_DIR%" ^
        --precon-dir "%PRECON_DECKS_DIR%" ^
        --port %LAB_PORT% ^
        --ximilar-key "%XIMILAR_API_KEY%"
)
