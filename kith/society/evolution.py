"""
Society evolution — maturity-based stage transitions and organic policy generation.

Stage upgrades are NOT based on interaction count alone. They require the society
to demonstrate maturity across multiple dimensions:
  - Diversity: enough distinct roles filled
  - Stability: average reputation above threshold
  - Tooling: society has developed/used tools
  - Governance: debates resolve, consensus forms
  - Scale: minimum agent count

Policies emerge from observed problems, not from templates.
"""
from __future__ import annotations

from collections import Counter

from meta_reasoning.policies import ReasoningPolicy, PolicyRule
from meta_reasoning.types import CognitiveMove, Mutation, MutationType

from ..agents.roles import TRIBAL_ROLES, ORGANIZED_ROLES
from ..config import Config
from ..society.state import (
    Agent, AgentStatus, EvolutionStage, Interaction, Role, Society, SocietyPolicy
)


# ---------------------------------------------------------------------------
# Maturity criteria per stage transition
# ---------------------------------------------------------------------------

# Agent count is uncapped — the society grows as needed.
# Spawn rate is limited to 1 per interaction to prevent explosions.


def _maturity_score(society: Society) -> dict[str, float]:
    """
    Compute maturity across dimensions. Each dimension is 0.0-1.0.
    """
    active = society.active_agents
    if not active:
        return {"diversity": 0, "stability": 0, "tooling": 0, "governance": 0, "scale": 0}

    # Diversity: how many distinct roles are filled (out of available)
    filled_roles = len(set(a.role_id for a in active if a.role_id))
    total_roles = len(society.roles)
    diversity = filled_roles / max(total_roles, 1)

    # Stability: average reputation of active agents
    avg_rep = sum(a.reputation for a in active) / len(active)
    stability = avg_rep

    # Tooling: has tools been created and used?
    tool_count = len(society.tools)
    tools_used = sum(1 for t in society.tools.values() if t.usage_count > 0)
    tooling = min(1.0, (tool_count * 0.3 + tools_used * 0.7) / max(3, 1))

    # Governance: ratio of active policies + debate resolution
    policy_count = len(society.active_policies)
    governance = min(1.0, policy_count / 3)

    # Scale: agent count relative to a reasonable baseline
    scale = min(1.0, len(active) / 10)

    return {
        "diversity": round(diversity, 2),
        "stability": round(stability, 2),
        "tooling": round(tooling, 2),
        "governance": round(governance, 2),
        "scale": round(scale, 2),
    }


# Minimum maturity thresholds to advance
_MATURITY_THRESHOLDS = {
    EvolutionStage.PRIMITIVE: {  # → TRIBAL
        "min_interactions": 8,
        "diversity": 0.5,    # at least half the roles filled
        "stability": 0.4,    # agents performing ok
        "scale": 0.4,        # enough agents
    },
    EvolutionStage.TRIBAL: {  # → ORGANIZED
        "min_interactions": 25,
        "diversity": 0.6,
        "stability": 0.5,
        "tooling": 0.2,      # some tool usage
        "governance": 0.3,   # at least 1 policy
        "scale": 0.5,
    },
    EvolutionStage.ORGANIZED: {  # → COMPLEX
        "min_interactions": 60,
        "diversity": 0.7,
        "stability": 0.6,
        "tooling": 0.4,
        "governance": 0.6,   # multiple policies
        "scale": 0.6,
    },
}


# ---------------------------------------------------------------------------
# Organic policy detection — what problems does the society have?
# ---------------------------------------------------------------------------

