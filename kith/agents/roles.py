from __future__ import annotations

from ..society.state import EvolutionStage, Role

# ---------------------------------------------------------------------------
# Seed roles — bootstrapped when society is first created
# ---------------------------------------------------------------------------

SEED_ROLES: list[Role] = [
    Role(
        id="role_elder",
        name="Elder",
        description="Synthesizes knowledge, makes final decisions, coordinates other agents",
        responsibilities=["synthesize responses", "resolve conflicts", "maintain coherence"],
        emerged_at_stage=EvolutionStage.PRIMITIVE,
    ),
    Role(
        id="role_scout",
        name="Scout",
        description="Explores new ideas, challenges assumptions, proposes novel angles",
        responsibilities=["divergent thinking", "hypothesis generation", "challenge consensus"],
        emerged_at_stage=EvolutionStage.PRIMITIVE,
    ),
    Role(
        id="role_builder",
        name="Builder",
        description="Translates ideas into concrete plans, structures, or code",
        responsibilities=["concrete implementation", "step-by-step plans", "tool usage"],
        emerged_at_stage=EvolutionStage.PRIMITIVE,
    ),
]

# Roles that emerge at later stages
TRIBAL_ROLES: list[Role] = [
    Role(
        id="role_critic",
        name="Critic",
        description="Analyzes response quality, finds logical flaws, weak arguments, and missing perspectives before deliberation",
        responsibilities=["quality analysis", "flaw detection", "argument strength assessment"],
        emerged_at_stage=EvolutionStage.TRIBAL,
    ),
    Role(
        id="role_tool_smith",
        name="Tool Smith",
        description="Designs and proposes new tools the society needs based on recurring tasks",
        responsibilities=["identify tool gaps", "propose tool specs", "document tool usage"],
        emerged_at_stage=EvolutionStage.TRIBAL,
    ),
]

ORGANIZED_ROLES: list[Role] = [
    Role(
        id="role_governor",
        name="Governor",
        description="Proposes and enforces society policies, manages agent hierarchy",
        responsibilities=["policy creation", "agent supervision", "conflict resolution"],
        supervises=["role_elder", "role_scout", "role_builder"],
        emerged_at_stage=EvolutionStage.ORGANIZED,
    ),
    Role(
        id="role_analyst",
        name="Analyst",
        description="Evaluates quality of responses, detects reasoning failures, reports to Governor",
        responsibilities=["quality control", "reasoning audit", "performance metrics"],
        emerged_at_stage=EvolutionStage.ORGANIZED,
    ),
]


def roles_for_stage(stage: EvolutionStage) -> list[Role]:
    roles = list(SEED_ROLES)
    if stage in (EvolutionStage.TRIBAL, EvolutionStage.ORGANIZED, EvolutionStage.COMPLEX):
        roles.extend(TRIBAL_ROLES)
    if stage in (EvolutionStage.ORGANIZED, EvolutionStage.COMPLEX):
        roles.extend(ORGANIZED_ROLES)
    return roles
