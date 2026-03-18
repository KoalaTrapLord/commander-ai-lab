"""
Commander AI Lab — FastAPI Application Factory (Phase 5)
=========================================================
Creates and wires the FastAPI application:
  - REST API router  (/api/v1/...)
  - WebSocket router (/ws/game/{game_id})
  - Scryfall art proxy (/api/v1/art/{card_name})
  - Static file mount  (/static  -> web/static/)
  - CORS middleware for browser dev server

Usage::

    uvicorn commander_ai_lab.web.app:app --reload --port 8000
    # or programmatically:
    from commander_ai_lab.web.app import create_app
    app = create_app()
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from commander_ai_lab.web.routers.api    import router as api_router
from commander_ai_lab.web.routers.ws     import router as ws_router
from commander_ai_lab.web.routers.art    import router as art_router

# Prefer the React build output; fall back to legacy static dir
_FRONTEND_DIST = Path(__file__).parents[3] / "frontend" / "dist"
_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    allow_origins: list[str] | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    """
    FastAPI application factory.

    Args:
        allow_origins:  CORS origins. Defaults to ["*"] (dev mode).
        static_dir:     Path to static files. Defaults to web/static/.
    """
    app = FastAPI(
        title="Commander AI Lab",
        version="0.5.0",
        description="4-player Commander AI game server with WebSocket game channel.",
    )

    # CORS
    origins = allow_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(api_router,  prefix="/api/v1")
    app.include_router(ws_router)                          # /ws/game/{game_id}
    app.include_router(art_router,  prefix="/api/v1")

    # Static files (web client) — prefer React build, fall back to legacy
    sd = static_dir or (_FRONTEND_DIST if _FRONTEND_DIST.exists() else _STATIC_DIR)
    if sd.exists():
        app.mount("/static", StaticFiles(directory=str(sd), html=True), name="static")

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "version": "0.5.0"}

    # SPA catch-all: serve index.html for non-API, non-WS paths
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        index = sd / "index.html"
        if index.exists():
            return FileResponse(str(index))
        # Fall back to legacy static
        legacy = _STATIC_DIR / "index.html"
        return FileResponse(str(legacy))

    return app


# Module-level app instance (for uvicorn)
app = create_app()


def run(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Convenience entry point."""
    try:
        import uvicorn
    except ImportError:
        raise RuntimeError("uvicorn is required: pip install uvicorn[standard]")
    uvicorn.run(
        "commander_ai_lab.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    run(reload=True)
