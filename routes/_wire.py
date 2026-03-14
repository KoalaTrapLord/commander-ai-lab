"""
routes/_wire.py
===============
Wires the routes package into lab_api.py.

This module is imported ONCE at the bottom of lab_api.py after all
symbols (CFG, app, helper functions, endpoint functions) are defined.

It does two things:
  1. Calls routes.shared._register_shared() so every router can access
     shared state via routes.shared.get().
  2. Calls app.include_router() for every APIRouter defined in the
     routes/ package.

Keeping wiring here means lab_api.py only needs one new line:

    import routes._wire  # noqa — side-effect import

"""
from __future__ import annotations

import lab_api as _api  # import the main module to grab its symbols

from routes.shared import _register_shared
from routes import (
    collection,
    deckbuilder,
    import_routes,
    lab,
    precon,
)

# ------------------------------------------------------------------
# 1. Register shared symbols so routers can call routes.shared.get()
# ------------------------------------------------------------------
_register_shared(
    # Config + app
    CFG=_api.CFG,
    app=_api.app,

    # Loggers
    log=_api.log,
    log_batch=_api.log_batch,
    log_sim=_api.log_sim,
    log_coach=_api.log_coach,
    log_deckgen=_api.log_deckgen,
    log_collect=_api.log_collect,
    log_scan=_api.log_scan,
    log_ml=_api.log_ml,
    log_cache=_api.log_cache,
    log_pplx=_api.log_pplx,

    # In-memory state
    active_batches=_api.active_batches,
    COMMANDER_META=_api.COMMANDER_META,
    PRECON_INDEX=_api.PRECON_INDEX,
    PRECON_DIR=_api.PRECON_DIR,
    AI_PROFILES=_api.AI_PROFILES,

    # DB
    COLLECTION_DB_PATH=_api.COLLECTION_DB_PATH,
    init_collection_db=_api.init_collection_db,

    # Precon helpers
    download_precon_database=_api.download_precon_database,

    # Scryfall helpers
    _enrich_from_scryfall=_api._enrich_from_scryfall,
    _fetch_scryfall_api=_api._fetch_scryfall_api,

    # Utility helpers
    _row_to_dict=_api._row_to_dict,
    _add_image_url=_api._add_image_url,
    _snake_to_camel=_api._snake_to_camel,
    _classify_card_type=_api._classify_card_type,
    _detect_card_roles=_api._detect_card_roles,
    _build_collection_filters=_api._build_collection_filters,
    _get_deck_or_404=_api._get_deck_or_404,
    _compute_deck_analysis=_api._compute_deck_analysis,
    _to_edhrec_slug=_api._to_edhrec_slug,
    _save_profile_to_dck=_api._save_profile_to_dck,
    _parse_finish=_api._parse_finish,
    _parse_text_line=_api._parse_text_line,
    _parse_csv_content=_api._parse_csv_content,
    _auto_infer_mapping=_api._auto_infer_mapping,
    get_java17=_api.get_java17,
    build_java_command=_api.build_java_command,

    # Deck import helpers
    _import_from_url=_api._import_from_url,
    _parse_text_decklist=_api._parse_text_decklist,
    _fetch_edhrec_average=_api._fetch_edhrec_average,

    # Endpoint functions (delegated by thin router wrappers)
    start_batch=_api.start_batch,
    start_batch_deepseek=_api.start_batch_deepseek,
    get_status=_api.get_status,
    get_result=_api.get_result,
    list_decks=_api.list_decks,
    list_history=_api.list_history,
    list_profiles=_api.list_profiles,
    get_profile=_api.get_profile,
    analyze_deck=_api.analyze_deck,
    get_deck_trends=_api.get_deck_trends,
    get_log=_api.get_log,
    get_debug_log=_api.get_debug_log,
    list_collection=_api.list_collection,
    export_collection=_api.export_collection,
    collection_sets=_api.collection_sets,
    collection_keywords=_api.collection_keywords,
    import_collection=_api.import_collection,
    get_collection_card=_api.get_collection_card,
    update_collection_card=_api.update_collection_card,
    scryfall_cache_stats=_api.scryfall_cache_stats,
    scryfall_cache_clear=_api.scryfall_cache_clear,
    scryfall_cache_evict_expired=_api.scryfall_cache_evict_expired,
    create_deck=_api.create_deck,
    list_decks_db=_api.list_decks_db,
    get_deck=_api.get_deck,
    update_deck=_api.update_deck,
    delete_deck=_api.delete_deck,
    delete_all_decks=_api.delete_all_decks,
    get_deck_cards=_api.get_deck_cards,
    add_deck_card=_api.add_deck_card,
    remove_deck_card=_api.remove_deck_card,
    patch_deck_card=_api.patch_deck_card,
    deck_analysis=_api.deck_analysis,
    recommend_from_collection=_api.recommend_from_collection,
    deck_edh_recs=_api.deck_edh_recs,
    bulk_add_cards=_api.bulk_add_cards,
    bulk_add_recommended=_api.bulk_add_recommended,
    export_deck_to_sim=_api.export_deck_to_sim,
)

# ------------------------------------------------------------------
# 2. Mount all routers onto the FastAPI app
# ------------------------------------------------------------------
_api.app.include_router(lab.router)
_api.app.include_router(import_routes.router)
_api.app.include_router(precon.router)
_api.app.include_router(collection.router)
_api.app.include_router(deckbuilder.router)