def _detect_policy_needs(society: Society, recent: list[Interaction]) -> list[SocietyPolicy]:
    """
    Analyze society health and propose policies for observed problems.
    Returns new policies that don't already exist.
    Policies go through governance cap — caller must use governance.add_policy().
    """
    active = society.active_agents
    if not active or not recent:
        return []

    existing_names = {p.name for p in society.policies.values()}
    proposals: list[SocietyPolicy] = []

    # Problem: high veto rate → quality review policy
    total_vetoes = sum(a.vetoed_count for a in active)
    total_approvals = sum(a.approved_count for a in active)
    if total_vetoes > 3 and total_vetoes > total_approvals * 0.3:
        name = "Quality Review"
        if name not in existing_names:
            proposals.append(SocietyPolicy(
                name=name, source="organic", effectiveness_score=0.6,
                rule="Before submitting a response, self-review for accuracy and completeness. If uncertain, state uncertainty explicitly.",
            ))

    # Problem: too many unresolved disagreements → mediation policy
    total_debates_lost = sum(a.debates_lost for a in active)
    if total_debates_lost > 5:
        name = "Structured Mediation"
        if name not in existing_names:
            proposals.append(SocietyPolicy(
                name=name, source="organic", effectiveness_score=0.6,
                rule="When disagreeing, state the specific claim you dispute and provide evidence. Governor mediates by evaluating evidence strength.",
            ))

    # Problem: low consensus alignment → deliberation depth policy
    total_dissents = sum(a.consensus_dissents for a in active)
    total_agreements = sum(a.consensus_agreements for a in active)
    if total_dissents > total_agreements and society.total_interactions > 5:
        name = "Deliberation Depth"
        if name not in existing_names:
            proposals.append(SocietyPolicy(
                name=name, source="organic", effectiveness_score=0.6,
                rule="Read all peer responses fully before reacting. Acknowledge valid points from others before stating disagreements.",
            ))

    # Problem: agents not using tools → tool adoption policy
    tools_unused = sum(1 for t in society.tools.values() if t.usage_count == 0)
    if tools_unused > 1 and society.total_interactions > 10:
        name = "Tool Adoption"
        if name not in existing_names:
            proposals.append(SocietyPolicy(
                name=name, source="organic", effectiveness_score=0.5,
                rule="When a task matches an available tool's capability, use TOOL_CALL instead of reasoning from scratch.",
            ))

    # Problem: low delegation trust → collaboration policy
    total_delegations = sum(a.delegations_received for a in active)
    if total_delegations == 0 and society.total_interactions > 8:
        name = "Collaborative Delegation"
        if name not in existing_names:
            proposals.append(SocietyPolicy(
                name=name, source="organic", effectiveness_score=0.5,
                rule="If a sub-task falls outside your expertise, delegate to the peer best suited. Use DELEGATE: [peer_name]: [task].",
            ))

    return proposals


# ---------------------------------------------------------------------------
# Meta-Reasoning policies per stage
# ---------------------------------------------------------------------------

def _policy_for_stage(stage: EvolutionStage) -> ReasoningPolicy:
    p = ReasoningPolicy(name=f"kith_{stage.value}")
    if stage == EvolutionStage.PRIMITIVE:
        p.add_rule(PolicyRule(name="no_stall", condition=lambda m, c: m.strategy_repetition > 0.5,
            mutations=lambda m, c: [Mutation(type=MutationType.INVERT_CAUSALITY, reason="break stall")]))
    elif stage == EvolutionStage.TRIBAL:
        p.add_rule(PolicyRule(name="require_diversity", condition=lambda m, c: m.entropy < 1.2,
            mutations=lambda m, c: [Mutation(type=MutationType.REQUIRE, target=CognitiveMove.CONTRADICTION, reason="tribal: diversity")]))
        p.add_rule(PolicyRule(name="compress_late", condition=lambda m, c: c >= 3,
            mutations=lambda m, c: [Mutation(type=MutationType.FORCE_COMPRESSION, parameter=3, reason="tribal: compress")]))
    elif stage in (EvolutionStage.ORGANIZED, EvolutionStage.COMPLEX):
        p.add_rule(PolicyRule(name="ban_dominant", condition=lambda m, c: m.dominant_move is not None,
            mutations=lambda m, c: [Mutation(type=MutationType.BAN, target=m.dominant_move, reason="organized: no dominance")]))
        p.add_rule(PolicyRule(name="hard_compress", condition=lambda m, c: c >= 2,
            mutations=lambda m, c: [Mutation(type=MutationType.FORCE_COMPRESSION, parameter=2, reason="organized: tight")]))
    return p


# ---------------------------------------------------------------------------
# Evolution engine
# ---------------------------------------------------------------------------

