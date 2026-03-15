"""
Commander AI Lab — Web Server Package (Phase 5)

Exposes:
  create_app()  — FastAPI application factory
  run()         — convenience entry point (uvicorn)
"""
from commander_ai_lab.web.app import create_app, run

__all__ = ["create_app", "run"]
