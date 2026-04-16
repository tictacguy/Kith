"""
Agent reputation system.

Reputation is a composite score [0.0, 1.0] computed from observable signals:
- Supervision verdicts (approved/vetoed)
- Debate outcomes (won/lost)
- Delegation trust (how often peers delegate to you)
- Consensus alignment (voting with majority)

Reputation drives:
- Vote weight in consensus (high rep = more influence)
- Promotion eligibility (rep > 0.7 + interaction threshold)
- Demotion trigger (rep < 0.3 for 5+ interactions)
- Auto-retire (rep < 0.15 for 10+ interactions)
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..society.state import Agent, AgentStatus, Society


def _log_event(agent: Agent, event_type: str, detail: str, impact: float) -> None:
    """Append a reputation event to the agent's log."""
    agent.reputation_log.append({
        "type": event_type,
        "detail": detail,
        "impact": round(impact, 3),
        "reputation_after": round(agent.reputation, 3),
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    # Keep last 50 events
    if len(agent.reputation_log) > 50:
        agent.reputation_log = agent.reputation_log[-50:]


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------

def compute_reputation(agent: Agent) -> float:
    """
    Compute reputation from raw counters. Returns [0.0, 1.0].
    Starts at 0.5 (neutral) and moves based on signals.
    """
    total_verdicts = agent.approved_count + agent.vetoed_count
    total_debates = agent.debates_won + agent.debates_lost
    total_consensus = agent.consensus_agreements + agent.consensus_dissents

    score = 0.5

    # Supervision signal: approval rate (weight: 0.3)
    if total_verdicts > 0:
        approval_rate = agent.approved_count / total_verdicts
        score += (approval_rate - 0.5) * 0.3

    # Debate signal: win rate (weight: 0.2)
    if total_debates > 0:
        win_rate = agent.debates_won / total_debates
        score += (win_rate - 0.5) * 0.2

    # Delegation trust: normalized by interaction count (weight: 0.2)
    if agent.interaction_count > 0:
        delegation_rate = min(agent.delegations_received / agent.interaction_count, 1.0)
        score += delegation_rate * 0.2

    # Consensus alignment (weight: 0.15)
    if total_consensus > 0:
        alignment = agent.consensus_agreements / total_consensus
        score += (alignment - 0.5) * 0.15

    # Activity bonus: agents that participate more get a small boost (weight: 0.15)
    activity = min(agent.interaction_count / 20, 1.0)
    score += activity * 0.15

    return max(0.0, min(1.0, score))


def vote_weight(agent: Agent) -> float:
    """
    Returns the weight of this agent's vote in consensus.
    Range [0.5, 2.0] — low-rep agents still count, but less.
    """
    rep = agent.reputation
    return 0.5 + rep * 1.5


# ---------------------------------------------------------------------------
# Lifecycle decisions
# ---------------------------------------------------------------------------

_RETIRE_THRESHOLD = 0.15
_RETIRE_MIN_INTERACTIONS = 10
_DEMOTE_THRESHOLD = 0.3
_DEMOTE_MIN_INTERACTIONS = 5
_PROMOTE_THRESHOLD = 0.7

# Promotion paths
_PROMOTIONS = {
    "role_builder": "role_elder",
    "role_scout": "role_analyst",
    "role_critic": "role_analyst",
}

# Demotion paths (reverse of promotion)
_DEMOTIONS = {
    "role_elder": "role_builder",
    "role_analyst": "role_scout",
}


def check_lifecycle(agent: Agent, society: Society) -> str | None:
    """
    Check if agent should be retired, demoted, or promoted.
    Returns action string or None:
      "retire" | "demote:role_id" | "promote:role_id" | None
    """
    rep = agent.reputation

    # Auto-retire: very low reputation for extended period
    if rep < _RETIRE_THRESHOLD and agent.interaction_count >= _RETIRE_MIN_INTERACTIONS:
        # Don't retire the last agent of a role
        role_count = sum(1 for a in society.active_agents if a.role_id == agent.role_id)
        if role_count > 1:
            return "retire"

    # Demotion: low reputation, has a demotion path
    if rep < _DEMOTE_THRESHOLD and agent.interaction_count >= _DEMOTE_MIN_INTERACTIONS:
        target = _DEMOTIONS.get(agent.role_id)
        if target and target in society.roles:
            return f"demote:{target}"

    # Promotion: high reputation + enough interactions
    if rep > _PROMOTE_THRESHOLD and agent.interaction_count >= 10:
        target = _PROMOTIONS.get(agent.role_id)
        if target and target in society.roles:
            # Only promote if source role has > 1 agent
            source_count = sum(1 for a in society.active_agents if a.role_id == agent.role_id)
            if source_count > 1:
                return f"promote:{target}"

    return None


# ---------------------------------------------------------------------------
# Update reputation after interaction
# ---------------------------------------------------------------------------

def update_reputation(agent: Agent) -> None:
    """Recompute and store reputation score."""
    agent.reputation = compute_reputation(agent)


def record_verdict(agent: Agent, verdict: str) -> None:
    if verdict == "approved":
        agent.approved_count += 1
    elif verdict == "vetoed":
        agent.vetoed_count += 1
    update_reputation(agent)
    _log_event(agent, "verdict", f"Supervisor {verdict} response", agent.reputation)


def record_debate(agent: Agent, won: bool) -> None:
    if won:
        agent.debates_won += 1
    else:
        agent.debates_lost += 1
    update_reputation(agent)
    _log_event(agent, "debate", f"{'Won' if won else 'Lost'} debate", agent.reputation)


def record_delegation_received(agent: Agent) -> None:
    agent.delegations_received += 1
    update_reputation(agent)
    _log_event(agent, "delegation", "Received delegation from peer (trust)", agent.reputation)


def record_consensus_vote(agent: Agent, with_majority: bool) -> None:
    if with_majority:
        agent.consensus_agreements += 1
    else:
        agent.consensus_dissents += 1
    update_reputation(agent)
    _log_event(agent, "consensus", f"Voted {'with' if with_majority else 'against'} majority", agent.reputation)
