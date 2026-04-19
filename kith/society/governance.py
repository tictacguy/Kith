"""
Policy governance — lifecycle management for society policies.

Policies are the society's self-imposed rules. They must be:
  - Capped: max active policies scales with society stage
  - Expiring: unused policies decay and get deactivated
  - Evaluated: effectiveness is tracked, low-value policies are pruned

Sources:
  - organic: detected from metrics (high veto rate, low delegation, etc.)
  - retrospective: proposed during self-reflection, queued for evaluation
  - manual: added by user via API

The Governor role (when present) has authority over policy decisions.
Without a Governor, policies are managed mechanically by this module.
"""
from __future__ import annotations

from ..society.state import EvolutionStage, Society, SocietyPolicy


# Max active policies per stage
_POLICY_CAP: dict[EvolutionStage, int] = {
    EvolutionStage.PRIMITIVE: 1,
    EvolutionStage.TRIBAL: 3,
    EvolutionStage.ORGANIZED: 5,
    EvolutionStage.COMPLEX: 7,
}

# Policies unused for this many interactions get deactivated
_DECAY_THRESHOLD = 15

# Minimum effectiveness to survive pruning
_MIN_EFFECTIVENESS = 0.2


def policy_cap(society: Society) -> int:
    return _POLICY_CAP.get(society.stage, 3)


def can_add_policy(society: Society) -> bool:
    """Check if the society can accept another active policy."""
    active_count = len(society.active_policies)
    return active_count < policy_cap(society)


def add_policy(society: Society, policy: SocietyPolicy) -> bool:
    """
    Try to add a policy. Returns True if added, False if cap reached.
    If cap is reached, tries to replace the weakest existing policy.
    """
    policy.created_at_interaction = society.total_interactions
    policy.last_relevant_at = society.total_interactions

    active = society.active_policies
    cap = policy_cap(society)

    if len(active) < cap:
        society.policies[policy.id] = policy
        return True

    # Cap reached — find the weakest policy to replace
    weakest = min(active, key=lambda p: p.effectiveness_score)
    if weakest.effectiveness_score < policy.effectiveness_score:
        weakest.active = False
        society.policies[policy.id] = policy
        return True

    return False


def decay_policies(society: Society) -> list[str]:
    """
    Run decay pass on all active policies.
    Deactivates policies that haven't been relevant for too long.
    Returns changelog entries.
    """
    changelog: list[str] = []
    current = society.total_interactions

    for p in list(society.active_policies):
        idle = current - p.last_relevant_at

        if idle >= _DECAY_THRESHOLD:
            p.active = False
            changelog.append(f"Policy expired (unused {idle} interactions): {p.name}")
            continue

        # Gradual effectiveness decay for idle policies
        if idle > 5:
            decay = 0.02 * (idle - 5)
            p.effectiveness_score = max(0.0, round(p.effectiveness_score - decay, 3))

            if p.effectiveness_score < _MIN_EFFECTIVENESS:
                p.active = False
                changelog.append(f"Policy pruned (low effectiveness): {p.name}")

    return changelog


def mark_policy_relevant(society: Society, policy_id: str) -> None:
    """Mark a policy as recently relevant (an agent referenced it)."""
    if policy_id in society.policies:
        p = society.policies[policy_id]
        p.last_relevant_at = society.total_interactions
        # Small effectiveness boost when used
        p.effectiveness_score = min(1.0, round(p.effectiveness_score + 0.05, 3))
