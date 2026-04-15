"""
Society mobilization — distributed resource allocation.

No dispatcher. Each agent self-evaluates relevance to a prompt.
Activation is proportional to complexity. Deliberation depth scales
with the number of activated agents.

Flow:
  1. BID — every active agent scores their relevance (1 ultra-cheap LLM call each)
  2. ACTIVATE — agents above dynamic threshold participate
  3. SCALE — deliberation depth determined by activation count

Mobilization levels (determined by how many agents self-activate):
  SOLO    (1 agent)  — direct response, no deliberation
  PAIR    (2 agents) — responses + light synthesis, no debate
  TEAM    (3-4)      — deliberation without debate
  COUNCIL (5+)       — full pipeline: deliberation + debate + consensus
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from ..agents.caveman import CavemanBackend
from ..api.events import EventType, event_bus
from ..config import Config, make_backend
from ..society.state import Agent, Society


@dataclass
class Bid:
    agent_id: str
    agent_name: str
    relevance: float   # 0.0 - 1.0
    reason: str


@dataclass
class MobilizationResult:
    bids: list[Bid]
    activated_ids: list[str]
    level: str          # solo | pair | team | council
    threshold: float
    total_bid_tokens: int


def _emit(t: EventType, data=None):
    event_bus.emit(t, data)


class MobilizationEngine:
    """
    Distributed agent activation. Each agent bids on relevance,
    only those above threshold participate.
    """

    def __init__(self, cfg: Config) -> None:
        backend = make_backend(cfg)
        self._backend = CavemanBackend(backend, intensity="ultra")

    def _bid_sync(self, agent: Agent, prompt: str, society: Society) -> tuple[float, str, int]:
        """Single agent evaluates relevance. Returns (score, reason, tokens)."""
        role_name = society.roles[agent.role_id].name if agent.role_id and agent.role_id in society.roles else "generalist"
        expertise = ", ".join(agent.expertise_domains) or "general"

        bid_prompt = (
            f"You are {agent.name} ({role_name}). Expertise: {expertise}.\n"
            f"Rate your relevance to this task 0.0-1.0. Consider:\n"
            f"- Does it match your expertise?\n"
            f"- Is it complex enough to need your role?\n"
            f"- Would a simpler agent handle it fine?\n\n"
            f"Task: {prompt}\n\n"
            f"Reply ONLY: RELEVANCE: <number> REASON: <one sentence>"
        )

        result = self._backend.generate([{"role": "user", "content": bid_prompt}])
        text = result.get("content", "").strip()
        tokens = result.get("output_tokens", 0)

        # Parse relevance score
        relevance = 0.5  # default
        reason = text
        m = re.search(r"RELEVANCE:\s*([\d.]+)", text, re.IGNORECASE)
        if m:
            try:
                relevance = max(0.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass
        m2 = re.search(r"REASON:\s*(.+)", text, re.IGNORECASE)
        if m2:
            reason = m2.group(1).strip()

        return relevance, reason, tokens

    async def mobilize(
        self,
        prompt: str,
        society: Society,
        executor,
    ) -> MobilizationResult:
        """
        Run bid phase across all active agents. Returns who should participate.
        """
        active = society.active_agents
        if not active:
            return MobilizationResult([], [], "solo", 0.0, 0)

        # For very small societies (<=3), skip bidding — everyone participates
        if len(active) <= 3:
            return MobilizationResult(
                bids=[Bid(a.id, a.name, 1.0, "small society") for a in active],
                activated_ids=[a.id for a in active],
                level=_level_for_count(len(active)),
                threshold=0.0,
                total_bid_tokens=0,
            )

        _emit(EventType.MOBILIZATION_START, {"agent_count": len(active)})

        loop = asyncio.get_event_loop()
        total_tokens = 0

        # Parallel bid phase
        async def _bid_one(agent: Agent):
            _emit(EventType.AGENT_BIDDING, {"agent_id": agent.id, "agent_name": agent.name})
            relevance, reason, tokens = await loop.run_in_executor(
                executor, self._bid_sync, agent, prompt, society
            )
            return Bid(agent.id, agent.name, relevance, reason), tokens

        results = await asyncio.gather(*[_bid_one(a) for a in active])

        bids: list[Bid] = []
        for bid, tokens in results:
            bids.append(bid)
            total_tokens += tokens

        # Sort by relevance descending
        bids.sort(key=lambda b: b.relevance, reverse=True)

        # Dynamic threshold: median relevance, but at least 1 agent activates
        scores = [b.relevance for b in bids]
        median = sorted(scores)[len(scores) // 2]

        # Threshold = median, but ensure at least 1 and at most all activate
        threshold = max(0.1, median)

        activated = [b for b in bids if b.relevance >= threshold]

        # Guarantee at least 1 agent (highest bidder)
        if not activated:
            activated = [bids[0]]

        # High-reputation agents get a boost — if they bid close to threshold, include them
        for bid in bids:
            if bid in activated:
                continue
            agent = next((a for a in active if a.id == bid.agent_id), None)
            if agent and agent.reputation > 0.7 and bid.relevance >= threshold * 0.7:
                activated.append(bid)

        activated_ids = [b.agent_id for b in activated]
        level = _level_for_count(len(activated_ids))

        _emit(EventType.MOBILIZATION_END, {
            "activated": len(activated_ids),
            "total": len(active),
            "level": level,
            "threshold": round(threshold, 2),
            "bids": [{"name": b.agent_name, "relevance": round(b.relevance, 2)} for b in bids],
        })

        return MobilizationResult(
            bids=bids,
            activated_ids=activated_ids,
            level=level,
            threshold=threshold,
            total_bid_tokens=total_tokens,
        )


def _level_for_count(n: int) -> str:
    if n <= 1:
        return "solo"
    if n <= 2:
        return "pair"
    if n <= 4:
        return "team"
    return "council"
