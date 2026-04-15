from __future__ import annotations

import asyncio

from ..config import Config, make_backend
from ..agents.caveman import CavemanBackend
from ..society.state import Agent, Interaction, Society

# Agent memory thresholds
_MEMORY_THRESHOLD = 1200
_MEMORY_TARGET = 400

# Society summary thresholds
_SOCIETY_SUMMARY_THRESHOLD = 2000
_SOCIETY_SUMMARY_TARGET = 600
_SOCIETY_COMPRESS_EVERY_N = 5  # compress every N interactions


class MemoryCompressor:
    """Compresses individual agent memory_summary when it exceeds threshold."""

    def __init__(self, cfg: Config) -> None:
        backend = make_backend(cfg)
        self._backend = CavemanBackend(backend, intensity="ultra")

    def _compress_sync(self, agent: Agent, society: Society) -> str:
        role_name = (
            society.roles[agent.role_id].name
            if agent.role_id and agent.role_id in society.roles
            else "agent"
        )
        messages = [
            {
                "role": "user",
                "content": (
                    f"You are Memory Keeper. Compress this {role_name} memory to ≤{_MEMORY_TARGET} chars. "
                    f"Keep: key decisions, expertise gained, important context. Drop: redundant detail, filler.\n\n"
                    f"MEMORY:\n{agent.memory_summary}"
                ),
            }
        ]
        result = self._backend.generate(messages)
        compressed = result.get("content", "").strip()
        return compressed if compressed else agent.memory_summary[:_MEMORY_TARGET]

    async def maybe_compress(self, agent: Agent, society: Society, executor) -> bool:
        if len(agent.memory_summary) < _MEMORY_THRESHOLD:
            return False
        loop = asyncio.get_event_loop()
        compressed = await loop.run_in_executor(
            executor, self._compress_sync, agent, society
        )
        agent.memory_summary = compressed
        return True

    def append_to_memory(self, agent: Agent, new_fragment: str) -> None:
        if agent.memory_summary:
            agent.memory_summary = f"{agent.memory_summary}\n{new_fragment}"
        else:
            agent.memory_summary = new_fragment


class SocietyMemoryKeeper:
    """
    Compresses the global society_summary periodically.

    Aggregates: recent interactions, dominant themes, agent roster changes,
    policy changes — into a single compressed narrative that gets injected
    into every agent's context as "society memory".

    Triggered every _SOCIETY_COMPRESS_EVERY_N interactions, or when
    society_summary exceeds _SOCIETY_SUMMARY_THRESHOLD chars.
    """

    def __init__(self, cfg: Config) -> None:
        backend = make_backend(cfg)
        self._backend = CavemanBackend(backend, intensity="ultra")

    def should_compress(self, society: Society) -> bool:
        if society.total_interactions % _SOCIETY_COMPRESS_EVERY_N != 0:
            return False
        return society.total_interactions > 0

    def _build_raw_summary(
        self,
        society: Society,
        recent_interactions: list[Interaction],
    ) -> str:
        """Build the raw text to compress from society state + recent interactions."""
        parts: list[str] = []

        # Existing summary as base
        if society.society_summary:
            parts.append(f"Previous summary:\n{society.society_summary}")

        # Recent interactions digest
        if recent_interactions:
            digest = "\n".join(
                f"- [{', '.join(i.themes[:3])}] {i.user_prompt[:80]} → {i.final_response[:80]}"
                for i in recent_interactions[:10]
            )
            parts.append(f"Recent interactions:\n{digest}")

        # Agent roster
        active = society.active_agents
        roster = ", ".join(
            f"{a.name}({society.roles[a.role_id].name if a.role_id and a.role_id in society.roles else '?'})"
            for a in active[:15]
        )
        parts.append(f"Active agents ({len(active)}): {roster}")

        # Themes
        if society.dominant_themes:
            parts.append(f"Dominant themes: {', '.join(society.dominant_themes[:10])}")

        # Policies
        active_policies = society.active_policies
        if active_policies:
            pol = "; ".join(p.name for p in active_policies)
            parts.append(f"Active policies: {pol}")

        parts.append(f"Stage: {society.stage.value}, Total interactions: {society.total_interactions}")

        return "\n\n".join(parts)

    def _compress_sync(
        self,
        society: Society,
        recent_interactions: list[Interaction],
    ) -> str:
        raw = self._build_raw_summary(society, recent_interactions)

        messages = [
            {
                "role": "user",
                "content": (
                    f"Compress this society state into max {_SOCIETY_SUMMARY_TARGET} chars. "
                    f"Focus on: what topics the society has expertise in, what it learned, key decisions. "
                    f"Do NOT list agent names. Do NOT repeat theme words. Write 2-3 sentences max.\n\n"
                    f"RAW:\n{raw}"
                ),
            }
        ]
        result = self._backend.generate(messages)
        compressed = result.get("content", "").strip()
        return compressed if compressed else raw[:_SOCIETY_SUMMARY_TARGET]

    async def maybe_compress(
        self,
        society: Society,
        recent_interactions: list[Interaction],
        executor,
    ) -> bool:
        """Compress society summary if conditions met. Returns True if compressed."""
        if not self.should_compress(society):
            return False

        loop = asyncio.get_event_loop()
        compressed = await loop.run_in_executor(
            executor, self._compress_sync, society, recent_interactions
        )
        society.society_summary = compressed
        return True
