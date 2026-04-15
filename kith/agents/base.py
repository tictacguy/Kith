from __future__ import annotations

from meta_reasoning.engine import CognitiveEngine
from meta_reasoning.policies import ReasoningPolicy

from ..config import Config, make_backend
from ..society.state import Agent, Role, Society, SocietyPolicy
from .caveman import CavemanBackend


# ---------------------------------------------------------------------------
# Role → caveman intensity mapping
# ---------------------------------------------------------------------------

_ROLE_INTENSITY: dict[str, str] = {
    "Elder": "full",
    "Scout": "lite",           # needs articulated reasoning to explore
    "Builder": "ultra",        # dense technical output
    "Critic": "full",          # needs clarity to articulate flaws
    "Tool Smith": "ultra",     # structured output
    "Governor": "full",        # governance needs clarity
    "Analyst": "full",         # auditing needs precision
}


def intensity_for_role(role_name: str | None, default: str = "full") -> str:
    """Return the optimal caveman intensity for a given role."""
    if role_name is None:
        return default
    return _ROLE_INTENSITY.get(role_name, default)


class KithAgent:
    """
    A society member. Each agent has its own CognitiveEngine instance
    (own ledger, own mutation history) but shares the Anthropic backend.
    Caveman is injected transparently via CavemanBackend wrapper.
    """

    def __init__(
        self,
        agent: Agent,
        role: Role | None,
        cfg: Config,
        policy: ReasoningPolicy | None = None,
    ) -> None:
        self.agent = agent
        self.role = role

        # Per-role caveman intensity: Scout gets lite, Builder/MemoryKeeper get ultra, etc.
        role_name = role.name if role else None
        intensity = intensity_for_role(role_name, default=cfg.caveman_intensity)

        raw_backend = make_backend(cfg)
        caveman_backend = CavemanBackend(raw_backend, intensity=intensity)

        self._engine = CognitiveEngine(
            backend=caveman_backend,
            max_cycles=cfg.max_reasoning_cycles,
            max_violations=cfg.max_violations,
            policy=policy,
        )

    # -----------------------------------------------------------------------

    def _build_task(self, user_prompt, society, relevant_memory):
        role_desc = f"Role: {self.role.name} — {self.role.description}" if self.role else "Role: generalist"
        traits = ", ".join(self.agent.personality_traits) or "none"
        expertise = ", ".join(self.agent.expertise_domains) or "general"
        policies = "\n".join(f"- {p.rule}" for p in society.active_policies) or "none"
        memory_ctx = "\n".join(f"- {m}" for m in relevant_memory) if relevant_memory else "none"

        # Society awareness — who else is in the society
        peers = []
        for a in society.active_agents:
            if a.id == self.agent.id:
                continue
            r = society.roles.get(a.role_id)
            rname = r.name if r else "?"
            sup = ""
            if a.supervisor_id and a.supervisor_id in society.agents:
                sup = f", supervised by {society.agents[a.supervisor_id].name}"
            peers.append(f"  - {a.name} ({rname}{sup})")
        peers_str = "\n".join(peers) if peers else "  none"

        # Supervisor awareness
        sup_str = ""
        if self.agent.supervisor_id and self.agent.supervisor_id in society.agents:
            sup = society.agents[self.agent.supervisor_id]
            sup_str = f"Your supervisor: {sup.name}\n"

        # Tools
        tools_desc = ""
        if society.tools:
            tool_lines = [f"  - {t.name}({', '.join(t.parameters.keys())}): {t.description}" for t in society.tools.values()]
            tools_desc = "\nAvailable tools (invoke with TOOL_CALL: name(args)):\n" + "\n".join(tool_lines)

        society_mem = f"Society memory: {society.society_summary}\n" if society.society_summary else ""

        return (
            f"You are {self.agent.name}. {role_desc}.\n"
            f"Traits: {traits}. Expertise: {expertise}.\n"
            f"You are part of a society called Kith (stage: {society.stage.value}).\n"
            f"{sup_str}"
            f"Your peers:\n{peers_str}\n"
            f"Society policies:\n{policies}\n"
            f"{society_mem}"
            f"Relevant past context:\n{memory_ctx}\n"
            f"Your memory: {self.agent.memory_summary or 'none yet'}\n"
            f"{tools_desc}\n\n"
            f"Task: {user_prompt}"
        )

    def run(
        self,
        user_prompt: str,
        society: Society,
        relevant_memory: list[str] | None = None,
    ) -> tuple[str, int]:
        """
        Execute reasoning. Returns (response_text, output_tokens).
        Synchronous — called from async context via run_in_executor if needed.
        """
        task = self._build_task(user_prompt, society, relevant_memory or [])
        result = self._engine.run(task)

        content = result.final_output.content if result.final_output else ""

        # Extract token count from raw payload if available
        tokens = 0
        if result.final_output and result.final_output.raw:
            tokens = result.final_output.raw.get("output_tokens", 0)

        return content, tokens

    @property
    def ledger(self):
        return self._engine.ledger
