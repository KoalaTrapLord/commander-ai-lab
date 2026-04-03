"""Deck service: .dck parsing, deck profile saving, deck loading."""
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from models.state import CFG
from services.database import _get_db_conn, _row_to_dict

log_collect = logging.getLogger("lab.collection")

# Repo root = two levels up from this file (services/deck_service.py)
_REPO_ROOT = Path(__file__).parent.parent

# Repo-relative deck dirs always searched as fallbacks (zero-config support)
_BUILTIN_DECK_DIRS = [
    _REPO_ROOT / "precon-decks",
    _REPO_ROOT / "sample-decks",
    _REPO_ROOT / "imported-decks",
]


_TYPE_PRIORITY = ["Land", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Creature"]
_TYPE_TARGETS = {
    "Land":         [36, 38],
    "Instant":      [9, 11],
    "Sorcery":      [7, 9],
    "Artifact":     [9, 11],
    "Creature":     [20, 30],
    "Enchantment":  [5, 10],
    "Planeswalker": [0, 5],
}


def _classify_card_type(type_line: str) -> str:
    tl = type_line or ""
    for t in _TYPE_PRIORITY:
        if t in tl:
            return t
    return "Other"


_CATEGORY_MAP = {
    "Ramp":        ["search your library for a", "add one mana", "add {c}", "{t}: add"],
    "Removal":     ["destroy target", "exile target", "counter target spell"],
    "Draw":        ["draw a card", "draw two", "draw three", "draw cards"],
    "Board Wipe":  ["destroy all", "exile all", "all creatures get -"],
    "Protection":  ["hexproof", "indestructible", "shroud", "ward"],
    "Tutor":       ["search your library"],
}


def _classify_card_category(type_line: str, oracle_text: str) -> str:
    """Assign a functional category based on type_line and oracle text."""
    card_type = _classify_card_type(type_line)
    if card_type == "Land":
        return "Land"
    text = (oracle_text or "").lower()
    for cat, phrases in _CATEGORY_MAP.items():
        if any(p in text for p in phrases):
            return cat
    if card_type == "Creature":
        return "Creature"
    return card_type


def _get_deck_or_404(deck_id: int):
    conn = _get_db_conn()
    row = conn.execute("SELECT * FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Deck {deck_id} not found")
    d = dict(row)
    try:
        d["color_identity"] = json.loads(d.get("color_identity", "[]"))
    except Exception:
        d["color_identity"] = []
    return d


def _compute_deck_analysis(deck_id: int) -> dict:
    conn = _get_db_conn()
    rows = conn.execute("""
        SELECT dc.id, dc.scryfall_id, dc.card_name, dc.quantity, dc.is_commander, dc.role_tag,
               COALESCE(ce.type_line, cr.type_line, '') as type_line,
               COALESCE(ce.oracle_text, cr.oracle_text, '') as oracle_text,
               COALESCE(ce.keywords, cr.keywords, '[]') as keywords,
               COALESCE(ce.cmc, cr.cmc, 0) as cmc,
               COALESCE(ce.color_identity, cr.color_identity, '[]') as color_identity
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, oracle_text, keywords, cmc, color_identity
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        LEFT JOIN (
            SELECT name, type_line, oracle_text, keywords, cmc, color_identity
            FROM card_records GROUP BY name
        ) cr ON cr.name = dc.card_name
        WHERE dc.deck_id = ?
    """, (deck_id,)).fetchall()
    counts_by_type = {t: 0 for t in _TYPE_PRIORITY}
    counts_by_type["Other"] = 0
    mana_curve = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6+": 0}
    color_pips = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    total_cards = 0
    roles_count = {}
    for row in rows:
        r = dict(row)
        qty = r.get("quantity", 1)
        total_cards += qty
        card_type = _classify_card_type(r.get("type_line", ""))
        counts_by_type[card_type] = counts_by_type.get(card_type, 0) + qty
        cmc = int(r.get("cmc", 0) or 0)
        if card_type != "Land":
            key = str(min(cmc, 6)) if cmc < 6 else "6+"
            mana_curve[key] = mana_curve.get(key, 0) + qty
        ci_raw = r.get("color_identity", "[]")
        if isinstance(ci_raw, str):
            try:
                ci_raw = json.loads(ci_raw)
            except Exception:
                ci_raw = []
        for c in (ci_raw or []):
            if c in color_pips:
                color_pips[c] += qty
        role = r.get("role_tag") or "Unknown"
        roles_count[role] = roles_count.get(role, 0) + qty
    return {
        "total_cards": total_cards,
        "counts_by_type": counts_by_type,
        "mana_curve": mana_curve,
        "color_pips": color_pips,
        "roles": roles_count,
    }


def _check_ratio_limit(deck_id: int, card_type: str, count_to_add: int = 1) -> bool:
    analysis = _compute_deck_analysis(deck_id)
    current = analysis["counts_by_type"].get(card_type, 0)
    target_max = _TYPE_TARGETS.get(card_type, [0, 9999])[1]
    return (current + count_to_add) <= target_max


def _to_edhrec_slug(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"[',.]" , "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def parse_dck_file(deck_path: str) -> dict:
    """Parse a Forge .dck file into {name, commanders, mainboard, colorIdentity, totalCards}."""
    path = Path(deck_path)
    if not path.exists():
        return {"error": f"File not found: {deck_path}"}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    name = path.stem
    section = "main"
    commanders: dict = {}
    mainboard: dict = {}
    commander_name = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[metadata]":
            section = "metadata"; continue
        if line.startswith("Name="):
            name = line.split("=", 1)[1].strip(); continue
        if line == "[Commander]":
            section = "commander"; continue
        if line == "[Main]":
            section = "main"; continue
        if line.lower().startswith("sideboard") or line == "[Sideboard]":
            section = "sideboard"; continue
        clean = re.sub(r"\(\w+\)\s*\d*$", "", line).strip()
        clean = re.sub(r"\s*\*\.\*$", "", clean).strip()
        m = re.match(r"^(\d+)x?\s+(.+)$", clean)
        qty, card_name = (int(m.group(1)), m.group(2).strip()) if m else (1, clean)
        if not card_name:
            continue
        if section == "commander":
            commanders[card_name] = qty
            if not commander_name:
                commander_name = card_name
        elif section != "sideboard":
            mainboard[card_name] = qty
    if commander_name:
        name = f"{commander_name} - Text Import"
    total = sum(commanders.values()) + sum(mainboard.values())
    return {"name": name, "commander": commander_name, "commanders": commanders, "mainboard": mainboard, "colorIdentity": [], "totalCards": total}


def _save_profile_to_dck(profile: dict) -> Path:
    lines = ["[metadata]", f"Name={profile.get('name', 'Imported Deck')}", "", "[Commander]"]
    for name, qty in profile.get("commanders", {}).items():
        lines.append(f"{qty} {name}")
    lines += ["", "[Main]"]
    for name, qty in profile.get("mainboard", {}).items():
        lines.append(f"{qty} {name}")
    content = "\n".join(lines)
    safe_name = re.sub(r"[^a-zA-Z0-9 _-]", "", profile.get("name", "imported")).replace(" ", "_").strip()
    if not safe_name:
        safe_name = "imported_deck"
    save_dir = CFG.forge_decks_dir
    if not save_dir or not os.path.isdir(save_dir):
        save_dir = str(_REPO_ROOT / "imported-decks")
        os.makedirs(save_dir, exist_ok=True)
    out_path = Path(save_dir) / f"{safe_name}.dck"
    out_path.write_text(content, encoding="utf-8")
    log_collect.info(f" Saved .dck: {out_path}")
    return out_path


def _find_dck_file(deck_name: str) -> Optional[Path]:
    """Search known deck directories for a .dck file matching deck_name.

    Resolution order:
      1. CFG.precon_dir  (explicit CLI/env config)
      2. CFG.forge_decks_dir  (Forge user decks)
      3. FORGE_DIR/res/decks/commander  (Forge bundled commander decks)
      4. Repo-relative fallbacks: precon-decks/, sample-decks/, imported-decks/
         (always searched so precon decks work with zero configuration)

    Within each directory tries:
      a. Exact stem match  (Elven_Empire.dck)
      b. Case-insensitive fuzzy match stripping underscores/spaces
    """
    search_dirs: list[Path] = []

    # CFG-configured paths (set via CLI args)
    if CFG.precon_dir and os.path.isdir(CFG.precon_dir):
        search_dirs.append(Path(CFG.precon_dir))
    if CFG.forge_decks_dir and os.path.isdir(CFG.forge_decks_dir):
        search_dirs.append(Path(CFG.forge_decks_dir))
    if CFG.forge_dir:
        forge_cmdr = Path(CFG.forge_dir) / "res" / "decks" / "commander"
        if forge_cmdr.is_dir():
            search_dirs.append(forge_cmdr)

    # Repo-relative fallbacks -- always active so precon decks need no config
    for builtin_dir in _BUILTIN_DECK_DIRS:
        if builtin_dir.is_dir() and builtin_dir not in search_dirs:
            search_dirs.append(builtin_dir)

    target_norm = deck_name.lower().replace("_", "").replace(" ", "")

    for d in search_dirs:
        exact = d / f"{deck_name}.dck"
        if exact.exists():
            return exact
        try:
            for f in d.iterdir():
                if f.suffix.lower() == ".dck":
                    if f.stem.lower().replace("_", "").replace(" ", "") == target_norm:
                        log_collect.info(f"[DeckService] Fuzzy .dck match: '{deck_name}' -> '{f}'")
                        return f
        except OSError:
            pass

    return None


def _load_deck_cards_from_dck(dck_path: Path) -> list:
    """Parse a .dck file and return card dicts enriched with Forge card data.

    Calls lookup_forge_card() for each card so that type_line, oracle_text,
    cmc, mana_cost, power, toughness, and keywords are populated from the
    Forge cardsfolder cache.  This ensures Card.is_land() / is_creature()
    work correctly when a deck is loaded via the .dck fallback path (i.e.
    the deck is not yet in the SQLite DB).

    The Forge cache is lazy-loaded and module-level, so there is no
    per-game overhead after the first deck load.
    """
    from commander_ai_lab.sim.forge_card_loader import lookup_forge_card  # lazy to avoid circular import

    parsed = parse_dck_file(str(dck_path))
    cards = []

    def _make_card(card_name: str, qty: int, is_commander: int) -> dict:
        forge = lookup_forge_card(card_name)
        power = ""
        toughness = ""
        if forge and "/" in forge.pt:
            parts = forge.pt.split("/", 1)
            power = parts[0].strip()
            toughness = parts[1].strip()
        return {
            "card_name":      card_name,
            "name":           card_name,
            "quantity":       qty,
            "is_commander":   is_commander,
            "type_line":      forge.type_line   if forge else "",
            "oracle_text":    forge.oracle_text if forge else "",
            "cmc":            forge.cmc         if forge else 0,
            "mana_cost":      forge.mana_cost   if forge else "",
            "power":          power,
            "toughness":      toughness,
            "keywords":       json.dumps(forge.keywords) if forge else "[]",
            "color_identity": "[]",
        }

    for card_name, qty in parsed.get("commanders", {}).items():
        cards.append(_make_card(card_name, qty, 1))
    for card_name, qty in parsed.get("mainboard", {}).items():
        cards.append(_make_card(card_name, qty, 0))

    enriched = sum(1 for c in cards if c["type_line"])
    log_collect.info(
        "[DeckService] .dck load: %d cards, %d enriched from Forge cache (%s)",
        len(cards), enriched, dck_path.name,
    )
    return cards


def _load_deck_cards_by_name(deck_name: str) -> list:
    """Load cards from a deck by name, returning list of card dicts.

    Resolution order:
      1. SQLite DB  (decks built/imported via the Deck Builder UI)
      2. .dck file fallback -- searches precon_dir, forge_decks_dir,
         FORGE_DIR/res/decks/commander, and repo-relative precon-decks/
         sample-decks/ so precon decks work without any configuration.
    """
    # -- 1. DB lookup --
    conn = _get_db_conn()
    deck_row = conn.execute("SELECT id FROM decks WHERE name = ?", (deck_name,)).fetchone()
    if deck_row:
        deck_id = deck_row[0]
        rows = conn.execute("""
            SELECT dc.card_name, dc.quantity, dc.is_commander, dc.role_tag, dc.scryfall_id,
                   COALESCE(ce.type_line, cr.type_line, '') as type_line,
                   COALESCE(ce.oracle_text, cr.oracle_text, '') as oracle_text,
                   COALESCE(ce.cmc, cr.cmc, 0) as cmc,
                   COALESCE(ce.color_identity, cr.color_identity, '[]') as color_identity,
                   COALESCE(ce.mana_cost, '', '') as mana_cost,
                   COALESCE(ce.power, '', '') as power,
                   COALESCE(ce.toughness, '', '') as toughness,
                   COALESCE(ce.keywords, cr.keywords, '[]') as keywords
            FROM deck_cards dc
            LEFT JOIN (
                SELECT scryfall_id, type_line, oracle_text, cmc, color_identity, mana_cost, power, toughness, keywords
                FROM collection_entries GROUP BY scryfall_id
            ) ce ON ce.scryfall_id = dc.scryfall_id
            LEFT JOIN (
                SELECT name, type_line, oracle_text, cmc, color_identity, keywords
                FROM card_records GROUP BY name
            ) cr ON cr.name = dc.card_name
            WHERE dc.deck_id = ?
        """, (deck_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    # -- 2. .dck file fallback --
    dck_path = _find_dck_file(deck_name)
    if dck_path:
        log_collect.info(
            f"[DeckService] '{deck_name}' not in DB -- loading from .dck file: {dck_path}"
        )
        return _load_deck_cards_from_dck(dck_path)

    log_collect.warning(f"[DeckService] Deck '{deck_name}' not found in DB or any .dck search path.")
    return []


log_deckgen = logging.getLogger("commander_ai_lab.deckgen")


def _build_dck_lines(
    deck_name: str,
    commander_name: str,
    cards: list[dict],
    *,
    resolve_substitutes: bool = False,
) -> list[str]:
    """Build Forge .dck file lines from deck name, commander, and card list."""
    lines: list[str] = [
        "[metadata]",
        f"Name={deck_name}",
        "",
        "[Commander]",
        f"1 {commander_name}",
        "",
        "[Main]",
    ]
    for card in cards:
        cname = card.get("name", "")
        if resolve_substitutes:
            if card.get("status") == "substituted" and card.get("selected_substitute"):
                cname = card["selected_substitute"]
        if cname and cname != commander_name:
            lines.append(f"{card.get('count', card.get('quantity', 1))} {cname}")
    return lines


def _write_dck_file(
    deck_name: str,
    commander_name: str,
    cards: list[dict],
    decks_dir: str | None = None,
    *,
    fallback_id: int | str = 0,
    resolve_substitutes: bool = False,
) -> str | None:
    """Write a Forge .dck file to decks_dir. Returns path on success, None otherwise."""
    if not decks_dir:
        decks_dir = CFG.forge_decks_dir
    if not decks_dir or not os.path.isdir(decks_dir):
        return None

    safe_name = re.sub(r"[^a-zA-Z0-9_\-\s]", "", deck_name).strip().replace(" ", "_")
    if not safe_name:
        safe_name = f"Deck_{fallback_id}"

    dck_path = os.path.join(decks_dir, f"{safe_name}.dck")
    lines = _build_dck_lines(
        deck_name, commander_name, cards,
        resolve_substitutes=resolve_substitutes,
    )
    with open(dck_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    log_deckgen.info(f" Exported .dck: {dck_path}")
    return dck_path
