"""
Society deliberation — agents communicate, debate, delegate, and reach consensus.

Pipeline after initial parallel responses:
  1. DELIBERATION — each agent reads all others' responses and reacts
  2. DEBATE — if disagreements detected, pairs debate with Governor mediating
  3. DELEGATION — agents can delegate sub-tasks to better-suited peers
  4. CONSENSUS — agents vote on the best position before synthesis
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
from ..society.state import Agent, EvolutionStage, Society
from ..society.reputation import vote_weight, record_delegation_received, record_debate, record_consensus_vote


@dataclass
class DeliberationResult:
    """Output of the full deliberation pipeline."""
    # Responses after deliberation (may differ from initial)
    responses: dict[str, str]           # agent_id → final position
    delegations: list[dict[str, Any]]   # [{from, to, subtask, result}]
    debates: list[dict[str, Any]]       # [{agent_a, agent_b, topic, resolution}]
    consensus: dict[str, str]           # agent_id → "agree" | "disagree" | "abstain"
    consensus_position: str             # the position most agents agreed on
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
                f"React to your peers. Do you agree? Disagree? See something they missed? "
                f"If you want to delegate a sub-task to a specific peer, write: DELEGATE: [peer_name]: [sub-task]\n"
                f"If you disagree with someone, write: DISAGREE: [peer_name]: [reason]\n"
                f"End with your updated position."
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
        # 2. Parse DELEGATE and DISAGREE directives
        # ===================================================================
        delegations: list[dict[str, Any]] = []
        disagreements: list[dict[str, Any]] = []
        name_to_id = {ka.agent.name: ka.agent.id for ka in agents}

        for aid, text in deliberated.items():
            agent_name = agent_map[aid].agent.name if aid in agent_map else aid

            # Parse DELEGATE: [peer_name]: [sub-task]
            for m in re.finditer(r"DELEGATE:\s*\[?(\w[\w\s]*?)\]?:\s*(.+?)(?:\n|$)", text, re.IGNORECASE):
                target_name = m.group(1).strip()
                subtask = m.group(2).strip()
                target_id = name_to_id.get(target_name)
                if target_id and target_id != aid:
                    delegations.append({"from": aid, "from_name": agent_name, "to": target_id, "to_name": target_name, "subtask": subtask})

            # Parse DISAGREE: [peer_name]: [reason]
            for m in re.finditer(r"DISAGREE:\s*\[?(\w[\w\s]*?)\]?:\s*(.+?)(?:\n|$)", text, re.IGNORECASE):
                target_name = m.group(1).strip()
                reason = m.group(2).strip()
                target_id = name_to_id.get(target_name)
                if target_id and target_id != aid:
                    disagreements.append({"agent_a": aid, "agent_a_name": agent_name, "agent_b": target_id, "agent_b_name": target_name, "topic": reason})

        # ===================================================================
        # 3. DELEGATION — execute delegated sub-tasks
        # ===================================================================
        for d in delegations:
            _emit(EventType.AGENT_DELEGATING, {
                "from_id": d["from"], "from_name": d["from_name"],
                "to_id": d["to"], "to_name": d["to_name"],
                "subtask": d["subtask"][:80],
            })
            if d["to"] in agent_map:
                target_ka = agent_map[d["to"]]
                prompt = (
                    f"You are {target_ka.agent.name}. {d['from_name']} delegated this sub-task to you:\n"
                    f"{d['subtask']}\n\nOriginal question context: {user_prompt}\n\nRespond concisely."
                )
                content, tokens = await loop.run_in_executor(executor, self._call_sync, prompt)
                d["result"] = content
                total_tokens += tokens
                _emit(EventType.AGENT_DELEGATED, {
                    "from_id": d["from"], "to_id": d["to"], "to_name": d["to_name"],
                    "result_preview": content[:100],
                })
                # Inject delegation result into the delegating agent's response
                deliberated[d["from"]] += f"\n[Delegation result from {d['to_name']}]: {content}"

        # Record delegation trust signals
        for d in delegations:
            if d["to"] in agent_map:
                record_delegation_received(agent_map[d["to"]].agent)

        # ===================================================================
        # 4. DEBATE — skip if skip_debate=True (team level)
        # ===================================================================
        debates: list[dict[str, Any]] = []

        if not skip_debate:
            governor_id = next((a.id for a in society.active_agents if a.role_id == "role_governor"), None)
            for dis in disagreements[:3]:
                a_id, b_id = dis["agent_a"], dis["agent_b"]
                a_name, b_name = dis["agent_a_name"], dis["agent_b_name"]
                topic = dis["topic"]

                _emit(EventType.DEBATE_START, {"agent_a": a_name, "agent_b": b_name, "topic": topic[:80]})

                rebuttal = ""
                if b_id in agent_map:
                    rebuttal_prompt = (
                        f"You are {b_name}. {a_name} disagrees with you: \"{topic}\"\n"
                        f"Your position: {deliberated.get(b_id, '')[:200]}\n"
                        f"Defend or concede. Be specific."
                    )
                    rebuttal, tokens = await loop.run_in_executor(executor, self._call_sync, rebuttal_prompt)
                    total_tokens += tokens
                    _emit(EventType.AGENT_DEBATING, {
                        "agent_id": b_id, "agent_name": b_name,
                        "responding_to": a_name, "preview": rebuttal[:100],
                    })

                resolution = ""
                if governor_id and governor_id in agent_map:
                    gov = agent_map[governor_id]
                    mediation_prompt = (
                        f"You are {gov.agent.name}, Governor. Mediate this debate:\n"
                        f"{a_name}: {topic}\n"
                        f"{b_name}: {rebuttal[:200]}\n\n"
                        f"Who has the stronger point? Give a ruling in one sentence."
                    )
                    resolution, tokens = await loop.run_in_executor(executor, self._call_sync, mediation_prompt)
                    total_tokens += tokens
                    _emit(EventType.DEBATE_MEDIATED, {"governor": gov.agent.name, "resolution": resolution[:100]})

                if resolution and a_id in agent_map and b_id in agent_map:
                    a_won = a_name.lower() in resolution.lower()
                    record_debate(agent_map[a_id].agent, a_won)
                    record_debate(agent_map[b_id].agent, not a_won)

                debates.append({
                    "agent_a": a_name, "agent_b": b_name,
                    "topic": topic, "rebuttal": rebuttal[:200],
                    "resolution": resolution,
                })
                _emit(EventType.DEBATE_END, {"agent_a": a_name, "agent_b": b_name})

        # ===================================================================
        # 5. CONSENSUS — agents vote on final position
        # ===================================================================
        _emit(EventType.CONSENSUS_START, {"agent_count": len(agents)})

        # Build summary of all positions + debate resolutions
        positions_summary = "\n".join(
            f"[{agent_map[aid].agent.name}]: {resp[:150]}"
            for aid, resp in deliberated.items() if aid in agent_map
        )
        debate_summary = "\n".join(
            f"Debate: {d['agent_a']} vs {d['agent_b']} → {d['resolution'][:100]}"
            for d in debates
        ) if debates else "No debates."

        consensus: dict[str, str] = {}
        vote_tasks = []

        for ka in agents:
            vote_prompt = (
                f"You are {ka.agent.name}. The society discussed:\n{positions_summary}\n\n"
                f"Debates resolved:\n{debate_summary}\n\n"
                f"Vote: AGREE, DISAGREE, or ABSTAIN with the emerging consensus. "
                f"Then state your final position in one sentence."
            )

            async def _vote(ka=ka, prompt=vote_prompt):
                _emit(EventType.AGENT_VOTING, {"agent_id": ka.agent.id, "agent_name": ka.agent.name})
                content, tokens = await loop.run_in_executor(executor, self._call_sync, prompt)
                # Parse vote
                vote = "agree"
                upper = content.upper()
                if "DISAGREE" in upper:
                    vote = "disagree"
                elif "ABSTAIN" in upper:
                    vote = "abstain"
                return ka.agent.id, ka.agent.name, vote, content, tokens

            vote_tasks.append(_vote())

        vote_results = await asyncio.gather(*vote_tasks)
        final_positions: dict[str, str] = {}
        for aid, name, vote, content, tokens in vote_results:
            consensus[aid] = vote
            final_positions[aid] = content
            total_tokens += tokens
            _emit(EventType.AGENT_VOTED, {"agent_id": aid, "agent_name": name, "vote": vote})

        # Determine consensus — WEIGHTED by reputation
        weighted_agree = sum(vote_weight(agent_map[aid].agent) for aid, v in consensus.items() if v == "agree" and aid in agent_map)
        weighted_disagree = sum(vote_weight(agent_map[aid].agent) for aid, v in consensus.items() if v == "disagree" and aid in agent_map)
        agree_count = sum(1 for v in consensus.values() if v == "agree")
        disagree_count = sum(1 for v in consensus.values() if v == "disagree")

        # Record consensus alignment
        majority_is_agree = weighted_agree >= weighted_disagree
        for aid, v in consensus.items():
            if aid in agent_map:
                with_majority = (v == "agree" and majority_is_agree) or (v == "disagree" and not majority_is_agree)
                record_consensus_vote(agent_map[aid].agent, with_majority)

        if majority_is_agree:
            # Use the Elder's final position as consensus, or first agreeing agent
            elder_id = next((a.id for a in society.active_agents if a.role_id == "role_elder"), None)
            consensus_position = final_positions.get(elder_id, next(iter(final_positions.values()), ""))
        else:
            # Dissent — use the strongest dissenter's position
            dissenter = next((aid for aid, v in consensus.items() if v == "disagree"), next(iter(final_positions)))
            consensus_position = final_positions.get(dissenter, "")

        _emit(EventType.CONSENSUS_END, {
            "agree": agree_count, "disagree": disagree_count,
            "abstain": len(consensus) - agree_count - disagree_count,
        })

        return DeliberationResult(
            responses=final_positions,
            delegations=delegations,
            debates=debates,
            consensus=consensus,
            consensus_position=consensus_position,
            total_tokens=total_tokens,
        )
