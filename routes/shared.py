"""
routes/shared.py
================
Single source of truth for objects that every router module needs:
  - CFG / Config class
  - Logging setup + named loggers
  - In-memory state (active_batches, COMMANDER_META, PRECON_INDEX, AI_PROFILES)
  - All Pydantic request/response models
  - DB helpers (_get_db_conn, init_collection_db, COLLECTION_DB_PATH)
  - Scryfall cache (_scryfall_cache, _enrich_from_scryfall, _fetch_scryfall_api)
  - Utility helpers (_row_to_dict, _add_image_url, _snake_to_camel,
                     _classify_card_type, _detect_card_roles,
                     _build_collection_filters, _get_deck_or_404,
                     _compute_deck_analysis, _to_edhrec_slug,
                     _save_profile_to_dck, _parse_finish, _parse_text_line,
                     _parse_csv_content, _auto_infer_mapping,
                     get_java17, build_java_command)
  - EDHREC in-memory cache helpers (_edhrec_cache_get, _edhrec_cache_set)

Import pattern in every router::

    from routes.shared import (
        CFG, log, active_batches, ...
    )
"""

# Re-export everything from lab_api so routers can do:
#   from routes.shared import CFG, log, active_batches, ...
# Without circular imports we simply import at the module level.
# lab_api.py must import routers AFTER defining these symbols.

# This file intentionally left as a thin re-export shim.
# The actual definitions live in lab_api.py until the full
# extraction migration is complete (Issues #16-#25).
#
# Once each router is extracted, the definitions will move here
# and lab_api.py will import from routes.shared instead.

from __future__ import annotations  # noqa: F401 — forward refs for Pydantic

# Populated by lab_api.py at import time via _register_shared()
_registry: dict = {}


def _register_shared(**kwargs):
    """Called once by lab_api.py after all shared symbols are defined.
    Makes them available to routers via get()."""
    _registry.update(kwargs)


def get(name: str):
    """Retrieve a shared object by name. Raises KeyError if not registered."""
    if name not in _registry:
        raise KeyError(
            f"routes.shared: '{name}' not registered. "
            "Ensure lab_api.py called _register_shared() before including routers."
        )
    return _registry[name]
