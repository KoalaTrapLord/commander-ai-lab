# Routes Wiring — Final Integration Step

All route files are in `routes/`. To activate them, add **two lines** to `lab_api.py`:

## Option A — Inline (recommended)

Add this block immediately after the `app.add_middleware(CORSMiddleware, ...)` call
(around line 145 in the current file):

```python
# ── Route Package Wiring ──────────────────────────────────────
from routes import _autoload as _routes_autoload
_routes_autoload.register_startup(app)
```

That's it. `register_startup(app)` attaches an `@app.on_event('startup')` hook
that imports `routes._wire`, which:
1. Calls `_register_shared()` with every symbol from `lab_api.py`
2. Calls `app.include_router()` for all 5 routers

## Option B — Bottom of file

Alternatively, add this at the very bottom of `lab_api.py`
(after all functions/endpoints are defined, before `if __name__ == '__main__'`):

```python
# ── Wire routes package (must be after all symbols are defined) ──
import routes._wire  # noqa — side-effect: registers shared state + mounts routers
```

Option B is slightly more efficient (no startup delay) but requires that all
functions referenced in `routes/_wire.py` exist at module level before the
import runs.

## Route Files Summary

| File | Prefix | Endpoints |
|---|---|---|
| `routes/lab.py` | `/api/lab` | start, status, result, decks, history, profiles, analytics, trends, log |
| `routes/import_routes.py` | `/api/lab` | import/url, import/text, meta/* |
| `routes/precon.py` | `/api/lab` | precons/*, precons/install, precons/refresh |
| `routes/collection.py` | *(none)* | /api/collection/*, /api/cache/scryfall/* |
| `routes/deckbuilder.py` | `/api/decks` | CRUD, cards, analysis, recommendations, export |

## Shared Registry

`routes/shared.py` holds a `_registry` dict populated by `routes/_wire.py`.
Every router calls `routes.shared.get('symbol_name')` to access shared state
without circular imports.
