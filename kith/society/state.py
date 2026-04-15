from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentStatus(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    RETIRED = "retired"


class EvolutionStage(str, Enum):
    PRIMITIVE = "primitive"       # 1-3 agents, no tools, no hierarchy
    TRIBAL = "tribal"             # 4-10 agents, basic tools, loose roles
    ORGANIZED = "organized"       # 11-25 agents, specialized roles, tool chains
    COMPLEX = "complex"           # 26+ agents, meta-agents, governance


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class ToolSpec(BaseModel):
    """A tool the society has developed and can use."""
    id: str = Field(default_factory=_uid)
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    handler_ref: str  # dotted import path to async callable
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    usage_count: int = 0


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------

class Role(BaseModel):
    """A role within the society. Roles emerge from usage patterns."""
    id: str = Field(default_factory=_uid)
    name: str
    description: str
    responsibilities: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)  # tool ids
    supervises: list[str] = Field(default_factory=list)     # role ids
    emerged_at_stage: EvolutionStage = EvolutionStage.PRIMITIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent(BaseModel):
    """A persistent member of the Kith society."""
    id: str = Field(default_factory=_uid)
    name: str
    role_id: str | None = None
    status: AgentStatus = AgentStatus.ACTIVE
    personality_traits: list[str] = Field(default_factory=list)
    expertise_domains: list[str] = Field(default_factory=list)
    memory_summary: str = ""          # compressed episodic memory
    interaction_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    supervisor_id: str | None = None  # agent id of supervisor

    # Reputation metrics (updated after each interaction)
    reputation: float = 0.5           # 0.0 = terrible, 1.0 = excellent
    vetoed_count: int = 0             # times supervisor vetoed this agent
    approved_count: int = 0           # times supervisor approved
    debates_won: int = 0
    debates_lost: int = 0
    delegations_received: int = 0     # times peers delegated to this agent (trust)
    consensus_agreements: int = 0     # times voted with majority
    consensus_dissents: int = 0       # times voted against majority
    previous_role_id: str | None = None  # for demotion tracking


# ---------------------------------------------------------------------------
# Society
# ---------------------------------------------------------------------------

class SocietyPolicy(BaseModel):
    """Internal governance rules that evolve over time."""
    id: str = Field(default_factory=_uid)
    name: str
    rule: str                          # natural language rule injected into agent prompts
    applies_to_roles: list[str] = Field(default_factory=list)  # empty = all
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = True


class Society(BaseModel):
    """The persistent society state."""
    id: str = "kith_society"
    stage: EvolutionStage = EvolutionStage.PRIMITIVE
    agents: dict[str, Agent] = Field(default_factory=dict)
    roles: dict[str, Role] = Field(default_factory=dict)
    tools: dict[str, ToolSpec] = Field(default_factory=dict)
    policies: dict[str, SocietyPolicy] = Field(default_factory=dict)
    total_interactions: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Thematic memory — what topics has the user engaged with
    dominant_themes: list[str] = Field(default_factory=list)

    # Global compressed memory maintained by Memory Keeper
    society_summary: str = ""

    @property
    def active_agents(self) -> list[Agent]:
        return [a for a in self.agents.values() if a.status == AgentStatus.ACTIVE]

    @property
    def active_policies(self) -> list[SocietyPolicy]:
        return [p for p in self.policies.values() if p.active]


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------

class Interaction(BaseModel):
    """A single user↔society exchange, persisted for memory and evolution."""
    id: str = Field(default_factory=_uid)
    user_prompt: str
    assigned_agents: list[str] = Field(default_factory=list)  # agent ids
    responses: dict[str, str] = Field(default_factory=dict)   # agent_id → response
    final_response: str = ""
    themes: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    society_stage_at_time: EvolutionStage = EvolutionStage.PRIMITIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    token_count: int = 0
