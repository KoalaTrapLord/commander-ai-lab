"""
Commander AI Lab — GUI Constants (Phase 4)
==========================================
All magic numbers in one place. Adjust here to re-skin the entire UI.
"""

# --- Window ---
SCREEN_W: int = 1280
SCREEN_H: int = 960
FPS: int = 60
TITLE: str = "Commander AI Lab"

# --- Card dimensions ---
CARD_W: int  = 90
CARD_H: int  = 126
CARD_RADIUS: int = 6   # rounded corner radius
CARD_TAPPED_ANGLE: float = 90.0  # degrees clockwise

# --- Zone layout (4-player split: top / left / right / bottom) ---
# Each player occupies one quadrant.  Zones inside each quadrant:
ZONE_HAND_H: int      = CARD_H + 16
ZONE_BF_H: int        = 220       # battlefield height per player
ZONE_GRAVEYARD_W: int = CARD_W + 12
ZONE_EXILE_W: int     = CARD_W + 12
ZONE_COMMAND_W: int   = CARD_W + 12
ZONE_STACK_W: int     = 160
ZONE_STACK_X: int     = (SCREEN_W - ZONE_STACK_W) // 2
ZONE_STACK_Y: int     = (SCREEN_H - 180) // 2

# --- Narration panel (right side) ---
NARRATION_X: int      = SCREEN_W - 270
NARRATION_Y: int      = 40
NARRATION_W: int      = 260
NARRATION_H: int      = SCREEN_H - 80
NARRATION_MAX_LINES: int = 18

# --- Phase / step indicator ---
PHASE_BAR_H: int = 32

# --- Life total / commander damage matrix ---
LIFE_PANEL_W: int = 120
LIFE_PANEL_H: int = 100

# --- Colours (R, G, B) ---
COLOUR_BG          = (18,  20,  30)
COLOUR_ZONE_BG     = (28,  32,  48)
COLOUR_ZONE_BORDER = (60,  70,  100)
COLOUR_CARD_BACK   = (40,  55,  90)
COLOUR_CARD_FACE   = (230, 220, 195)
COLOUR_CARD_TAPPED = (150, 130, 80)
COLOUR_HIGHLIGHT   = (255, 220, 50)
COLOUR_TARGET_RING = (255, 80,  80)
COLOUR_TEXT        = (240, 240, 240)
COLOUR_TEXT_DIM    = (140, 140, 160)
COLOUR_PHASE_BAR   = (35,  40,  60)
COLOUR_PHASE_ACTIVE= (60, 130, 220)
COLOUR_NARRATION_BG= (22,  26,  40)
COLOUR_LIFE_HIGH   = (80,  200, 100)
COLOUR_LIFE_MED    = (220, 180, 50)
COLOUR_LIFE_LOW    = (220, 60,  60)
COLOUR_ELIMINATED  = (80,  80,  80)
COLOUR_THINKING    = (100, 180, 255)

# Player seat colours (used to tint zone borders and name labels)
SEAT_COLOURS = [
    (70,  140, 255),   # seat 0 — blue
    (255, 100, 80),    # seat 1 — red
    (80,  210, 120),   # seat 2 — green
    (220, 170, 50),    # seat 3 — gold
]

# --- Commander phases list (for phase bar) ---
COMMANDER_PHASES = [
    "untap", "upkeep", "draw",
    "main1", "begin_combat", "declare_attackers",
    "declare_blockers", "combat_damage", "end_combat",
    "main2", "end_step", "cleanup",
]

PHASE_LABELS = {
    "untap":             "Untap",
    "upkeep":            "Upkeep",
    "draw":              "Draw",
    "main1":             "Main 1",
    "begin_combat":      "Begin Combat",
    "declare_attackers": "Attackers",
    "declare_blockers":  "Blockers",
    "combat_damage":     "Damage",
    "end_combat":        "End Combat",
    "main2":             "Main 2",
    "end_step":          "End Step",
    "cleanup":           "Cleanup",
}
