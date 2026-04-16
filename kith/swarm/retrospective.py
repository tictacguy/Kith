"""
Retrospective — the society examines its own performance.

Triggered every N interactions. The society's agents collectively
evaluate: what went well, what went wrong, what patterns emerge,
and what should change.

This is NOT a single LLM call summarizing stats. It's a multi-agent
process where different roles contribute their perspective:
  - Analyst/Elder: evaluates response quality
  - Critic: identifies recurring weaknesses
  - Governor: proposes structural changes

Output: a RetrospectiveReport with findings and actions taken.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..agents.caveman import CavemanBackend
from ..api.events import EventType, event_bus
from ..config import Config, make_backend
from ..society.state import Agent, Interaction, Society, SocietyPolicy


_RETROSPECTIVE_EVERY_N = 10  # trigger every N interactions


@dataclass
class RetrospectiveReport:
    """Output of a society retrospective."""
    timestamp: str = ""
    interaction_range: str = ""          # e.g. "interactions 11-20"
    quality_assessment: str = ""         # how good were recent responses
    recurring_weaknesses: list[str] = field(default_factory=list)
    recurring_strengths: list[str] = field(default_factory=list)
    proposed_actions: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)  # what was actually applied
    tokens_used: int = 0


class RetrospectiveEngine:
    """
    Runs a multi-perspective self-evaluation of the society.
    Uses existing agents' roles to get different viewpoints.
    """

    def __init__(self, cfg: Config) -> None:
        # Use higher token limit for retrospective — needs room for analysis
        saved = cfg.llm_max_tokens
        cfg.llm_max_tokens = max(saved, 2048)
        backend = make_backend(cfg)
        cfg.llm_max_tokens = saved
        self._backend = CavemanBackend(backend, intensity="full")  # full, not ultra — needs clarity

    def _call_sync(self, prompt: str) -> tuple[str, int]:
        result = self._backend.generate([{"role": "user", "content": prompt}])
        return result.get("content", "").strip(), result.get("output_tokens", 0)

    def should_run(self, society: Society) -> bool:
        return (
            society.total_interactions > 0
            and society.total_interactions % _RETROSPECTIVE_EVERY_N == 0
        )

    # -----------------------------------------------------------------------
    # Main retrospective process
    # -----------------------------------------------------------------------

    def run_sync(
        self,
        society: Society,
        recent_interactions: list[Interaction],
    ) -> RetrospectiveReport:
        if not recent_interactions:
            return RetrospectiveReport()

        report = RetrospectiveReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            interaction_range=f"interactions {max(1, society.total_interactions - len(recent_interactions) + 1)}-{society.total_interactions}",
        )
        total_tokens = 0

        # Build interaction digest for analysis
        digest = "\n".join(
            f"#{i+1} Q: {ix.user_prompt[:80]} | A: {ix.final_response[:100]} | "
            f"Agents: {len(ix.assigned_agents)} | Tokens: {ix.token_count} | "
            f"Tools: {','.join(ix.tools_used) or 'none'}"
            for i, ix in enumerate(recent_interactions[:10])
        )

        # Agent stats summary
        active = society.active_agents
        agent_stats = "\n".join(
            f"- {a.name} ({society.roles[a.role_id].name if a.role_id and a.role_id in society.roles else '?'}): "
            f"rep={a.reputation:.2f}, interactions={a.interaction_count}, "
            f"vetoed={a.vetoed_count}, debates_won={a.debates_won}/{a.debates_won + a.debates_lost}"
            for a in active[:10]
        )

        # Phase 1: Quality assessment (Elder/Analyst perspective)
        quality_prompt = (
            f"You are evaluating the quality of a society's recent decisions.\n\n"
            f"RECENT INTERACTIONS:\n{digest}\n\n"
            f"AGENT PERFORMANCE:\n{agent_stats}\n\n"
            f"ACTIVE POLICIES: {', '.join(p.name for p in society.active_policies) or 'none'}\n\n"
            f"Assess overall quality in 2-3 sentences. Were responses thorough? "
            f"Were the right agents mobilized? Was token usage efficient?"
        )
        quality, tokens = self._call_sync(quality_prompt)
        report.quality_assessment = quality
        total_tokens += tokens

        # Phase 2: Weakness/strength analysis (Critic perspective)
        analysis_prompt = (
            f"You are a Critic analyzing patterns in recent society decisions.\n\n"
            f"INTERACTIONS:\n{digest}\n\n"
            f"AGENTS:\n{agent_stats}\n\n"
            f"QUALITY ASSESSMENT: {quality}\n\n"
            f"Identify:\n"
            f"STRENGTHS: 2-3 recurring strengths (one per line, prefixed with '+ ')\n"
            f"WEAKNESSES: 2-3 recurring weaknesses (one per line, prefixed with '- ')\n"
            f"ACTIONS: 2-3 concrete actions to improve (one per line, prefixed with '> ')"
        )
        analysis, tokens = self._call_sync(analysis_prompt)
        total_tokens += tokens

        # Parse strengths, weaknesses, actions
        for line in analysis.split("\n"):
            line = line.strip()
            if line.startswith("+ "):
                report.recurring_strengths.append(line[2:].strip())
            elif line.startswith("- "):
                report.recurring_weaknesses.append(line[2:].strip())
            elif line.startswith("> "):
                report.proposed_actions.append(line[2:].strip())

        # Phase 3: Apply actions — convert proposals into concrete changes
        report.actions_taken = self._apply_actions(
            report.proposed_actions, society, report
        )

        report.tokens_used = total_tokens
        return report

    # -----------------------------------------------------------------------
    # Apply proposed actions
    # -----------------------------------------------------------------------

    def _apply_actions(
        self,
        proposals: list[str],
        society: Society,
        report: RetrospectiveReport,
    ) -> list[str]:
        """Convert proposed actions into concrete society changes."""
        actions_taken: list[str] = []
        existing_policy_names = {p.name for p in society.policies.values()}

        for proposal in proposals:
            proposal_lower = proposal.lower()

            # Pattern: proposal suggests a new policy/rule
            if any(kw in proposal_lower for kw in ["policy", "rule", "require", "enforce", "mandate"]):
                name = f"Retrospective: {proposal[:40]}"
                if name not in existing_policy_names:
                    policy = SocietyPolicy(name=name, rule=proposal)
                    society.policies[policy.id] = policy
                    actions_taken.append(f"Policy created: {name}")
                    existing_policy_names.add(name)

            # Pattern: proposal suggests focusing on quality
            elif any(kw in proposal_lower for kw in ["review", "quality", "check", "verify"]):
                name = "Retrospective: Quality Focus"
                if name not in existing_policy_names:
                    policy = SocietyPolicy(name=name, rule=proposal)
                    society.policies[policy.id] = policy
                    actions_taken.append(f"Policy created: {name}")
                    existing_policy_names.add(name)

            # Pattern: proposal about agent performance
            elif any(kw in proposal_lower for kw in ["agent", "role", "reassign", "train"]):
                actions_taken.append(f"Noted for evolution: {proposal[:60]}")

            else:
                actions_taken.append(f"Acknowledged: {proposal[:60]}")

        return actions_taken

    # -----------------------------------------------------------------------
    # Async wrapper
    # -----------------------------------------------------------------------

    async def maybe_run(
        self,
        society: Society,
        store,
        executor,
    ) -> RetrospectiveReport | None:
        if not self.should_run(society):
            return None

        event_bus.emit(EventType.RETROSPECTIVE_START, {
            "interaction_count": society.total_interactions,
        })

        recent = await store.recent_interactions(n=_RETROSPECTIVE_EVERY_N)

        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(
            executor, self.run_sync, society, recent,
        )

        event_bus.emit(EventType.RETROSPECTIVE_END, {
            "quality": report.quality_assessment[:100],
            "strengths": len(report.recurring_strengths),
            "weaknesses": len(report.recurring_weaknesses),
            "actions_taken": report.actions_taken,
        })

        return report