class EvolutionEngine:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def policy_for_society(self, society: Society) -> ReasoningPolicy:
        return _policy_for_stage(society.stage)

    # -----------------------------------------------------------------------
    # Legacy transfer — institutional knowledge survives agent death
    # -----------------------------------------------------------------------

    @staticmethod
    def transfer_legacy(retired: Agent, society: Society) -> str | None:
        """
        Build a legacy from a retired agent and transfer it to the best
        successor (same role, lowest experience). Returns changelog entry
        or None if no successor found.
        """
        # Build the testament
        lessons = []
        if retired.memory_summary:
            # Keep last ~300 chars of memory (most recent lessons)
            mem = retired.memory_summary.strip()
            if len(mem) > 300:
                mem = mem[-300:]
            lessons.append(f"Memory: {mem}")

        # Extract failure patterns from reputation log
        failures = [e for e in retired.reputation_log if e.get("type") == "verdict" and "vetoed" in e.get("detail", "").lower()]
        if failures:
            lessons.append(f"Vetoed {len(failures)} times — avoid repeating these mistakes.")
        debate_losses = [e for e in retired.reputation_log if e.get("type") == "debate" and "Lost" in e.get("detail", "")]
        if debate_losses:
            lessons.append(f"Lost {len(debate_losses)} debates — strengthen evidence before arguing.")

        # Thematic expertise
        if retired.thematic_profile:
            top_themes = sorted(retired.thematic_profile.items(), key=lambda x: -x[1])[:5]
            lessons.append(f"Expertise areas: {', '.join(t for t, _ in top_themes)}")

        if not lessons:
            return None

        legacy = f"[Legacy from {retired.name}] " + " | ".join(lessons)
        # Cap legacy size
        if len(legacy) > 500:
            legacy = legacy[:500]

        # Find successor: same role, active, lowest interaction count
        candidates = [
            a for a in society.active_agents
            if a.role_id == retired.role_id and a.id != retired.id
        ]
        if not candidates:
            # No same-role successor — try any active agent with fewest interactions
            candidates = [a for a in society.active_agents if a.id != retired.id]
        if not candidates:
            return None

        successor = min(candidates, key=lambda a: a.interaction_count)
        successor.inherited_legacy = legacy

        # Transfer thematic profile (diluted)
        if retired.thematic_profile:
            for theme, score in retired.thematic_profile.items():
                existing = successor.thematic_profile.get(theme, 0.0)
                successor.thematic_profile[theme] = round(min(1.0, existing + score * 0.5), 3)

        # Transfer expertise domains (merge, no duplicates)
        for domain in retired.expertise_domains:
            if domain not in successor.expertise_domains:
                successor.expertise_domains.append(domain)
        # Cap at 6
        successor.expertise_domains = successor.expertise_domains[:6]

        return f"{retired.name}'s legacy transferred to {successor.name}"

    # -----------------------------------------------------------------------
    # Stage evolution — maturity-based
    # -----------------------------------------------------------------------

    def should_evolve(self, society: Society) -> bool:
        thresholds = _MATURITY_THRESHOLDS.get(society.stage)
        if not thresholds:
            return False

        if society.total_interactions < thresholds.get("min_interactions", 0):
            return False

        maturity = _maturity_score(society)
        for dim, min_val in thresholds.items():
            if dim == "min_interactions":
                continue
            if maturity.get(dim, 0) < min_val:
                return False

        return True

    def maturity_report(self, society: Society) -> dict:
        """Return current maturity scores + thresholds for frontend display."""
        maturity = _maturity_score(society)
        thresholds = _MATURITY_THRESHOLDS.get(society.stage, {})
        return {
            "scores": maturity,
            "thresholds": {k: v for k, v in thresholds.items() if k != "min_interactions"},
            "min_interactions": thresholds.get("min_interactions", 0),
            "current_interactions": society.total_interactions,
            "ready": self.should_evolve(society),
        }

    def evolve(self, society: Society) -> tuple[Society, list[str]]:
        changelog: list[str] = []
        stage_order = list(EvolutionStage)
        idx = stage_order.index(society.stage)
        if idx >= len(stage_order) - 1:
            return society, []

        new_stage = stage_order[idx + 1]
        society.stage = new_stage
        changelog.append(f"Stage: {stage_order[idx].value} -> {new_stage.value}")

        for role in self._roles_for_stage(new_stage):
            if role.id not in society.roles:
                society.roles[role.id] = role
                changelog.append(f"Role unlocked: {role.name}")
                if True:  # no agent cap
                    agent = self._spawn_agent(society, role_id=role.id)
                    society.agents[agent.id] = agent
                    changelog.append(f"Spawned {agent.name} for new role")

        assigned = self.assign_supervisors(society)
        for aid, sup_id in assigned.items():
            changelog.append(f"Supervision: {society.agents[aid].name} -> {society.agents[sup_id].name}")

        return society, changelog

    # -----------------------------------------------------------------------
    # Organic checks — called after each interaction
    # -----------------------------------------------------------------------

    def organic_check(self, society: Society, recent: list[Interaction]) -> list[str]:
        from ..society.governance import add_policy, decay_policies

        changelog: list[str] = []
        spawned = False  # max 1 spawn per cycle

        # --- Policy decay — prune unused/ineffective policies ---
        decay_log = decay_policies(society)
        changelog.extend(decay_log)

        # --- Organic policy generation (through governance cap) ---
        new_policies = _detect_policy_needs(society, recent)
        for p in new_policies:
            added = add_policy(society, p)
            if added:
                changelog.append(f"Policy emerged: {p.name} — {p.rule[:60]}")

        # --- SPAWN: role overload (based on recent mobilization frequency) ---
        if not spawned:
            role_freq = self._compute_role_mobilization(recent, society)
            if role_freq:
                avg_freq = sum(role_freq.values()) / len(role_freq)
                for role_id, freq in role_freq.items():
                    if freq > avg_freq * 2.5 and freq >= 4:
                        agent = self._spawn_agent(society, role_id=role_id)
                        society.agents[agent.id] = agent
                        changelog.append(f"Spawned {agent.name} (role overloaded: {freq} activations in last {len(recent)} interactions)")
                        spawned = True
                        break

        # --- SPAWN: theme coverage ---
        if not spawned and society.dominant_themes:
            covered = set()
            for a in society.active_agents:
                covered.update(d.lower() for d in a.expertise_domains)
            uncovered = [t for t in society.dominant_themes[:3] if t.lower() not in covered]
            if len(uncovered) >= 2:
                role_usage = Counter(a.role_id for a in society.active_agents if a.role_id)
                least_role = min(society.roles.values(), key=lambda r: role_usage.get(r.id, 0))
                agent = self._spawn_agent(society, role_id=least_role.id, extra_expertise=uncovered[:2])
                society.agents[agent.id] = agent
                changelog.append(f"Spawned {agent.name} (themes: {', '.join(uncovered[:2])})")
                spawned = True

        if changelog:
            self.assign_supervisors(society)

        return changelog

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _compute_role_mobilization(self, recent: list[Interaction], society: Society) -> dict[str, int]:
        """Count how many times each role was activated in recent interactions."""
        role_freq: dict[str, int] = {}
        for ix in recent:
            for aid in ix.assigned_agents:
                agent = society.agents.get(aid)
                if agent and agent.role_id:
                    role_freq[agent.role_id] = role_freq.get(agent.role_id, 0) + 1
        return role_freq

    def _compute_role_load(self, society: Society) -> dict[str, float]:
        role_counts: dict[str, list[int]] = {}
        for a in society.active_agents:
            if a.role_id:
                role_counts.setdefault(a.role_id, []).append(a.interaction_count)
        return {rid: sum(c) / len(c) for rid, c in role_counts.items() if c}

    def _spawn_agent(self, society: Society, role_id: str | None = None, extra_expertise: list[str] | None = None) -> Agent:
        if role_id is None:
            role_usage = Counter(a.role_id for a in society.active_agents if a.role_id)
            role = min(society.roles.values(), key=lambda r: role_usage.get(r.id, 0))
            role_id = role.id
        role = society.roles[role_id]
        name = f"{role.name}_{len(society.agents) + 1}"
        expertise = list(role.responsibilities[:2])
        if extra_expertise:
            expertise.extend(extra_expertise)
        return Agent(name=name, role_id=role_id, expertise_domains=expertise, personality_traits=self._traits_for_role(role))

    def assign_supervisors(self, society: Society) -> dict[str, str]:
        role_to_agent: dict[str, str] = {}
        for agent in society.active_agents:
            if agent.role_id and agent.role_id not in role_to_agent:
                role_to_agent[agent.role_id] = agent.id
        assigned: dict[str, str] = {}
        for role in society.roles.values():
            sup_id = role_to_agent.get(role.id)
            if not sup_id:
                continue
            for sub_role_id in role.supervises:
                for agent in society.active_agents:
                    if agent.role_id == sub_role_id and agent.id != sup_id:
                        if agent.supervisor_id != sup_id:
                            agent.supervisor_id = sup_id
                            assigned[agent.id] = sup_id
        return assigned

    def update_themes(self, society: Society, new_themes: list[str]) -> None:
        counter = Counter(society.dominant_themes + new_themes)
        society.dominant_themes = [t for t, _ in counter.most_common(10)]

    @staticmethod
    def _roles_for_stage(stage: EvolutionStage) -> list[Role]:
        if stage == EvolutionStage.TRIBAL:
            return list(TRIBAL_ROLES)
        if stage in (EvolutionStage.ORGANIZED, EvolutionStage.COMPLEX):
            return list(ORGANIZED_ROLES)
        return []

    @staticmethod
    def _traits_for_role(role: Role) -> list[str]:
        return {
            "Elder": ["analytical", "decisive", "concise"],
            "Scout": ["curious", "contrarian", "creative"],
            "Builder": ["pragmatic", "systematic", "detail-oriented"],
            "Critic": ["analytical", "skeptical", "precise"],
            "Tool Smith": ["inventive", "technical", "forward-thinking"],
            "Governor": ["authoritative", "fair", "strategic"],
            "Analyst": ["critical", "objective", "thorough"],
        }.get(role.name, ["adaptive"])
