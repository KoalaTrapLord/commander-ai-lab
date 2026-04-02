@echo off
REM ═══════════════════════════════════════════════════════════
REM Commander AI Lab — One-Click Launcher (Windows)
REM ═══════════════════════════════════════════════════════════
REM
REM Starts the Python FastAPI server + serves the web UI.
REM Prerequisites:
REM   - Python 3.10+ with: pip install fastapi uvicorn
REM   - Java 17+
REM   - commander-ai-lab built: mvn package "-DskipTests"
REM
REM Edit the paths below to match your system.
REM ═══════════════════════════════════════════════════════════
REM ── Your Forge paths (EDIT THESE) ──────────────────────────
set FORGE_JAR=D:\ForgeCommander\forge-repo\forge-gui-desktop\target\forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar
set FORGE_DIR=D:\ForgeCommander\forge-repo
REM Precon-decks folder — Forge reads .dck files directly from here.
REM This is also used as the source for precon install endpoints.
set FORGE_DECKS_DIR=D:\ForgeCommander\commander-ai-lab\precon-decks
set PRECON_DECKS_DIR=D:\ForgeCommander\commander-ai-lab\precon-decks
REM ── Lab JAR (auto-detected from target/) ─────────────────────
set LAB_PORT=8080

REM ── API Keys (set via environment variables or .env file) ──
REM If not already set in your environment, create a .env file
REM in this directory (see .env.example) or set them manually:
REM   set XIMILAR_API_KEY=your-ximilar-key-here
REM   set ANTHROPIC_API_KEY=your-anthropic-api-key-here
REM
REM Load from .env file if it exists and vars aren't already set
if not defined XIMILAR_API_KEY (
    if exist "%~dp0.env" (
        for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
            if "%%A"=="XIMILAR_API_KEY" set XIMILAR_API_KEY=%%B
            if "%%A"=="ANTHROPIC_API_KEY" set ANTHROPIC_API_KEY=%%B
            if "%%A"=="PRECON_DECKS_DIR" set PRECON_DECKS_DIR=%%B
            if "%%A"=="FORGE_DECKS_DIR" set FORGE_DECKS_DIR=%%B
        )
    )
)

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
echo Ximilar:     Configured
if defined ANTHROPIC_API_KEY (
    echo Claude Opus: Configured
) else (
    echo Claude Opus: Not configured ^(set ANTHROPIC_API_KEY env var for AI features^)
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
    echo   cd D:\ForgeCommander\forge-repo
    echo   mvn package -pl forge-gui-desktop "-DskipTests" "-Drevision=2.0.12-SNAPSHOT" -am
    pause
    exit /b 1
)

REM ── Check if lab_api.py exists ─────────────────────────────
if not exist "%~dp0lab_api.py" (
    echo ERROR: lab_api.py not found in %~dp0
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
    python "%~dp0lab_api.py" ^
        --forge-jar "%FORGE_JAR%" ^
        --forge-dir "%FORGE_DIR%" ^
        --forge-decks-dir "%FORGE_DECKS_DIR%" ^
        --precon-dir "%PRECON_DECKS_DIR%" ^
        --port %LAB_PORT% ^
        --ximilar-key "%XIMILAR_API_KEY%" ^
        --anthropic-key "%ANTHROPIC_API_KEY%"
) else (
    python "%~dp0lab_api.py" ^
        --forge-jar "%FORGE_JAR%" ^
        --forge-dir "%FORGE_DIR%" ^
        --forge-decks-dir "%FORGE_DECKS_DIR%" ^
        --precon-dir "%PRECON_DECKS_DIR%" ^
        --port %LAB_PORT% ^
        --ximilar-key "%XIMILAR_API_KEY%"
)
