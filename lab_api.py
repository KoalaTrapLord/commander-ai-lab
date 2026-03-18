#!/usr/bin/env python3
"""
Commander AI Lab — FastAPI Backend
Thin entry point: registers routers and starts uvicorn.
"""
import argparse
import logging
import os
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
except ImportError:
    print("ERROR: FastAPI not installed. Run: pip install fastapi uvicorn")
    import sys; sys.exit(1)

from routes.shared import (
    CFG,
    setup_logging,
    init_collection_db,
    download_precon_database,
    load_commander_meta,
    PRECON_INDEX,
    COMMANDER_META,
)
from routes.collection import router as collection_router
from routes.deckbuilder import router as deckbuilder_router
from routes.precon import router as precon_router
from routes.import_routes import router as import_router
from routes.lab import router as lab_router
from routes.scanner import router as scanner_router
from routes.deepseek import router as deepseek_router
from routes.deckgen import router as deckgen_router
from routes.coach import router as coach_router, init_coach_service
from routes.ml import router as ml_router

log = logging.getLogger("commander_ai_lab.api")

# ── App ────────────────────────────────────────────────────────
app = FastAPI(title="Commander AI Lab API", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(collection_router)
app.include_router(deckbuilder_router)
app.include_router(precon_router)
app.include_router(import_router)
app.include_router(lab_router)
app.include_router(scanner_router)
app.include_router(deepseek_router)
app.include_router(deckgen_router)
app.include_router(coach_router)
app.include_router(ml_router)


@app.on_event("startup")
async def _on_startup():
    """Ensure DB and precon index are ready (supports uvicorn --reload)."""
    import routes.shared as _shared
    _shared.init_collection_db()
    if not _shared.PRECON_INDEX:
        _shared.download_precon_database()
    if not _shared.COMMANDER_META:
        _shared.load_commander_meta()


# ── Static UI ──────────────────────────────────────────────────
_legacy_ui_dir = Path(__file__).parent / "ui"
_spa_dir = Path(__file__).parent / "frontend" / "commander-ai-lab-ui" / "dist"

if _legacy_ui_dir.exists():
    app.mount("/", StaticFiles(directory=str(_legacy_ui_dir), html=True), name="ui")
elif _spa_dir.exists():
    _spa_assets = _spa_dir / "assets"
    if _spa_assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_spa_assets)), name="spa-assets")

    @app.get("/{full_path:path}")
    async def _spa_catchall(full_path: str):
        from fastapi.responses import FileResponse
        requested_file = _spa_dir / full_path
        if full_path and requested_file.exists() and requested_file.is_file():
            return FileResponse(str(requested_file))
        return FileResponse(str(_spa_dir / "index.html"))


# ── Startup ────────────────────────────────────────────────────
def _parse_args():
    p = argparse.ArgumentParser(description="Commander AI Lab API Server")
    p.add_argument("--forge-jar",   default=os.environ.get("FORGE_JAR", ""))
    p.add_argument("--forge-dir",   default=os.environ.get("FORGE_DIR", ""))
    p.add_argument("--forge-decks-dir", default=os.environ.get("FORGE_DECKS_DIR", ""))
    p.add_argument("--lab-jar",     default=os.environ.get("LAB_JAR", ""))
    p.add_argument("--port",        type=int, default=int(os.environ.get("LAB_PORT", "8080")))
    p.add_argument("--ximilar-key", default=os.environ.get("XIMILAR_API_KEY", ""))
    p.add_argument("--pplx-key",    default=os.environ.get("PPLX_API_KEY", ""))
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def _resolve_forge_decks_dir() -> str:
    import sys
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidate = os.path.join(appdata, "Forge", "decks", "commander")
            if os.path.isdir(candidate):
                return candidate
    home = Path.home()
    for candidate in [
        home / ".forge" / "decks" / "commander",
        home / "Forge" / "decks" / "commander",
    ]:
        if candidate.is_dir():
            return str(candidate)
    return ""


def _resolve_forge_jar() -> str:
    """Auto-detect the Forge GUI desktop JAR in common locations."""
    project_root = Path(__file__).parent
    # Candidate directories where the Forge JAR might live
    candidates = [
        project_root / "forge-gui-desktop" / "target",
        project_root.parent / "forge-repo" / "forge-gui-desktop" / "target",
        project_root.parent / "forge" / "forge-gui-desktop" / "target",
    ]
    # Also check FORGE_DIR/../forge-gui-desktop/target if FORGE_DIR is set
    forge_dir_env = os.environ.get("FORGE_DIR", "")
    if forge_dir_env:
        fd = Path(forge_dir_env)
        candidates.append(fd.parent / "forge-gui-desktop" / "target")
        candidates.append(fd / "target")
    for target_dir in candidates:
        if target_dir.is_dir():
            for pattern in [
                "forge-gui-desktop-*-jar-with-dependencies.jar",
                "forge-gui-desktop-*-shaded.jar",
                "forge-gui-desktop-*.jar",
            ]:
                jars = sorted(target_dir.glob(pattern))
                jars = [j for j in jars if not j.name.startswith("original-")]
                if jars:
                    return str(jars[0])
    return ""


def _resolve_lab_jar() -> str:
    target_dir = Path(__file__).parent / "target"
    if target_dir.exists():
        for pattern in [
            "commander-ai-lab-*-jar-with-dependencies.jar",
            "commander-ai-lab-*-shaded.jar",
            "commander-ai-lab-*.jar",
        ]:
            jars = sorted(target_dir.glob(pattern))
            jars = [j for j in jars if not j.name.startswith("original-")]
            if jars:
                return str(jars[0])
    return ""


def main():
    args = _parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    CFG.forge_jar       = args.forge_jar or _resolve_forge_jar()
    CFG.forge_dir       = args.forge_dir
    CFG.forge_decks_dir = args.forge_decks_dir or _resolve_forge_decks_dir()
    CFG.lab_jar         = args.lab_jar or _resolve_lab_jar()
    CFG.port            = args.port
    CFG.ximilar_api_key = args.ximilar_key
    CFG.pplx_api_key    = args.pplx_key

    from routes.shared import get_java17
    j17 = get_java17()

    log.info("Commander AI Lab — API Server v3.0.0")
    log.info(f"  Port:       {CFG.port}")
    log.info(f"  Forge JAR:  {CFG.forge_jar or 'NOT SET'}")
    log.info(f"  Decks Dir:  {CFG.forge_decks_dir or 'NOT SET'}")
    log.info(f"  Ximilar:    {'configured' if CFG.ximilar_api_key else 'NOT SET'}")
    log.info(f"  Perplexity: {'configured' if CFG.pplx_api_key else 'NOT SET'}")
    log.info(f"  Java 17:    {j17}")

    load_commander_meta()
    download_precon_database()
    init_collection_db()
    init_coach_service()

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=CFG.port, log_level="info")


if __name__ == "__main__":
    main()
