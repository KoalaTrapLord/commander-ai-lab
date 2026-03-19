"""
FastAPI + CLI entrypoint for the Commander AI Deck Builder.

Run with:
    uvicorn commander_ai_lab.deck_builder.main:app --reload

Or via CLI:
    python -m commander_ai_lab.deck_builder.main --commander "Atraxa, Praetors' Voice"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .core.models import BuildRequest, BuildResult
from .pipeline.build_deck import build_deck

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Commander AI Deck Builder",
    version="0.1.0",
    description="Generate optimised 99-card Commander decks using local Ollama AI.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/build", response_model=BuildResult)
async def api_build_deck(request: BuildRequest):
    """Build a Commander deck from the given request."""
    try:
        result = build_deck(request)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unhandled error during deck build")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def cli() -> None:
    """Minimal CLI wrapper around build_deck."""
    parser = argparse.ArgumentParser(description="Commander AI Deck Builder CLI")
    parser.add_argument("--commander", required=True, help="Commander card name")
    parser.add_argument(
        "--collection",
        default=None,
        help="Path to collection CSV (optional)",
    )
    parser.add_argument(
        "--collection-only",
        action="store_true",
        default=False,
        help="Only use cards from collection",
    )
    parser.add_argument(
        "--model",
        default="gpt-oss:20b",
        help="Ollama model name (default: gpt-oss:20b)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: stdout)",
    )
    args = parser.parse_args()

    # Load collection if provided
    collection_names: list[str] | None = None
    if args.collection:
        import csv
        from pathlib import Path

        path = Path(args.collection)
        if not path.exists():
            print(f"Error: collection file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            name_col = "Name" if "Name" in (reader.fieldnames or []) else "name"
            collection_names = [row[name_col] for row in reader if row.get(name_col)]

    request = BuildRequest(
        commander_name=args.commander,
        collection_names=collection_names,
        collection_only=args.collection_only,
    )

    logger.info("Building deck for %s …", args.commander)
    result = build_deck(request)

    output = result.model_dump_json(indent=2)
    if args.output:
        from pathlib import Path as P

        P(args.output).write_text(output, encoding="utf-8")
        logger.info("Deck written to %s", args.output)
    else:
        print(output)

    if result.warnings:
        for w in result.warnings:
            logger.warning("⚠  %s", w)


if __name__ == "__main__":
    cli()
