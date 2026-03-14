"""
routes/_autoload.py
===================
Optional zero-touch bootstrap for the routes package.

If you don't want to modify lab_api.py at all, add one line
anywhere after `app = FastAPI(...)` in lab_api.py::

    from routes import _autoload  # noqa  — registers routers on startup

This module registers a FastAPI startup event that imports routes._wire,
which in turn calls _register_shared() and app.include_router() for all
five routers.
"""
from __future__ import annotations


def register_startup(app):
    """Attach the router-wiring startup event to a FastAPI app instance."""

    @app.on_event("startup")
    async def _wire_routers():
        import routes._wire  # noqa — side-effect: registers shared + mounts routers
