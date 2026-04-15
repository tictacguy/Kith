"""
Historian — the society's dedicated memory keeper.

Not a compressor. Not a word counter. An intelligent agent that:
1. After each interaction, decides what's worth remembering
2. Maintains structured memory: topics, decisions, expertise, patterns
3. Extracts meaningful themes (via LLM, not word counting)
4. Compresses individual agent memories when needed
5. Serves as the bridge between agents and historical context

Uses caveman ultra internally for token efficiency.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..agents.caveman import CavemanBackend
from ..api.events import EventType, event_bus
from ..config import Config, make_backend
from ..society.state import Agent, Interaction, Society


@dataclass
class MemoryUpdate:
    """Output of the Historian after processing an interaction."""
    society_summary: str          # updated narrative summary
    themes: list[str]             # meaningful topic keywords (LLM-extracted)
    agent_notes: dict[str, str]   # agent_id → what this agent should remember
    tokens_used: int = 0


class Historian:
    """
    The society's memory. Runs after every interaction.
    One LLM call to analyze what happened and update memory.
    """

    def __init__(self, cfg: Config) -> None:
        backend = make_backend(cfg)
        self._backend = CavemanBackend(backend, intensity="ultra")

    def _call_sync(self, prompt: str) -> tuple[str, int]:
        result = self._backend.generate([{"role": "user", "content": prompt}])
        return result.get("content", "").strip(), result.get("output_tokens", 0)

    # -----------------------------------------------------------------------
    # Main entry: process an interaction and update memory
    # -----------------------------------------------------------------------

    def process_interaction_sync(
        self,
        interaction: Interaction,
        society: Society,
        participating_agent_ids: list[str],
    ) -> MemoryUpdate:
        """
        Analyze what happened in this interaction and produce a memory update.
        Single LLM call — efficient.
        """
        # Build context
        agent_names = []
        for aid in participating_agent_ids:
            if aid in society.agents:
                a = society.agents[aid]
                role = society.roles.get(a.role_id)
                agent_names.append(f"{a.name} ({role.name if role else '?'})")

        existing_summary = society.society_summary or "No history yet."
        existing_themes = ", ".join(society.dominant_themes[:5]) if society.dominant_themes else "none"

        prompt = (
            f"You are the Historian of a society called Kith.\n\n"
            f"CURRENT MEMORY:\n{existing_summary}\n\n"
            f"CURRENT THEMES: {existing_themes}\n\n"
            f"NEW INTERACTION:\n"
            f"User asked: {interaction.user_prompt}\n"
            f"Agents involved: {', '.join(agent_names)}\n"
            f"Final response: {interaction.final_response[:300]}\n"
            f"Tools used: {', '.join(interaction.tools_used) or 'none'}\n\n"
            f"TASKS:\n"
            f"1. SUMMARY: Update the society memory in 2-3 sentences. What did the society learn? "
            f"What expertise was demonstrated? Do NOT list agent names or repeat old info verbatim.\n"
            f"2. THEMES: Extract 3-5 meaningful topic keywords from this interaction. "
            f"Not generic words — specific domains/concepts discussed.\n"
            f"3. AGENT_NOTES: For each participating agent, write one sentence about what they "
            f"should remember from this interaction.\n\n"
            f"Reply in this exact format:\n"
            f"SUMMARY: <2-3 sentences>\n"
            f"THEMES: <comma-separated keywords>\n"
            f"AGENT_NOTES:\n"
            f"<agent_name>: <one sentence>\n"
        )

        text, tokens = self._call_sync(prompt)
        return self._parse_update(text, tokens, participating_agent_ids, society)

    def _parse_update(
        self, text: str, tokens: int,
        agent_ids: list[str], society: Society,
    ) -> MemoryUpdate:
        """Parse the Historian's structured response."""
        summary = ""
        themes: list[str] = []
        agent_notes: dict[str, str] = {}

        # Parse SUMMARY
        m = re.search(r"SUMMARY:\s*(.+?)(?=\nTHEMES:|\nAGENT_NOTES:|\Z)", text, re.DOTALL | re.IGNORECASE)
        if m:
            summary = m.group(1).strip()

        # Parse THEMES
        m = re.search(r"THEMES:\s*(.+?)(?=\nAGENT_NOTES:|\Z)", text, re.DOTALL | re.IGNORECASE)
        if m:
            raw_themes = m.group(1).strip()
            themes = [t.strip().lower() for t in raw_themes.split(",") if t.strip() and len(t.strip()) > 2]

        # Parse AGENT_NOTES
        notes_section = re.search(r"AGENT_NOTES:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
        if notes_section:
            name_to_id = {}
            for aid in agent_ids:
                if aid in society.agents:
                    name_to_id[society.agents[aid].name.lower()] = aid

            for line in notes_section.group(1).strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    name_part, note = line.split(":", 1)
                    name_clean = name_part.strip().lower()
                    # Match agent name
                    for name, aid in name_to_id.items():
                        if name in name_clean or name_clean in name:
                            agent_notes[aid] = note.strip()
                            break

        # Fallbacks
        if not summary:
            summary = society.society_summary or ""
        if not themes:
            themes = society.dominant_themes[:5]

        return MemoryUpdate(
            society_summary=summary,
            themes=themes[:5],
            agent_notes=agent_notes,
            tokens_used=tokens,
        )

    # -----------------------------------------------------------------------
    # Agent memory compression
    # -----------------------------------------------------------------------

    def compress_agent_memory_sync(self, agent: Agent, society: Society) -> str:
        """Compress an agent's memory when it gets too long."""
        role = society.roles.get(agent.role_id)
        role_name = role.name if role else "agent"

        prompt = (
            f"Compress this {role_name}'s memory to key facts only (max 400 chars). "
            f"Keep: decisions made, expertise gained, important outcomes. "
            f"Drop: redundant details.\n\n"
            f"MEMORY:\n{agent.memory_summary}"
        )
        compressed, _ = self._call_sync(prompt)
        return compressed if compressed else agent.memory_summary[:400]

    async def maybe_compress_agent(self, agent: Agent, society: Society, executor) -> bool:
        """Compress if over 1200 chars."""
        if len(agent.memory_summary) < 1200:
            return False
        loop = asyncio.get_event_loop()
        compressed = await loop.run_in_executor(
            executor, self.compress_agent_memory_sync, agent, society
        )
        agent.memory_summary = compressed
        return True

    # -----------------------------------------------------------------------
    # Async wrapper for orchestrator
    # -----------------------------------------------------------------------

    async def process_interaction(
        self,
        interaction: Interaction,
        society: Society,
        participating_agent_ids: list[str],
        executor,
    ) -> MemoryUpdate:
        loop = asyncio.get_event_loop()
        event_bus.emit(EventType.MEMORY_COMPRESSED, {
            "agent_name": "Historian", "agent_id": "historian",
        })
        update = await loop.run_in_executor(
            executor,
            self.process_interaction_sync,
            interaction, society, participating_agent_ids,
        )
        return update
