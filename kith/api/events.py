from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    # Society state
    SOCIETY_STATE = "society_state"
    SOCIETY_EVOLVED = "society_evolved"

    # Processing lifecycle
    PROCESSING_START = "processing_start"
    PROCESSING_END = "processing_end"

    # Agent activity during processing
    AGENT_THINKING = "agent_thinking"       # agent started reasoning
    AGENT_RESPONDED = "agent_responded"     # agent produced response
    AGENT_SUPERVISING = "agent_supervising" # supervisor reviewing
    AGENT_VERDICT = "agent_verdict"         # supervisor verdict

    # Synthesis
    SYNTHESIS_START = "synthesis_start"
    SYNTHESIS_END = "synthesis_end"

    # Deliberation
    DELIBERATION_START = "deliberation_start"
    DELIBERATION_END = "deliberation_end"
    AGENT_DELIBERATING = "agent_deliberating"   # reading peers' responses
    AGENT_DELIBERATED = "agent_deliberated"     # reacted to peers

    # Delegation
    AGENT_DELEGATING = "agent_delegating"       # delegating sub-task
    AGENT_DELEGATED = "agent_delegated"         # delegation completed

    # Debate
    DEBATE_START = "debate_start"
    DEBATE_END = "debate_end"
    AGENT_DEBATING = "agent_debating"           # defending position
    DEBATE_MEDIATED = "debate_mediated"         # governor ruled

    # Consensus
    CONSENSUS_START = "consensus_start"
    CONSENSUS_END = "consensus_end"
    AGENT_VOTING = "agent_voting"
    AGENT_VOTED = "agent_voted"

    # Tools
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"

    # Memory
    MEMORY_COMPRESSED = "memory_compressed"

    # Mobilization
    MOBILIZATION_START = "mobilization_start"
    MOBILIZATION_END = "mobilization_end"
    AGENT_BIDDING = "agent_bidding"


class EventBus:
    """Async broadcast bus. WebSocket handlers subscribe, orchestrator publishes."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers = [s for s in self._subscribers if s is not q]

    def emit(self, event_type: EventType, data: dict[str, Any] | None = None) -> None:
        msg = {
            "type": event_type.value,
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": data or {},
        }
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Singleton
event_bus = EventBus()
