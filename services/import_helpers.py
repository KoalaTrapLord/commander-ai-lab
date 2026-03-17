"""URL-based deck import helpers: Archidekt, EDHREC, text decklist parsing."""
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.request import urlopen, Request

from models.state import CFG
from services.deck_service import _to_edhrec_slug
from services.scryfall import _API_HEADERS

log_collect = logging.getLogger("commander_ai_lab.collection")


def _http_get(url: str) -> str:
    with urlopen(Request(url, headers=_API_HEADERS), timeout=30) as resp:
        return resp.read().decode("utf-8")


def _fetch_archidekt_deck(deck_id: str) -> dict:
    url = f"https://archidekt.com/api/decks/{deck_id}/"
    data = json.loads(_http_get(url))
    profile = {
        "name": data.get("name", f"Archidekt {deck_id}"),
        "commander": None,
        "source": "Archidekt",
        "sourceUrl": f"https://archidekt.com/decks/{deck_id}",
        "commanders": {},
        "mainboard": {},
        "colorIdentity": [],
        "totalCards": 0,
    }
    for card_entry in data.get("cards", []):
        qty = card_entry.get("quantity", 1)
        oracle = card_entry.get("card", {}).get("oracleCard", {})
        card_name = oracle.get("name", "Unknown")
        is_commander = any(c.lower() == "commander" for c in card_entry.get("categories", []))
        if is_commander:
            profile["commanders"][card_name] = qty
            if not profile["commander"]:
                profile["commander"] = card_name
                if oracle.get("colorIdentity"):
                    profile["colorIdentity"] = oracle["colorIdentity"]
        else:
            profile["mainboard"][card_name] = qty
    profile["totalCards"] = sum(profile["commanders"].values()) + sum(profile["mainboard"].values())
    if not profile["name"] or profile["name"] == f"Archidekt {deck_id}":
        profile["name"] = f"{profile['commander']} \u2014 Archidekt"
    return profile


def _fetch_edhrec_average(commander_name: str) -> dict:
    slug = _to_edhrec_slug(commander_name)
    url = f"https://json.edhrec.com/pages/average-decks/{slug}.json"
    data = json.loads(_http_get(url))
    container = data.get("container", {})
    json_dict = container.get("json_dict", {})
    card_info = json_dict.get("card", {})
    real_name = card_info.get("name", commander_name.title())
    profile = {
        "name": f"{real_name} \u2014 EDHREC Average",
        "commander": real_name,
        "source": "EDHREC Average",
        "sourceUrl": f"https://edhrec.com/average-decks/{slug}",
        "commanders": {real_name: 1},
        "mainboard": {},
        "colorIdentity": card_info.get("color_identity", []),
        "sampleSize": data.get("num_decks_avg"),
        "totalCards": 0,
    }
    for cl in json_dict.get("cardlists", []):
        for cv in cl.get("cardviews", []):
            card_name = cv.get("name", "")
            if card_name:
                profile["mainboard"][card_name] = 1
    archidekt_data = data.get("archidekt", [])
    if archidekt_data:
        basic_names = []
        for cl in json_dict.get("cardlists", []):
            if cl.get("tag") == "basics":
                for cv in cl.get("cardviews", []):
                    basic_names.append(cv.get("name", ""))
        basic_quantities = [e["q"] for e in archidekt_data if e.get("q", 1) > 1]
        for i, name in enumerate(basic_names):
            if i < len(basic_quantities):
                profile["mainboard"][name] = basic_quantities[i]
    profile["totalCards"] = sum(profile["commanders"].values()) + sum(profile["mainboard"].values())
    return profile


def _import_from_url(url: str) -> dict:
    url = url.strip()
    if "archidekt.com/decks/" in url:
        m = re.search(r"/decks/(\d+)", url)
        if not m:
            raise ValueError("Could not parse Archidekt deck ID from URL")
        return _fetch_archidekt_deck(m.group(1))
    if "edhrec.com/average-decks/" in url:
        slug = re.search(r"/average-decks/([^/?#]+)", url).group(1)
        return _fetch_edhrec_average(slug.replace("-", " "))
    if "edhrec.com/commanders/" in url:
        slug = re.search(r"/commanders/([^/?#]+)", url).group(1)
        return _fetch_edhrec_average(slug.replace("-", " "))
    raise ValueError(f"Unsupported URL: {url}. Supported: archidekt.com/decks/..., edhrec.com/average-decks/..., edhrec.com/commanders/...")


def _parse_text_decklist(text: str, commander_override: str = None) -> dict:
    profile = {
        "name": "Text Import",
        "commander": None,
        "source": "Text Import",
        "sourceUrl": None,
        "commanders": {},
        "mainboard": {},
        "totalCards": 0,
    }
    section = "main"
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        if line.lower().startswith("commander") or line == "[Commander]":
            section = "commander"; continue
        if line.lower().startswith("main") or line.lower().startswith("deck") or line == "[Main]":
            section = "main"; continue
        if line.lower().startswith("sideboard") or line == "[Sideboard]":
            section = "sideboard"; continue
        clean = re.sub(r"\(\w+\)\s*\d*$", "", line).strip()
        clean = re.sub(r"\s*\*.*$", "", clean).strip()
        m = re.match(r"^(\d+)x?\s+(.+)$", clean)
        qty, card_name = (int(m.group(1)), m.group(2).strip()) if m else (1, clean)
        if not card_name:
            continue
        if section == "commander":
            profile["commanders"][card_name] = qty
            if not profile["commander"]:
                profile["commander"] = card_name
        elif section != "sideboard":
            profile["mainboard"][card_name] = qty
    if commander_override:
        profile["commander"] = commander_override
        if not profile["commanders"]:
            if commander_override in profile["mainboard"]:
                qty = profile["mainboard"].pop(commander_override)
                profile["commanders"][commander_override] = qty
            else:
                profile["commanders"][commander_override] = 1
    if profile["commander"]:
        profile["name"] = f"{profile['commander']} \u2014 Text Import"
    profile["totalCards"] = sum(profile["commanders"].values()) + sum(profile["mainboard"].values())
    return profile


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


# EDHREC in-memory cache
_edhrec_cache: dict = {}
_EDHREC_CACHE_TTL = 3600


def _edhrec_cache_get(key: str):
    entry = _edhrec_cache.get(key)
    if not entry:
        return None
    if time.time() - entry["ts"] > _EDHREC_CACHE_TTL:
        del _edhrec_cache[key]
        return None
    return entry["data"]


def _edhrec_cache_set(key: str, data):
    _edhrec_cache[key] = {"data": data, "ts": time.time()}
