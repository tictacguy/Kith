"""
Emergent thematic clusters.

Agents develop thematic profiles from participation history.
When a new prompt arrives, agents with high thematic affinity
get a mobilization boost — no explicit cluster management needed.

Profile update:
  After each interaction, participating agents get their thematic_profile
  updated with the interaction's themes, weighted by outcome quality
  (reputation delta, supervision verdict).

Affinity scoring:
  Uses ChromaDB semantic similarity between the prompt and each agent's
  accumulated thematic profile. Pure vector math — zero LLM calls.
"""
from __future__ import annotations

from .state import Agent, Society


# ---------------------------------------------------------------------------
# Thematic affinity: agent ↔ prompt
# ---------------------------------------------------------------------------

def thematic_affinity(agent: Agent, prompt: str, store) -> float:
    """
    Score how well an agent's thematic history matches a prompt.
    Uses ChromaDB vector similarity against the agent's profile document.
    Returns 0.0-1.0 (1.0 = perfect match).
    """
    if not agent.thematic_profile:
        return 0.0

    # Build a document from the agent's thematic profile
    profile_doc = " ".join(
        f"{theme} " * max(1, int(score * 3))
        for theme, score in sorted(agent.thematic_profile.items(), key=lambda x: -x[1])[:10]
    )
    if not profile_doc.strip():
        return 0.0

    # Use ChromaDB's built-in embedding to compare
    try:
        vec = store._vec
        # Upsert a temporary doc for the agent profile, query against prompt
        tmp_id = f"_tmp_affinity_{agent.id}"
        vec.upsert(ids=[tmp_id], documents=[profile_doc], metadatas=[{"type": "_tmp"}])
        results = vec.query(query_texts=[prompt], n_results=20, where={"type": "_tmp"})

        # Find this agent's distance in results
        for i, rid in enumerate(results["ids"][0]):
            if rid == tmp_id:
                distance = results["distances"][0][i]
                # cosine distance → affinity (0 distance = 1.0 affinity)
                return max(0.0, min(1.0, 1.0 - distance))
    except Exception:
        pass
    return 0.0


def batch_thematic_affinity(agents: list[Agent], prompt: str, store) -> dict[str, float]:
    """
    Score all agents at once. More efficient than calling thematic_affinity
    one by one — single query, batch upsert.
    Returns {agent_id: affinity_score}.
    """
    vec = store._vec
    agents_with_profile = [a for a in agents if a.thematic_profile]
    if not agents_with_profile:
        return {a.id: 0.0 for a in agents}

    # Batch upsert all agent profiles as temporary docs
    tmp_ids = []
    docs = []
    for a in agents_with_profile:
        profile_doc = " ".join(
            f"{theme} " * max(1, int(score * 3))
            for theme, score in sorted(a.thematic_profile.items(), key=lambda x: -x[1])[:10]
        )
        if profile_doc.strip():
            tmp_ids.append(f"_tmp_affinity_{a.id}")
            docs.append(profile_doc)

    if not tmp_ids:
        return {a.id: 0.0 for a in agents}

    try:
        vec.upsert(ids=tmp_ids, documents=docs, metadatas=[{"type": "_tmp"}] * len(tmp_ids))
        results = vec.query(query_texts=[prompt], n_results=len(tmp_ids), where={"type": "_tmp"})

        # Build distance map
        dist_map: dict[str, float] = {}
        for i, rid in enumerate(results["ids"][0]):
            agent_id = rid.replace("_tmp_affinity_", "")
            dist_map[agent_id] = results["distances"][0][i]

        # Cleanup temp docs
        vec.delete(ids=tmp_ids)

        # Convert distances to affinities
        out: dict[str, float] = {}
        for a in agents:
            if a.id in dist_map:
                out[a.id] = max(0.0, min(1.0, 1.0 - dist_map[a.id]))
            else:
                out[a.id] = 0.0
        return out

    except Exception:
        # Cleanup on failure
        try:
            vec.delete(ids=tmp_ids)
        except Exception:
            pass
        return {a.id: 0.0 for a in agents}


# ---------------------------------------------------------------------------
# Profile update — called after each interaction
# ---------------------------------------------------------------------------

_DECAY = 0.95   # old themes decay slightly each interaction
_BOOST = 0.15   # base boost for participating in an interaction


def update_thematic_profiles(
    society: Society,
    participant_ids: list[str],
    themes: list[str],
    quality_scores: dict[str, float] | None = None,
) -> None:
    """
    Update thematic profiles for agents who participated.

    quality_scores: {agent_id: 0.0-1.0} — how well the agent performed.
    If not provided, all participants get equal boost.
    """
    if not themes:
        return

    for agent in society.agents.values():
        if agent.id not in participant_ids:
            # Non-participants: decay only (themes they haven't worked on fade)
            if agent.thematic_profile:
                agent.thematic_profile = {
                    t: round(s * _DECAY, 3)
                    for t, s in agent.thematic_profile.items()
                    if s * _DECAY > 0.01
                }
            continue

        # Participant: boost themes from this interaction
        quality = (quality_scores or {}).get(agent.id, 0.5)
        boost = _BOOST * (0.5 + quality)  # range: 0.075 to 0.225

        profile = agent.thematic_profile or {}

        # Decay existing
        profile = {t: round(s * _DECAY, 3) for t, s in profile.items() if s * _DECAY > 0.01}

        # Boost interaction themes
        for theme in themes:
            t = theme.lower().strip()
            if t:
                profile[t] = min(1.0, round(profile.get(t, 0.0) + boost, 3))

        # Cap at 20 themes per agent (keep highest)
        if len(profile) > 20:
            profile = dict(sorted(profile.items(), key=lambda x: -x[1])[:20])

        agent.thematic_profile = profile
