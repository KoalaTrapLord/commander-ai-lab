"""
Card Scanner — Ximilar Visual AI Client
═════════════════════════════════════════

Calls the Ximilar Collectibles TCG Identification API
to recognize MTG cards from images using visual AI.

API Endpoint: POST https://api.ximilar.com/collectibles/v2/tcg_id
Auth: Token-based (Authorization: Token <api_key>)
"""
import base64
import json
from typing import Optional, List
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

XIMILAR_ENDPOINT = "https://api.ximilar.com/collectibles/v2/tcg_id"


class XimilarResult:
    """Result for a single card identified by Ximilar."""
    __slots__ = (
        "name", "full_name", "set_name", "set_code",
        "card_number", "rarity", "year",
        "tcgplayer_url", "scryfall_url", "ebay_url",
        "confidence", "error",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot, ""))
        if "confidence" not in kwargs:
            self.confidence = 0.0
        if "error" not in kwargs:
            self.error = ""

    def to_dict(self) -> dict:
        return {s: getattr(self, s) for s in self.__slots__}


def identify_cards(image_bytes: bytes, api_key: str,
                   analyze_all: bool = True) -> List[XimilarResult]:
    """
    Send image bytes to Ximilar TCG identification API.

    Args:
        image_bytes: Raw image bytes (JPEG, PNG, etc.)
        api_key: Ximilar API token
        analyze_all: If True, detect and identify ALL cards in the image.
                     If False, identify only the dominant card.

    Returns:
        List of XimilarResult objects, one per detected card.
    """
    if not api_key:
        return [XimilarResult(error="No Ximilar API key configured")]

    # Encode image to base64
    b64_data = base64.b64encode(image_bytes).decode("ascii")

    # Build request body
    body = {
        "records": [
            {"_base64": b64_data}
        ],
    }
    if analyze_all:
        body["analyze_all"] = True

    payload = json.dumps(body).encode("utf-8")

    # Build HTTP request
    req = Request(
        XIMILAR_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {api_key}",
            "User-Agent": "CommanderAILab/1.0",
        },
        method="POST",
    )

    try:
        print(f"    [XIMILAR] Sending {len(image_bytes):,} bytes to API (analyze_all={analyze_all})")
        with urlopen(req, timeout=60) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return [XimilarResult(error=f"Ximilar API error {e.code}: {error_body[:500]}")]
    except URLError as e:
        return [XimilarResult(error=f"Ximilar API connection error: {e.reason}")]
    except Exception as e:
        return [XimilarResult(error=f"Ximilar API request failed: {e}")]

    # Parse response
    return _parse_response(resp_data)


def _parse_response(resp_data: dict) -> List[XimilarResult]:
    """
    Parse the Ximilar API response into XimilarResult objects.

    Response structure:
    {
      "records": [
        {
          "_objects": [
            {
              "_identification": {
                "best_match": {
                  "name": "Lightning Bolt",
                  "full_name": "Lightning Bolt (M11) #149",
                  "set": "Magic 2011",
                  "set_code": "m11",
                  "card_number": "149",
                  "rarity": "common",
                  "year": "2010",
                  "links": {
                    "tcgplayer": "https://...",
                    "scryfall": "https://...",
                    "ebay": "https://..."
                  }
                },
                "top_k": [...]
              }
            },
            ...
          ]
        }
      ]
    }
    """
    results = []
    records = resp_data.get("records", [])

    if not records:
        return [XimilarResult(error="Ximilar returned no records")]

    for record in records:
        objects = record.get("_objects", [])

        if not objects:
            # Check if there's a record-level identification (single card mode)
            ident = record.get("_identification")
            if ident:
                result = _parse_identification(ident)
                if result:
                    results.append(result)
            else:
                results.append(XimilarResult(error="No cards detected in image"))
            continue

        for obj in objects:
            ident = obj.get("_identification")
            if not ident:
                results.append(XimilarResult(error="Object detected but not identified"))
                continue

            result = _parse_identification(ident)
            if result:
                results.append(result)

    if not results:
        results.append(XimilarResult(error="Ximilar could not identify any cards"))

    print(f"    [XIMILAR] Identified {len(results)} card(s)")
    for r in results:
        if r.name:
            print(f"    [XIMILAR]   - {r.name} ({r.set_code}) conf={r.confidence:.2f}")
        elif r.error:
            print(f"    [XIMILAR]   - ERROR: {r.error}")

    return results


def _parse_identification(ident: dict) -> Optional[XimilarResult]:
    """Parse a single _identification block."""
    best = ident.get("best_match")
    if not best:
        return XimilarResult(error="No best match in identification")

    links = best.get("links", {})
    prob = best.get("prob", 0.0)

    return XimilarResult(
        name=best.get("name", ""),
        full_name=best.get("full_name", ""),
        set_name=best.get("set", ""),
        set_code=best.get("set_code", ""),
        card_number=str(best.get("card_number", "")),
        rarity=best.get("rarity", ""),
        year=str(best.get("year", "")),
        tcgplayer_url=links.get("tcgplayer", ""),
        scryfall_url=links.get("scryfall", ""),
        ebay_url=links.get("ebay", ""),
        confidence=float(prob) if prob else 0.0,
    )
