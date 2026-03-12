@echo off
REM ═══════════════════════════════════════════════════════════
REM  Commander AI Lab — One-Click Launcher (Windows)
REM ═══════════════════════════════════════════════════════════
REM
REM  Starts the Python FastAPI server + serves the web UI.
REM  Prerequisites:
REM    - Python 3.10+ with: pip install fastapi uvicorn
REM    - Java 17+
REM    - commander-ai-lab built: mvn package "-DskipTests"
REM
REM  Edit the paths below to match your system.
REM ═══════════════════════════════════════════════════════════

REM ── Your Forge paths (EDIT THESE) ──────────────────────────
set FORGE_JAR=D:\ForgeCommander\forge-repo\forge-gui-desktop\target\forge-gui-desktop-2.0.12-SNAPSHOT-jar-with-dependencies.jar
set FORGE_DIR=D:\ForgeCommander\forge-repo\forge-gui
set FORGE_DECKS_DIR=%APPDATA%\Forge\decks\commander

REM ── Lab JAR (auto-detected from target/) ───────────────────
set LAB_PORT=8080

REM ── Ximilar API Key for Card Scanner ────────────────────────
set XIMILAR_API_KEY=96c7dab35ddbd8829b04c0f5bcea57f5ede20496

REM ── Perplexity API Key for AI Deck Research/Generation ─────
set PPLX_API_KEY=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

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║      Commander AI Lab — Launcher                ║
echo  ╚══════════════════════════════════════════════════╝
echo.
echo  Forge JAR:    %FORGE_JAR%
echo  Forge Dir:    %FORGE_DIR%
echo  Decks Dir:    %FORGE_DECKS_DIR%
echo  Port:         %LAB_PORT%
echo  Ximilar:      Configured
if defined PPLX_API_KEY (
    echo  Perplexity:   Configured
) else (
    echo  Perplexity:   Not configured ^(set PPLX_API_KEY env var for AI features^)
)
echo.

REM ── Check prerequisites ────────────────────────────────────
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  ERROR: Python not found in PATH
    pause
    exit /b 1
)

where java >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  ERROR: Java not found in PATH
    pause
    exit /b 1
)

if not exist "%FORGE_JAR%" (
    echo  ERROR: Forge JAR not found at: %FORGE_JAR%
    echo  Run Forge build first:
    echo    cd D:\ForgeCommander\forge-repo
    echo    mvn package -pl forge-gui-desktop "-DskipTests" "-Drevision=2.0.12-SNAPSHOT" -am
    pause
    exit /b 1
)

REM ── Check if lab_api.py exists ─────────────────────────────
if not exist "%~dp0lab_api.py" (
    echo  ERROR: lab_api.py not found in %~dp0
    pause
    exit /b 1
)

REM ── Install Python deps if needed ──────────────────────────
python -c "import fastapi" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  Installing FastAPI + Uvicorn...
    pip install fastapi uvicorn
)

REM ── Launch the server ──────────────────────────────────────
echo.
echo  Starting Commander AI Lab server...
echo  Web UI:  http://localhost:%LAB_PORT%
echo  API:     http://localhost:%LAB_PORT%/docs
echo  Press Ctrl+C to stop.
echo.

if defined PPLX_API_KEY (
    python "%~dp0lab_api.py" ^
        --forge-jar "%FORGE_JAR%" ^
        --forge-dir "%FORGE_DIR%" ^
        --forge-decks-dir "%FORGE_DECKS_DIR%" ^
        --port %LAB_PORT% ^
        --ximilar-key "%XIMILAR_API_KEY%" ^
        --pplx-key "%PPLX_API_KEY%"
) else (
    python "%~dp0lab_api.py" ^
        --forge-jar "%FORGE_JAR%" ^
        --forge-dir "%FORGE_DIR%" ^
        --forge-decks-dir "%FORGE_DECKS_DIR%" ^
        --port %LAB_PORT% ^
        --ximilar-key "%XIMILAR_API_KEY%"
)
