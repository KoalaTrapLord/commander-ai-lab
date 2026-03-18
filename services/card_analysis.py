"""Card role detection, type classification, and deck composition analysis."""
import json
import re


def _detect_card_roles(oracle_text: str, type_line: str, keywords) -> list:
    roles = []
    ot = (oracle_text or "").lower()
    tl = (type_line or "").lower()
    kw_raw = keywords or []
    if isinstance(kw_raw, str):
        try:
            kw_raw = json.loads(kw_raw)
        except Exception:
            kw_raw = []
    kw = " ".join(str(k).lower() for k in kw_raw)

    if ("add {" in ot or "add one mana" in ot
            or ("search your library for a" in ot and "land" in ot)
            or "treasure token" in ot or "add mana" in ot):
        roles.append("Ramp")
    if ("draw a card" in ot or "draw cards" in ot or "draws a card" in ot
            or "draw two cards" in ot or "draw three cards" in ot
            or re.search(r"draw \d+ cards?", ot)
            or ("whenever" in ot and "draw" in ot)):
        roles.append("Draw")
    if ("destroy target" in ot or "exile target" in ot
            or re.search(r"deals? \d+ damage to (target|any target)", ot)
            or re.search(r"deals? x damage to (target|any target)", ot)
            or "target creature gets -" in ot or "fights target" in ot):
        roles.append("Removal")
    if ("destroy all" in ot or "exile all" in ot
            or re.search(r"all creatures get -\d+/-\d+", ot)
            or re.search(r"each creature gets -\d+/-\d+", ot)
            or ("deals" in ot and "to each creature" in ot)):
        roles.append("Board Wipe")
    if "search your library" in ot and "land" not in ot:
        roles.append("Tutor")
    if ("counter target" in ot or "counter that" in ot
            or "counters" in kw):
        roles.append("Counter")
    if ("create" in ot and ("token" in ot or "tokens" in ot)):
        roles.append("Token")
    if ("each creature you control gets" in ot or "creatures you control get" in ot
            or "all creatures you control" in ot or "anthem" in tl.lower()):
        roles.append("Anthem")
    if ("target creature gains" in ot and ("hexproof" in ot or "indestructible" in ot or "shroud" in ot))\
            or ("protection" in kw):
        roles.append("Protection")
    if ("sacrifice" in ot and ("whenever" in ot or "you may" in ot)):
        roles.append("Sacrifice")
    if ("return" in ot and ("from your graveyard" in ot and "onto the battlefield" in ot)
            or ("put" in ot and "from a graveyard" in ot and "onto the battlefield" in ot)):
        roles.append("Recursion")
    if (("graveyard" in ot and ("mill" in ot or "put" in ot and "into" in ot and "graveyard" in ot))
            or "mill" in kw):
        roles.append("Graveyard")
    if ("gain" in ot and "life" in ot) or "lifelink" in ot or "lifelink" in kw:
        roles.append("Lifegain")
    if (re.search(r"deals? \d+ damage to (each|any|target) (opponent|player)", ot)
            or "each opponent loses" in ot and "life" in ot
            or "deals damage to each opponent" in ot):
        roles.append("Burn")
    if ("can't cast" in ot or "can't attack" in ot or "can't activate" in ot
            or ("enters the battlefield tapped" in ot and "opponents" in ot)
            or "each player can't" in ot or "players can't" in ot
            or ("cost {" in ot and "more to cast" in ot)):
        roles.append("Stax")
    if ("flying" in kw or "trample" in kw or "menace" in kw or "shadow" in kw
            or "fear" in kw or "intimidate" in kw
            or "can't be blocked" in ot or "unblockable" in ot):
        roles.append("Evasion")
    if ("you win the game" in ot or "extra turn" in ot or "infinite" in ot
            or "loses the game" in ot
            or ("damage equal to" in ot and ("number" in ot or "total" in ot))):
        roles.append("Finisher")
    if ("untap all" in ot or ("copy" in ot and "spell" in ot)
            or "take an extra" in ot
            or ("double" in ot and ("damage" in ot or "counters" in ot or "tokens" in ot))):
        roles.append("Combo")
    return roles