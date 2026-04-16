"""
Bilateral relationships between agents.

Every pair of agents has an affinity score [-1.0, 1.0]:
  -1.0 = deep distrust (consistently opposed, vetoed each other)
   0.0 = neutral (no history)
  +1.0 = strong trust (collaborated well, delegated, agreed)

Signals that modify relationships:
  - Co-participation: worked on same prompt → small positive
  - Delegation: A delegated to B → positive for both
  - Consensus alignment: voted the same way → positive
  - Consensus opposition: voted opposite → small negative
  - Debate: A won against B → A gains, B loses slightly
  - Supervision veto: supervisor vetoed subordinate → negative

Relationships influence:
  - Mobilization: if agent A is activated, agents with high affinity to A
    get a bid boost (they work well together)
  - Deliberation: agents aware of who they trust/distrust
  - Delegation: agents prefer delegating to trusted peers
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..society.state import Society


def _pair_key(a_id: str, b_id: str) -> str:
    """Canonical key for a pair — always sorted so A:B == B:A."""
    return ":".join(sorted([a_id, b_id]))


def get_affinity(society: Society, a_id: str, b_id: str) -> float:
    """Get affinity between two agents. Returns 0.0 if no history."""
    return society.relationships.get(_pair_key(a_id, b_id), 0.0)


def get_top_allies(society: Society, agent_id: str, n: int = 3) -> list[tuple[str, float]]:
    """Get the N agents with highest affinity to this agent."""
    scores: list[tuple[str, float]] = []
    for key, score in society.relationships.items():
        parts = key.split(":")
        if agent_id in parts:
            other = parts[0] if parts[1] == agent_id else parts[1]
            if other in society.agents and society.agents[other].status.value == "active":
                scores.append((other, score))
    scores.sort(key=lambda x: -x[1])
    return scores[:n]


def get_rivals(society: Society, agent_id: str, n: int = 3) -> list[tuple[str, float]]:
    """Get the N agents with lowest (most negative) affinity."""
    scores: list[tuple[str, float]] = []
    for key, score in society.relationships.items():
        if score >= 0:
            continue
        parts = key.split(":")
        if agent_id in parts:
            other = parts[0] if parts[1] == agent_id else parts[1]
            if other in society.agents:
                scores.append((other, score))
    scores.sort(key=lambda x: x[1])
    return scores[:n]


# ---------------------------------------------------------------------------
# Modify relationships based on observed signals
# ---------------------------------------------------------------------------

def _adjust(society: Society, a_id: str, b_id: str, delta: float, reason: str) -> None:
    """Adjust affinity between two agents. Clamps to [-1.0, 1.0]."""
    if a_id == b_id:
        return
    key = _pair_key(a_id, b_id)
    current = society.relationships.get(key, 0.0)
    new_val = max(-1.0, min(1.0, current + delta))
    society.relationships[key] = round(new_val, 3)

    # Log (keep last 100)
    society.relationship_log.append({
        "agents": [a_id, b_id],
        "delta": round(delta, 3),
        "new_value": round(new_val, 3),
        "reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    if len(society.relationship_log) > 100:
        society.relationship_log = society.relationship_log[-100:]


def record_co_participation(society: Society, agent_ids: list[str]) -> None:
    """All agents who worked on the same prompt get a small affinity boost."""
    for i, a in enumerate(agent_ids):
        for b in agent_ids[i + 1:]:
            _adjust(society, a, b, 0.02, "co-participation")


def record_delegation(society: Society, from_id: str, to_id: str) -> None:
    """Delegation = trust signal. Positive for both."""
    _adjust(society, from_id, to_id, 0.08, "delegation trust")


def record_consensus_alignment(society: Society, a_id: str, b_id: str, aligned: bool) -> None:
    """Voted the same way = positive. Opposite = small negative."""
    if aligned:
        _adjust(society, a_id, b_id, 0.04, "consensus aligned")
    else:
        _adjust(society, a_id, b_id, -0.03, "consensus opposed")


def record_debate_outcome(society: Society, winner_id: str, loser_id: str) -> None:
    """Winner gains slight edge over loser in the relationship."""
    _adjust(society, winner_id, loser_id, -0.05, "debate: lost against")


def record_supervision_veto(society: Society, supervisor_id: str, subordinate_id: str) -> None:
    """Veto creates friction between supervisor and subordinate."""
    _adjust(society, supervisor_id, subordinate_id, -0.06, "supervision veto")


def record_supervision_approval(society: Society, supervisor_id: str, subordinate_id: str) -> None:
    """Approval strengthens the relationship."""
    _adjust(society, supervisor_id, subordinate_id, 0.03, "supervision approved")
