"""
Historian — vectorized society memory.

Instead of maintaining a global summary that pollutes every prompt,
the Historian extracts discrete FACTS from each interaction and
vectorizes them in ChromaDB. When agents need context, only
semantically relevant facts are retrieved.

Each fact has rich metadata: who was involved, what happened,
the outcome, and the topic domain.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from ..agents.caveman import CavemanBackend
from ..api.events import EventType, event_bus
from ..config import Config, make_backend
from ..society.state import Agent, Interaction, Society


@dataclass
class MemoryUpdate:
    facts: list[dict[str, str]]       # [{text, type, agents, topic}]
    themes: list[str]
    agent_notes: dict[str, str]       # agent_id → note
    tokens_used: int = 0


class Historian:
    def __init__(self, cfg: Config) -> None:
        backend = make_backend(cfg)
        self._backend = CavemanBackend(backend, intensity="ultra")

    def _call_sync(self, prompt: str) -> tuple[str, int]:
        result = self._backend.generate([{"role": "user", "content": prompt}])
        return result.get("content", "").strip(), result.get("output_tokens", 0)

    # -----------------------------------------------------------------------
    # Extract facts from an interaction
    # -----------------------------------------------------------------------

    def process_interaction_sync(
        self,
        interaction: Interaction,
        society: Society,
        participating_agent_ids: list[str],
    ) -> MemoryUpdate:
        agent_names = []
        for aid in participating_agent_ids:
            if aid in society.agents:
                a = society.agents[aid]
                role = society.roles.get(a.role_id)
                agent_names.append(f"{a.name} ({role.name if role else '?'})")

        prompt = (
            f"You are the Historian. Extract discrete facts from this interaction.\n\n"
            f"User asked: {interaction.user_prompt}\n"
            f"Agents: {', '.join(agent_names)}\n"
            f"Response: {interaction.final_response[:400]}\n"
            f"Tools used: {', '.join(interaction.tools_used) or 'none'}\n\n"
            f"Extract:\n"
            f"1. FACTS: 2-5 discrete, self-contained facts learned. Each on its own line prefixed with '- '.\n"
            f"   Each fact should make sense on its own without context.\n"
            f"2. THEMES: 3-5 specific topic keywords (not generic words).\n"
            f"3. AGENT_NOTES: For each agent, one sentence about what they contributed.\n\n"
            f"Format:\n"
            f"FACTS:\n- <fact 1>\n- <fact 2>\n"
            f"THEMES: <comma-separated>\n"
            f"AGENT_NOTES:\n<name>: <note>\n"
        )

        text, tokens = self._call_sync(prompt)
        return self._parse(text, tokens, participating_agent_ids, society)

    def _parse(self, text: str, tokens: int, agent_ids: list[str], society: Society) -> MemoryUpdate:
        facts: list[dict[str, str]] = []
        themes: list[str] = []
        agent_notes: dict[str, str] = {}

        # Parse FACTS
        facts_match = re.search(r"FACTS:\s*(.+?)(?=\nTHEMES:|\nAGENT_NOTES:|\Z)", text, re.DOTALL | re.IGNORECASE)
        if facts_match:
            for line in facts_match.group(1).strip().split("\n"):
                line = line.strip().lstrip("- ").strip()
                if line and len(line) > 10:
                    facts.append({"text": line})

        # Parse THEMES
        themes_match = re.search(r"THEMES:\s*(.+?)(?=\nAGENT_NOTES:|\Z)", text, re.DOTALL | re.IGNORECASE)
        if themes_match:
            themes = [t.strip().lower() for t in themes_match.group(1).strip().split(",") if t.strip() and len(t.strip()) > 2]

        # Parse AGENT_NOTES
        notes_match = re.search(r"AGENT_NOTES:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
        if notes_match:
            name_to_id = {}
            for aid in agent_ids:
                if aid in society.agents:
                    name_to_id[society.agents[aid].name.lower()] = aid
            for line in notes_match.group(1).strip().split("\n"):
                line = line.strip()
                if ":" in line:
                    name_part, note = line.split(":", 1)
                    name_clean = name_part.strip().lower()
                    for name, aid in name_to_id.items():
                        if name in name_clean or name_clean in name:
                            agent_notes[aid] = note.strip()
                            break

        return MemoryUpdate(facts=facts, themes=themes[:8], agent_notes=agent_notes, tokens_used=tokens)

    # -----------------------------------------------------------------------
    # Vectorize facts into ChromaDB
    # -----------------------------------------------------------------------

    def vectorize_facts(self, facts: list[dict[str, str]], interaction: Interaction, store) -> None:
        """Store each fact as a separate vector in ChromaDB with rich metadata."""
        for i, fact in enumerate(facts):
            doc_id = f"fact:{interaction.id}:{i}"
            store._vec.upsert(
                ids=[doc_id],
                documents=[fact["text"]],
                metadatas=[{
                    "type": "fact",
                    "interaction_id": interaction.id,
                    "prompt": interaction.user_prompt[:100],
                    "agents": ",".join(interaction.assigned_agents[:5]),
                    "themes": ",".join(interaction.themes[:5]),
                    "stage": interaction.society_stage_at_time.value,
                }],
            )

    # -----------------------------------------------------------------------
    # Retrieve relevant facts for a new prompt
    # -----------------------------------------------------------------------

    @staticmethod
    def retrieve_relevant_context(prompt: str, store, n: int = 8) -> list[str]:
        """Semantic search for facts relevant to the current prompt."""
        results = store.semantic_search(prompt, n=n, filter_type="fact")
        # Deduplicate and return fact texts
        seen = set()
        facts = []
        for r in results:
            text = r["document"]
            if text not in seen and r["distance"] < 0.8:  # relevance threshold
                seen.add(text)
                facts.append(text)
        return facts

    # -----------------------------------------------------------------------
    # Build society summary from recent facts (for Memory tab display only)
    # -----------------------------------------------------------------------

    def build_summary_sync(self, store, society: Society) -> str:
        """Build a summary from the most recent vectorized facts. For display only, NOT injected into prompts."""
        # Get recent facts
        try:
            results = store._vec.get(
                where={"type": "fact"},
                limit=20,
                include=["documents", "metadatas"],
            )
        except Exception:
            return society.society_summary or ""

        if not results or not results.get("documents"):
            return society.society_summary or ""

        docs = results["documents"]
        if not docs:
            return ""

        facts_text = "\n".join(f"- {d}" for d in docs[:15])

        prompt = (
            f"Summarize these facts about a society's history in 3-4 sentences. "
            f"Cover the breadth of topics, not just the latest.\n\n"
            f"FACTS:\n{facts_text}"
        )
        summary, _ = self._call_sync(prompt)
        return summary if summary else society.society_summary or ""

    # -----------------------------------------------------------------------
    # Agent memory compression
    # -----------------------------------------------------------------------

    def compress_agent_memory_sync(self, agent: Agent, society: Society) -> str:
        role = society.roles.get(agent.role_id)
        role_name = role.name if role else "agent"
        prompt = (
            f"Compress this {role_name}'s memory to key facts only (max 400 chars). "
            f"Keep: decisions, expertise, outcomes. Drop: redundant details.\n\n"
            f"MEMORY:\n{agent.memory_summary}"
        )
        compressed, _ = self._call_sync(prompt)
        return compressed if compressed else agent.memory_summary[:400]

    async def maybe_compress_agent(self, agent: Agent, society: Society, executor) -> bool:
        if len(agent.memory_summary) < 1200:
            return False
        loop = asyncio.get_event_loop()
        compressed = await loop.run_in_executor(executor, self.compress_agent_memory_sync, agent, society)
        agent.memory_summary = compressed
        return True

    # -----------------------------------------------------------------------
    # Async wrappers
    # -----------------------------------------------------------------------

    async def process_interaction(self, interaction, society, agent_ids, executor) -> MemoryUpdate:
        loop = asyncio.get_event_loop()
        event_bus.emit(EventType.MEMORY_COMPRESSED, {"agent_name": "Historian", "agent_id": "historian"})
        return await loop.run_in_executor(executor, self.process_interaction_sync, interaction, society, agent_ids)

    async def build_summary(self, store, society, executor) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, self.build_summary_sync, store, society)
