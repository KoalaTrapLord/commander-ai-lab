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
               ce.type_line, ce.oracle_text, ce.keywords, ce.cmc, ce.color_identity
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, oracle_text, keywords, cmc, color_identity
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
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
        "total_cards": total_cards,
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
        save_dir = os.path.join(Path(__file__).parent.parent, "imported-decks")
        os.makedirs(save_dir, exist_ok=True)
    out_path = Path(save_dir) / f"{safe_name}.dck"
    out_path.write_text(content, encoding="utf-8")
    log_collect.info(f" Saved .dck: {out_path}")
    return out_path


def _load_deck_cards_by_name(deck_name: str) -> list:
    """Load cards from a deck by name, returning list of card dicts."""
    conn = _get_db_conn()
    deck_row = conn.execute("SELECT id FROM decks WHERE name = ?", (deck_name,)).fetchone()
    if not deck_row:
        return []
    deck_id = deck_row[0]
    rows = conn.execute("""
        SELECT dc.card_name, dc.quantity, dc.is_commander, dc.role_tag, dc.scryfall_id,
               ce.type_line, ce.oracle_text, ce.cmc, ce.color_identity, ce.mana_cost
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, oracle_text, cmc, color_identity, mana_cost
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
    """, (deck_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]