from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..agents.base import KithAgent
from ..config import Config
from ..society.evolution import EvolutionEngine
from ..society.state import Agent, AgentStatus, EvolutionStage, Role, Society


@dataclass
class SupervisedResponse:
    agent_id: str
    agent_name: str
    raw_response: str
    supervisor_id: str | None = None
    supervisor_name: str | None = None
    supervisor_verdict: str = "approved"   # approved | revised | vetoed
    final_response: str = ""
    tokens: int = 0

    def __post_init__(self):
        if not self.final_response:
            self.final_response = self.raw_response


def _build_supervision_map(society: Society) -> dict[str, str]:
    """
    Returns {subordinate_agent_id: supervisor_agent_id}.
    Primary source: agent.supervisor_id (set by EvolutionEngine.assign_supervisors).
    Fallback: role.supervises chains for agents without supervisor_id.
    """
    sup_map: dict[str, str] = {}

    # Primary: use persisted supervisor_id
    for agent in society.active_agents:
        if agent.supervisor_id and agent.supervisor_id in society.agents:
            sup = society.agents[agent.supervisor_id]
            if sup.status == AgentStatus.ACTIVE:
                sup_map[agent.id] = agent.supervisor_id

    # Fallback: derive from role.supervises for any agent not yet mapped
    role_to_agent: dict[str, str] = {}
    for agent in society.active_agents:
        if agent.role_id and agent.role_id not in role_to_agent:
            role_to_agent[agent.role_id] = agent.id

    for role in society.roles.values():
        supervisor_agent_id = role_to_agent.get(role.id)
        if not supervisor_agent_id:
            continue
        for supervised_role_id in role.supervises:
            for agent in society.active_agents:
                if (
                    agent.role_id == supervised_role_id
                    and agent.id != supervisor_agent_id
                    and agent.id not in sup_map
                ):
                    sup_map[agent.id] = supervisor_agent_id

    return sup_map


class SupervisionChain:
    """
    At ORGANIZED+ stages, each agent response passes through its supervisor
    before being included in synthesis.

    Supervisor can:
    - approve  → response passes unchanged
    - revise   → supervisor rewrites/improves the response
    - veto     → response excluded from synthesis
    """

    def __init__(self, cfg: Config, evolution: EvolutionEngine) -> None:
        self._cfg = cfg
        self._evolution = evolution

    def is_active(self, society: Society) -> bool:
        return society.stage in (EvolutionStage.ORGANIZED, EvolutionStage.COMPLEX)

    async def review(
        self,
        responses: dict[str, str],   # agent_id → raw response
        token_map: dict[str, int],
        society: Society,
        executor,
    ) -> list[SupervisedResponse]:
        """
        Apply supervision to all responses.
        Returns list of SupervisedResponse, vetoed ones excluded from final synthesis.
        """
        if not self.is_active(society):
            # Pass-through — no supervision at primitive/tribal
            return [
                SupervisedResponse(
                    agent_id=aid,
                    agent_name=society.agents[aid].name if aid in society.agents else aid,
                    raw_response=resp,
                    final_response=resp,
                    tokens=token_map.get(aid, 0),
                )
                for aid, resp in responses.items()
            ]

        sup_map = _build_supervision_map(society)
        policy = self._evolution.policy_for_society(society)

        # Build supervisor KithAgents (one per unique supervisor needed)
        needed_supervisors = set(sup_map.get(aid) for aid in responses if sup_map.get(aid))
        supervisor_agents: dict[str, KithAgent] = {}
        for sup_id in needed_supervisors:
            if sup_id not in society.agents:
                continue
            sup_agent = society.agents[sup_id]
            supervisor_agents[sup_id] = KithAgent(
                agent=sup_agent,
                role=society.roles.get(sup_agent.role_id) if sup_agent.role_id else None,
                cfg=self._cfg,
                policy=policy,
            )

        loop = asyncio.get_event_loop()
        results: list[SupervisedResponse] = []

        for agent_id, raw_resp in responses.items():
            agent = society.agents.get(agent_id)
            agent_name = agent.name if agent else agent_id
            sup_id = sup_map.get(agent_id)

            if not sup_id or sup_id not in supervisor_agents:
                # No supervisor — auto-approved
                results.append(SupervisedResponse(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    raw_response=raw_resp,
                    final_response=raw_resp,
                    tokens=token_map.get(agent_id, 0),
                ))
                continue

            sup_ka = supervisor_agents[sup_id]
            sup_agent = society.agents[sup_id]

            review_prompt = (
                f"You are {sup_agent.name}, supervisor. Review this subordinate response.\n\n"
                f"Subordinate ({agent_name}): {raw_resp}\n\n"
                f"Reply with one of:\n"
                f"APPROVED: <response unchanged>\n"
                f"REVISED: <your improved version>\n"
                f"VETOED: <one-line reason>"
            )

            verdict_text, sup_tokens = await loop.run_in_executor(
                executor, sup_ka.run, review_prompt, society, []
            )

            verdict_text = verdict_text.strip()
            if verdict_text.startswith("VETOED"):
                results.append(SupervisedResponse(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    raw_response=raw_resp,
                    supervisor_id=sup_id,
                    supervisor_name=sup_agent.name,
                    supervisor_verdict="vetoed",
                    final_response="",
                    tokens=token_map.get(agent_id, 0) + sup_tokens,
                ))
            elif verdict_text.startswith("REVISED:"):
                revised = verdict_text[len("REVISED:"):].strip()
                results.append(SupervisedResponse(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    raw_response=raw_resp,
                    supervisor_id=sup_id,
                    supervisor_name=sup_agent.name,
                    supervisor_verdict="revised",
                    final_response=revised,
                    tokens=token_map.get(agent_id, 0) + sup_tokens,
                ))
            else:
                # APPROVED or unparseable → pass through
                results.append(SupervisedResponse(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    raw_response=raw_resp,
                    supervisor_id=sup_id,
                    supervisor_name=sup_agent.name,
                    supervisor_verdict="approved",
                    final_response=raw_resp,
                    tokens=token_map.get(agent_id, 0) + sup_tokens,
                ))

        return results
