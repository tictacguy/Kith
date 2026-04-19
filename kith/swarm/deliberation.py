"""
Society deliberation — agents communicate, challenge, and converge.

Pipeline after initial parallel responses:
  1. DELIBERATION — each agent reads all others' responses and reacts
     - Can CHALLENGE a specific peer's reasoning (triggers debate)
     - Can REQUEST a peer to elaborate on a specific point
  2. DEBATE — challenged pairs argue, Governor mediates
  3. CONVERGENCE — natural consensus emerges from updated positions
     No explicit voting — convergence is measured by position similarity
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from ..agents.base import KithAgent
from ..api.events import EventType, event_bus
from ..config import Config, make_backend
from ..agents.caveman import CavemanBackend
from ..society.state import Society
from ..society.reputation import record_debate, record_consensus_vote
from ..society.relationships import record_consensus_alignment, record_debate_outcome


@dataclass
class DeliberationResult:
    """Output of the full deliberation pipeline."""
    responses: dict[str, str]           # agent_id → final position
    delegations: list[dict[str, Any]]   # kept for compatibility, always []
    debates: list[dict[str, Any]]       # [{agent_a, agent_b, topic, resolution}]
    consensus: dict[str, str]           # agent_id → "agree" | "disagree" | "abstain"
    consensus_position: str             # the strongest position after convergence
    total_tokens: int = 0


def _emit(t: EventType, data=None):
    event_bus.emit(t, data)


class DeliberationEngine:
    """
    Runs the full deliberation pipeline between agents.
    Each step uses a lightweight LLM call (caveman ultra) to minimize tokens.
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        backend = make_backend(cfg)
        self._backend = CavemanBackend(backend, intensity="ultra")

    def _call_sync(self, prompt: str) -> tuple[str, int]:
        result = self._backend.generate([{"role": "user", "content": prompt}])
        return result.get("content", "").strip(), result.get("output_tokens", 0)

    async def deliberate(
        self,
        initial_responses: dict[str, str],
        user_prompt: str,
        society: Society,
        agents: list[KithAgent],
        executor,
        skip_debate: bool = False,
    ) -> DeliberationResult:
        loop = asyncio.get_event_loop()
        total_tokens = 0
        agent_map = {ka.agent.id: ka for ka in agents}

        # ===================================================================
        # 1. DELIBERATION — each agent reads all others and reacts
        # ===================================================================
        _emit(EventType.DELIBERATION_START, {"agent_count": len(agents)})

        deliberated: dict[str, str] = {}
        delib_tasks = []

        for ka in agents:
            others = "\n".join(
                f"[{agent_map[aid].agent.name}]: {resp[:200]}"
                for aid, resp in initial_responses.items()
                if aid != ka.agent.id and aid in agent_map
            )
            prompt = (
                f"You are {ka.agent.name} ({ka.role.name if ka.role else 'generalist'}).\n"
                f"Original question: {user_prompt}\n\n"
                f"Your initial response: {initial_responses.get(ka.agent.id, '')[:200]}\n\n"
                f"Your peers responded:\n{others}\n\n"
                f"React to your peers. What did they get right? What did they miss? "
                f"If you think a peer's reasoning is flawed, write: CHALLENGE: [peer_name]: [specific flaw]\n"
                f"End with your UPDATED position incorporating what you learned from peers."
            )

            async def _delib(ka=ka, prompt=prompt):
                _emit(EventType.AGENT_DELIBERATING, {
                    "agent_id": ka.agent.id, "agent_name": ka.agent.name,
                    "reading_from": [aid for aid in initial_responses if aid != ka.agent.id],
                })
                content, tokens = await loop.run_in_executor(executor, self._call_sync, prompt)
                _emit(EventType.AGENT_DELIBERATED, {
                    "agent_id": ka.agent.id, "agent_name": ka.agent.name,
                    "response_preview": content[:100],
                })
                return ka.agent.id, content, tokens

            delib_tasks.append(_delib())

        delib_results = await asyncio.gather(*delib_tasks)
        for aid, content, tokens in delib_results:
            deliberated[aid] = content
            total_tokens += tokens

        _emit(EventType.DELIBERATION_END, {})

        # ===================================================================
        # 2. Parse CHALLENGE directives
        # ===================================================================
        challenges: list[dict[str, Any]] = []
        name_to_id = {ka.agent.name: ka.agent.id for ka in agents}

        for aid, text in deliberated.items():
            agent_name = agent_map[aid].agent.name if aid in agent_map else aid
            # Max 1 challenge per agent
            m = re.search(r"CHALLENGE:\s*\[?(\w[\w\s]*?)\]?:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
            if m:
                target_name = m.group(1).strip()
                reason = m.group(2).strip()
                target_id = name_to_id.get(target_name)
                if target_id and target_id != aid:
                    challenges.append({
                        "agent_a": aid, "agent_a_name": agent_name,
                        "agent_b": target_id, "agent_b_name": target_name,
                        "topic": reason,
                    })

        # ===================================================================
        # 3. DEBATE — challenged pairs argue, Governor mediates
        # ===================================================================
        debates: list[dict[str, Any]] = []

        if not skip_debate and challenges:
            governor_id = next(
                (a.id for a in society.active_agents if a.role_id == "role_governor"), None
            )
            for dis in challenges[:3]:  # max 3 debates
                a_id, b_id = dis["agent_a"], dis["agent_b"]
                a_name, b_name = dis["agent_a_name"], dis["agent_b_name"]
                topic = dis["topic"]

                _emit(EventType.DEBATE_START, {
                    "agent_a": a_name, "agent_b": b_name, "topic": topic[:80],
                })

                # Challenged agent defends
                rebuttal = ""
                if b_id in agent_map:
                    rebuttal_prompt = (
                        f"You are {b_name}. {a_name} challenges your reasoning: \"{topic}\"\n"
                        f"Your position: {deliberated.get(b_id, '')[:200]}\n"
                        f"Defend with evidence, or concede if the challenge is valid."
                    )
                    rebuttal, tokens = await loop.run_in_executor(
                        executor, self._call_sync, rebuttal_prompt,
                    )
                    total_tokens += tokens
                    _emit(EventType.AGENT_DEBATING, {
                        "agent_id": b_id, "agent_name": b_name,
                        "responding_to": a_name, "preview": rebuttal[:100],
                    })

                # Governor mediates (if present)
                resolution = ""
                if governor_id and governor_id in agent_map:
                    gov = agent_map[governor_id]
                    mediation_prompt = (
                        f"You are {gov.agent.name}, Governor. Mediate this debate:\n"
                        f"{a_name} challenges: {topic}\n"
                        f"{b_name} defends: {rebuttal[:200]}\n\n"
                        f"Who has the stronger argument? Rule in one sentence."
                    )
                    resolution, tokens = await loop.run_in_executor(
                        executor, self._call_sync, mediation_prompt,
                    )
                    total_tokens += tokens
                    _emit(EventType.DEBATE_MEDIATED, {
                        "governor": gov.agent.name, "resolution": resolution[:100],
                    })

                # Record debate outcome
                if resolution and a_id in agent_map and b_id in agent_map:
                    a_won = a_name.lower() in resolution.lower()
                    record_debate(agent_map[a_id].agent, a_won)
                    record_debate(agent_map[b_id].agent, not a_won)
                    winner, loser = (a_id, b_id) if a_won else (b_id, a_id)
                    record_debate_outcome(society, winner, loser)

                debates.append({
                    "agent_a": a_name, "agent_b": b_name,
                    "topic": topic, "rebuttal": rebuttal[:200],
                    "resolution": resolution,
                })
                _emit(EventType.DEBATE_END, {"agent_a": a_name, "agent_b": b_name})

        # ===================================================================
        # 4. CONVERGENCE — measure natural consensus from positions
        #    No explicit voting. Consensus is inferred from how much
        #    positions aligned after deliberation + debate.
        # ===================================================================

        # Determine consensus position: Elder's updated position takes priority
        # (Elder's role is to synthesize), otherwise highest-reputation agent
        elder_id = next(
            (a.id for a in society.active_agents if a.role_id == "role_elder" and a.id in deliberated),
            None,
        )
        if elder_id:
            consensus_position = deliberated[elder_id]
        else:
            # Highest reputation among participants
            best = max(
                (ka for ka in agents if ka.agent.id in deliberated),
                key=lambda ka: ka.agent.reputation,
                default=None,
            )
            consensus_position = deliberated.get(best.agent.id, "") if best else ""

        # Infer agreement: agents whose updated position doesn't contain
        # CHALLENGE are considered converged
        consensus: dict[str, str] = {}
        for aid, text in deliberated.items():
            has_challenge = bool(re.search(r"CHALLENGE:", text, re.IGNORECASE))
            consensus[aid] = "disagree" if has_challenge else "agree"

        # Record pairwise consensus relationships
        agent_ids_list = list(consensus.keys())
        for i, aid_a in enumerate(agent_ids_list):
            for aid_b in agent_ids_list[i + 1:]:
                aligned = consensus.get(aid_a) == consensus.get(aid_b)
                record_consensus_alignment(society, aid_a, aid_b, aligned)

        # Record individual consensus alignment
        agree_count = sum(1 for v in consensus.values() if v == "agree")
        majority_agrees = agree_count > len(consensus) / 2
        for aid, v in consensus.items():
            if aid in agent_map:
                with_majority = (v == "agree") == majority_agrees
                record_consensus_vote(agent_map[aid].agent, with_majority)

        _emit(EventType.CONSENSUS_END, {
            "agree": agree_count,
            "disagree": sum(1 for v in consensus.values() if v == "disagree"),
            "abstain": 0,
        })

        return DeliberationResult(
            responses=deliberated,
            delegations=[],
            debates=debates,
            consensus=consensus,
            consensus_position=consensus_position,
            total_tokens=total_tokens,
        )
