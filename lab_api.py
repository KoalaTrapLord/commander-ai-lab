#!/usr/bin/env python3
"""
Commander AI Lab — FastAPI Backend
Thin entry point: registers routers and starts uvicorn.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be set directly

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
except ImportError:
    print("ERROR: FastAPI not installed. Run: pip install fastapi uvicorn")
    import sys; sys.exit(1)

from models.state import CFG, COMMANDER_META, load_commander_meta
from services.database import init_collection_db
from services.logging import setup_logging
from services.precon_service import PRECON_INDEX, download_precon_database
from routes.collection import router as collection_router
from routes.deckbuilder import router as deckbuilder_router
from routes.precon import router as precon_router
from routes.import_routes import router as import_router
from routes.lab import router as lab_router
from routes.scanner import router as scanner_router
from routes.rag import router as rag_router
from routes.deepseek import router as deepseek_router
from routes.deckgen import router as deckgen_router
from routes.coach import router as coach_router, init_coach_service
from routes.ml import router as ml_router
from routes.ws_game import router as ws_game_router

log = logging.getLogger("commander_ai_lab.api")

_DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3000,http://localhost:8080"
_allowed = os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS)
allowed_origins = [o.strip() for o in _allowed.split(",") if o.strip()]


# ── Lifespan (replaces deprecated @app.on_event) ───────────────────────────────────────
@asynccontextmanager
async def _lifespan(application: FastAPI):
    # ──── STARTUP ────
    if not CFG.precon_dir:
        CFG.precon_dir = _resolve_precon_dir()
    init_collection_db()
    if not PRECON_INDEX:
        download_precon_database()
    if not COMMANDER_META:
        load_commander_meta()

    loop = asyncio.get_running_loop()

    # RAG Phase 1: kick off Scryfall bulk download in background thread.
    from services.scryfall_bulk import ensure_bulk_db
    loop.run_in_executor(None, ensure_bulk_db)

    # RAG Phase 2: kick off ChromaDB vector store build in background thread.
    from services.rag_store import ensure_rag_store
    loop.run_in_executor(None, ensure_rag_store)

    # RAG Phase 3: background staleness monitor (rebuilds if >14 days old)
    async def _rag_staleness_monitor():
        """Periodically check if the RAG index needs rebuilding."""
        import time as _time
        while True:
            await asyncio.sleep(6 * 3600)  # check every 6 hours
            try:
                from services.rag_store import check_staleness, build_index
                info = check_staleness()
                if info.get("stale"):
                    log.info("RAG staleness monitor: %s — triggering rebuild.", info["reason"])
                    loop.run_in_executor(None, lambda: build_index(force=True))
                else:
                    log.debug("RAG staleness monitor: index is current (%.1f days).", info.get("age_days", 0))
            except Exception as exc:
                log.warning("RAG staleness monitor failed: %s", exc)
    asyncio.ensure_future(_rag_staleness_monitor())

    # Policy routes: register if ML policy model is available
    try:
        from ml.serving.policy_server import PolicyInferenceService
        from routes.policy import register_policy_routes
        _policy_svc = PolicyInferenceService()
        if _policy_svc.load():
            register_policy_routes(application, _policy_svc)
            log.info("Policy routes registered (/api/policy/*)")
        else:
            log.warning("Policy model not loaded — /api/policy/* routes inactive")
    except ImportError:
        log.info("Policy service not available (ml.serving not installed)")
    except Exception as e:
        log.warning("Policy route registration failed (non-fatal): %s", e)

    yield  # ← server is running

    # ──── SHUTDOWN ────
    from services.async_db import async_close_db
    await async_close_db()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Commander AI Lab API", version="3.0.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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
app.include_router(rag_router)
app.include_router(deepseek_router)
app.include_router(deckgen_router)
app.include_router(coach_router)
app.include_router(ws_game_router)
app.include_router(ml_router)


# ── API endpoints ────────────────────────────────────────────────────────────────
# NOTE: all @app.get routes MUST be registered before app.mount() calls.
# Once StaticFiles is mounted at "/", it registers a wildcard catch-all that
# shadows any routes added after it.

@app.get("/api/health")
async def health_check():
    """Health check endpoint for load balancers and Unity client polling."""
    return {"status": "ok"}

# ── Static UI (MUST come after all @app.get routes) ────────────────────────────
from pathlib import Path as _Path
_legacy_ui_dir = _Path(__file__).parent / "ui"
_spa_dir = _Path(__file__).parent / "frontend" / "commander-ai-lab-ui" / "dist"

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


# ── Argument parsing + auto-detection helpers ───────────────────────────────────────
def _parse_args():
    p = argparse.ArgumentParser(description="Commander AI Lab API Server")
    p.add_argument("--forge-jar", default=os.environ.get("FORGE_JAR", ""))
    p.add_argument("--forge-dir", default=os.environ.get("FORGE_DIR", ""))
    p.add_argument("--forge-decks-dir", default=os.environ.get("FORGE_DECKS_DIR", ""))
    p.add_argument("--lab-jar", default=os.environ.get("LAB_JAR", ""))
    p.add_argument("--precon-dir", default=os.environ.get("PRECON_DIR", ""))
    p.add_argument("--port", type=int, default=int(os.environ.get("LAB_PORT", "8080")))
    p.add_argument("--ximilar-key", default=os.environ.get("XIMILAR_API_KEY", ""))
    p.add_argument("--anthropic-key", default=os.environ.get("ANTHROPIC_API_KEY", ""))
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


def _resolve_forge_dir() -> str:
    """Auto-detect the Forge installation directory."""
    import sys
    if CFG.forge_jar and os.path.isfile(CFG.forge_jar):
        jar_path = Path(CFG.forge_jar)
        candidate = jar_path.parent.parent.parent
        if candidate.is_dir() and (candidate / "res").is_dir():
            return str(candidate)
        candidate = jar_path.parent.parent
        forge_gui_sibling = jar_path.parent.parent.parent / "forge-gui"
        if forge_gui_sibling.is_dir() and (forge_gui_sibling / "res").is_dir():
            return str(forge_gui_sibling)
        if candidate.is_dir() and (candidate / "res").is_dir():
            return str(candidate)
        candidate = jar_path.parent
        if candidate.is_dir():
            return str(candidate)
    project_root = Path(__file__).parent
    for candidate in [
        project_root / "forge",
        project_root.parent / "forge-repo",
        project_root.parent / "forge-repo" / "forge-gui",
        project_root.parent / "forge",
        project_root / "forge-gui-desktop",
    ]:
        if candidate.is_dir():
            if (candidate / "res").is_dir():
                return str(candidate)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidate = Path(appdata) / "Forge"
            if candidate.is_dir():
                return str(candidate)
    home = Path.home()
    for candidate in [home / ".forge", home / "Forge"]:
        if candidate.is_dir():
            return str(candidate)
    return ""


def _resolve_forge_jar() -> str:
    """Auto-detect the Forge GUI desktop JAR in common locations."""
    project_root = Path(__file__).parent
    candidates = [
        project_root / "forge-gui-desktop" / "target",
        project_root.parent / "forge-repo" / "forge-gui-desktop" / "target",
        project_root.parent / "forge" / "forge-gui-desktop" / "target",
    ]
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


def _resolve_precon_dir() -> str:
    """Auto-detect the precon-decks directory."""
    project_root = Path(__file__).parent
    candidate = project_root / "precon-decks"
    if candidate.is_dir():
        return str(candidate)
    candidate = project_root.parent / "precon-decks"
    if candidate.is_dir():
        return str(candidate)
    if CFG.forge_dir:
        candidate = Path(CFG.forge_dir) / "precon-decks"
        if candidate.is_dir():
            return str(candidate)
    fallback = project_root / "precon-decks"
    fallback.mkdir(parents=True, exist_ok=True)
    return str(fallback)


def main():
    args = _parse_args()
    setup_logging(logging.DEBUG if args.verbose else logging.INFO)

    CFG.forge_jar = args.forge_jar or _resolve_forge_jar()
    CFG.forge_dir = args.forge_dir or _resolve_forge_dir()
    CFG.forge_decks_dir = args.forge_decks_dir or _resolve_forge_decks_dir()
    CFG.lab_jar = args.lab_jar or _resolve_lab_jar()
    CFG.precon_dir = args.precon_dir or _resolve_precon_dir()
    CFG.port = args.port
    CFG.ximilar_api_key = args.ximilar_key
    CFG.anthropic_api_key = args.anthropic_key

    from services.forge_runner import get_java17
    j17 = get_java17()

    log.info("Commander AI Lab — API Server v3.0.0")
    log.info(f"  Port:        {CFG.port}")
    log.info(f"  Forge JAR:   {CFG.forge_jar or 'NOT SET'}")
    log.info(f"  Forge Dir:   {CFG.forge_dir or 'NOT SET'}")
    log.info(f"  Decks Dir:   {CFG.forge_decks_dir or 'NOT SET'}")
    log.info(f"  Precon Dir:  {CFG.precon_dir or 'NOT SET'}")
    log.info(f"  Lab JAR:     {CFG.lab_jar or 'NOT SET'}")
    log.info(f"  Results:     {CFG.results_dir}")
    log.info(f"  Ximilar:     {'configured' if CFG.ximilar_api_key else 'NOT SET'}")
    log.info(f"  Anthropic:  {'configured' if CFG.anthropic_api_key else 'NOT SET'}")
    log.info(f"  Java 17:     {j17}")

    load_commander_meta()
    download_precon_database()
    init_collection_db()
    init_coach_service()

    # RAG Phase 1 + 2 are handled by _lifespan when uvicorn starts.
    # No need to call them here — doing so causes a double-run.

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=CFG.port, log_level="info")


if __name__ == "__main__":
    main()
