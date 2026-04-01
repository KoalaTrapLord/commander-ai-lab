# Phase 2 - game_orchestrator.py  *** CORE PRIORITY ***
# GameAIOrchestrator: select_brain(), assign_personalities(), get_action()
# Brains: DeepSeek-R1-14B (complex) + GPT-OSS-20B (tactical)
# ChromaDB RAG for per-player card knowledge
# See issue #169

PERSONALITY_POOL = [
    "aggressive -- attack early and often, prioritize players with lowest life totals",
    "control -- counter key spells, hold mana open, only act when clearly advantageous",
    "combo -- develop mana and card advantage quietly, avoid conflict until ready to win",
    "political -- make deals, attack whoever is ahead, never fully commit to one target",
    "pillowfort -- build defensive pieces, let others fight, win slowly through attrition",
    "stompy -- play the biggest threats as fast as possible, ignore table politics",
    "tempo -- disrupt opponents early, trade efficiently, stay ahead on board",
]
