"""
Commander AI Lab — Politics Engine (Phase 6)

Exposes:
  PoliticsEngine   — deal proposals, threat broadcasts, spite tracking
  TargetingMemory  — per-seat history of who targeted whom
  Deal             — data class for a proposed deal
  DealResponse     — accept / counter / reject
"""
from commander_ai_lab.sim.politics.engine   import PoliticsEngine
from commander_ai_lab.sim.politics.memory   import TargetingMemory
from commander_ai_lab.sim.politics.deals    import Deal, DealResponse, DealType
from commander_ai_lab.sim.politics.comms    import ThreatBroadcast, PoliticsCommsChannel

__all__ = [
    "PoliticsEngine", "TargetingMemory",
    "Deal", "DealResponse", "DealType",
    "ThreatBroadcast", "PoliticsCommsChannel",
]
