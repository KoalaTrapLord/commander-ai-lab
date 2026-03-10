"""
Card Scanner — Recognition Pipeline (Ximilar Visual AI)
═══════════════════════════════════════════════════════════

Orchestrates the full scan workflow using the Ximilar Collectibles
TCG Identification API for card recognition:
  1. Send image bytes to Ximilar API
  2. Parse identified cards (name, set, number, rarity, links)
  3. Optionally enrich with Scryfall for scryfall_id + image URI
  4. Return structured results

No local OCR or OpenCV needed — all recognition is done by the
Ximilar cloud API using visual AI.
"""
from typing import Callable, Optional

from .ximilar_client import identify_cards, XimilarResult


# ── Data structures ──────────────────────────────────────────

class ScanResult:
    """Result for a single recognized card."""
    __slots__ = ("raw_ocr", "matched_name", "set_code", "scryfall_id",
                 "confidence", "image_uri", "error", "corrected_name",
                 "collector_number", "rarity", "tcgplayer_url")

    def __init__(self, raw_ocr: str = "", matched_name: str = "",
                 set_code: str = "", scryfall_id: str = "",
                 confidence: str = "low", image_uri: str = "",
                 error: str = "", corrected_name: str = "",
                 collector_number: str = "", rarity: str = "",
                 tcgplayer_url: str = ""):
        self.raw_ocr = raw_ocr
        self.matched_name = matched_name
        self.set_code = set_code
        self.scryfall_id = scryfall_id
        self.confidence = confidence     # "high" | "medium" | "low"
        self.image_uri = image_uri       # Scryfall card image for preview
        self.error = error
        self.corrected_name = corrected_name
        self.collector_number = collector_number
        self.rarity = rarity
        self.tcgplayer_url = tcgplayer_url

    def to_dict(self) -> dict:
        return {
            "raw_ocr": self.raw_ocr,
            "corrected_name": self.corrected_name,
            "matched_name": self.matched_name,
            "set_code": self.set_code,
            "scryfall_id": self.scryfall_id,
            "confidence": self.confidence,
            "image_uri": self.image_uri,
            "error": self.error,
            "collector_number": self.collector_number,
            "rarity": self.rarity,
            "tcgplayer_url": self.tcgplayer_url,
        }


# ── Public API ───────────────────────────────────────────────

def scan_single(image_bytes: bytes,
                scryfall_lookup: Callable[[str], Optional[dict]],
                ximilar_api_key: str = "") -> ScanResult:
    """
    Scan a single card image using Ximilar Visual AI.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG)
        scryfall_lookup: Callback to look up a card on Scryfall (for scryfall_id + image)
        ximilar_api_key: Ximilar API token

    Returns:
        ScanResult with identified card info
    """
    if not ximilar_api_key:
        return ScanResult(error="Ximilar API key not configured. Set it in lab config.")

    # Call Ximilar API with analyze_all=False for single card
    ximilar_results = identify_cards(image_bytes, ximilar_api_key, analyze_all=False)

    if not ximilar_results:
        return ScanResult(error="Ximilar returned no results")

    # Take the first (best) result
    xr = ximilar_results[0]

    if xr.error and not xr.name:
        return ScanResult(error=xr.error)

    return _ximilar_to_scan_result(xr, scryfall_lookup)


def scan_multi(image_bytes: bytes,
               scryfall_lookup: Callable[[str], Optional[dict]],
               ximilar_api_key: str = "") -> list:
    """
    Scan an image containing multiple cards using Ximilar Visual AI.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG)
        scryfall_lookup: Callback to look up a card on Scryfall
        ximilar_api_key: Ximilar API token

    Returns:
        List of ScanResult objects, one per detected card
    """
    if not ximilar_api_key:
        return [ScanResult(error="Ximilar API key not configured. Set it in lab config.")]

    # Call Ximilar API with analyze_all=True for multi-card detection
    ximilar_results = identify_cards(image_bytes, ximilar_api_key, analyze_all=True)

    if not ximilar_results:
        return [ScanResult(error="Ximilar returned no results")]

    results = []
    for xr in ximilar_results:
        if xr.error and not xr.name:
            results.append(ScanResult(error=xr.error))
        else:
            results.append(_ximilar_to_scan_result(xr, scryfall_lookup))

    return results


# ── Internal helpers ─────────────────────────────────────────

def _ximilar_to_scan_result(xr: XimilarResult,
                             scryfall_lookup: Callable[[str], Optional[dict]]) -> ScanResult:
    """
    Convert a Ximilar identification result to a ScanResult,
    enriching with Scryfall data for scryfall_id and image URI.
    """
    result = ScanResult(
        raw_ocr=xr.full_name or xr.name,
        corrected_name=xr.name,
        matched_name=xr.name,
        set_code=xr.set_code,
        collector_number=xr.card_number,
        rarity=xr.rarity,
        tcgplayer_url=xr.tcgplayer_url,
    )

    # Map Ximilar confidence (0.0–1.0) to our levels
    if xr.confidence >= 0.7:
        result.confidence = "high"
    elif xr.confidence >= 0.4:
        result.confidence = "medium"
    else:
        result.confidence = "low"

    # Try to get scryfall_id and image URI via Scryfall lookup
    # First try exact set/number lookup, then fuzzy name
    scryfall_data = None

    if xr.name:
        try:
            scryfall_data = scryfall_lookup(xr.name)
        except Exception as e:
            print(f"    [SCAN] Scryfall lookup failed for '{xr.name}': {e}")

    if scryfall_data and scryfall_data.get("object") != "error":
        result.scryfall_id = scryfall_data.get("id", "")
        result.matched_name = scryfall_data.get("name", xr.name)

        # Get card image for preview
        image_uris = scryfall_data.get("image_uris", {})
        if not image_uris and scryfall_data.get("card_faces"):
            image_uris = scryfall_data["card_faces"][0].get("image_uris", {})
        result.image_uri = image_uris.get("normal", image_uris.get("small", ""))

        # Update set_code from Scryfall if available
        if not result.set_code:
            result.set_code = scryfall_data.get("set", "")
    else:
        # No Scryfall match — use Scryfall URL from Ximilar if available
        if xr.scryfall_url:
            # Extract image from scryfall URL pattern
            # e.g., https://scryfall.com/card/m11/149/lightning-bolt
            result.image_uri = ""  # Will be fetched by frontend via scryfall_id
        print(f"    [SCAN] No Scryfall match for '{xr.name}' — using Ximilar data only")

    return result
