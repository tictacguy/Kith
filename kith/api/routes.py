from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import Config, get_config
from ..society.state import AgentStatus, ToolSpec
from ..swarm.orchestrator import Orchestrator

router = APIRouter()

# ---------------------------------------------------------------------------
# Shared orchestrator singleton
# ---------------------------------------------------------------------------

_orchestrator: Orchestrator | None = None


async def get_orchestrator(cfg: Config = Depends(get_config)) -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator(cfg)
        await _orchestrator.boot()
    return _orchestrator


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PromptRequest(BaseModel):
    prompt: str

class PromptResponse(BaseModel):
    interaction_id: str
    response: str
    agents_used: list[str]
    themes: list[str]
    society_stage: str
    token_count: int

class SocietyResponse(BaseModel):
    stage: str
    total_interactions: int
    active_agents: int
    roles: list[str]
    tools: list[str]
    policies: list[str]
    dominant_themes: list[str]
    society_summary: str
    is_processing: bool

class AgentResponse(BaseModel):
    id: str
    name: str
    role: str | None
    status: str
    expertise: list[str]
    interaction_count: int
    memory_summary: str
    supervisor_id: str | None

class EvolutionResponse(BaseModel):
    evolved: bool
    new_stage: str | None
    changelog: list[str]

class ToolProposalResponse(BaseModel):
    proposals: list[dict]

class RegisterToolRequest(BaseModel):
    name: str
    description: str
    parameters: dict = {}
    handler_ref: str

class SupervisionAuditResponse(BaseModel):
    reviews: list[dict]

class AgentStatusRequest(BaseModel):
    status: str  # active | dormant | retired

class ReassignRoleRequest(BaseModel):
    role_id: str

class RenameAgentRequest(BaseModel):
    name: str

class UpdatePolicyRequest(BaseModel):
    rule: str | None = None
    active: bool | None = None

class AddPolicyRequest(BaseModel):
    name: str
    rule: str
    applies_to_roles: list[str] = []


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------

@router.post("/prompt", response_model=PromptResponse)
async def process_prompt(
    req: PromptRequest,
    orc: Orchestrator = Depends(get_orchestrator),
) -> PromptResponse:
    try:
        interaction = await orc.process(req.prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    society = orc.society
    return PromptResponse(
        interaction_id=interaction.id,
        response=interaction.final_response,
        agents_used=[
            society.agents[aid].name
            for aid in interaction.assigned_agents
            if aid in society.agents
        ],
        themes=interaction.themes,
        society_stage=interaction.society_stage_at_time.value,
        token_count=interaction.token_count,
    )


@router.get("/society", response_model=SocietyResponse)
async def get_society(orc: Orchestrator = Depends(get_orchestrator)) -> SocietyResponse:
    s = orc.society
    if s is None:
        raise HTTPException(status_code=503, detail="Society not initialized")
    return SocietyResponse(
        stage=s.stage.value,
        total_interactions=s.total_interactions,
        active_agents=len(s.active_agents),
        roles=[r.name for r in s.roles.values()],
        tools=[t.name for t in s.tools.values()],
        policies=[p.name for p in s.active_policies],
        dominant_themes=s.dominant_themes,
        society_summary=s.society_summary,
        is_processing=orc.is_processing,
    )


@router.get("/agents", response_model=list[AgentResponse])
async def list_agents(orc: Orchestrator = Depends(get_orchestrator)) -> list[AgentResponse]:
    s = orc.society
    if s is None:
        raise HTTPException(status_code=503, detail="Society not initialized")
    return [
        AgentResponse(
            id=a.id,
            name=a.name,
            role=s.roles[a.role_id].name if a.role_id and a.role_id in s.roles else None,
            status=a.status.value,
            expertise=a.expertise_domains,
            interaction_count=a.interaction_count,
            memory_summary=a.memory_summary,
            supervisor_id=a.supervisor_id,
        )
        for a in s.agents.values()
    ]


@router.get("/interactions/recent")
async def recent_interactions(
    n: int = 10,
    orc: Orchestrator = Depends(get_orchestrator),
):
    interactions = await orc.store.recent_interactions(n=n)
    return [
        {
            "id": i.id,
            "prompt": i.user_prompt,
            "response": i.final_response,
            "themes": i.themes,
            "stage": i.society_stage_at_time.value,
            "agents": i.assigned_agents,
            "tools_used": i.tools_used,
            "tokens": i.token_count,
            "created_at": i.created_at.isoformat(),
        }
        for i in interactions
    ]


@router.get("/memory/search")
async def search_memory(
    q: str,
    n: int = 5,
    orc: Orchestrator = Depends(get_orchestrator),
):
    return orc.store.semantic_search(q, n=n)


@router.post("/society/evolve", response_model=EvolutionResponse)
async def force_evolve(orc: Orchestrator = Depends(get_orchestrator)) -> EvolutionResponse:
    s = orc.society
    if s is None:
        raise HTTPException(status_code=503, detail="Society not initialized")
    if not orc._evolution.should_evolve(s):
        return EvolutionResponse(evolved=False, new_stage=None, changelog=[])
    s, changelog = orc._evolution.evolve(s)
    await orc.store.save_society(s)
    return EvolutionResponse(evolved=True, new_stage=s.stage.value, changelog=changelog)


@router.post("/society/reset")
async def reset_society(orc: Orchestrator = Depends(get_orchestrator)):
    """Wipe all state — interactions, memories, tools — and start fresh."""
    try:
        society = await orc.reset_society()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "reset", "stage": society.stage.value, "agents": len(society.agents)}


# ---------------------------------------------------------------------------
# Agent management
# ---------------------------------------------------------------------------

@router.patch("/agents/{agent_id}/status")
async def set_agent_status(
    agent_id: str,
    req: AgentStatusRequest,
    orc: Orchestrator = Depends(get_orchestrator),
):
    try:
        status = AgentStatus(req.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}. Use: active, dormant, retired")
    try:
        agent = await orc.set_agent_status(agent_id, status)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"id": agent.id, "name": agent.name, "status": agent.status.value}


@router.patch("/agents/{agent_id}/role")
async def reassign_agent_role(
    agent_id: str,
    req: ReassignRoleRequest,
    orc: Orchestrator = Depends(get_orchestrator),
):
    try:
        agent = await orc.reassign_role(agent_id, req.role_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    s = orc.society
    return {
        "id": agent.id,
        "name": agent.name,
        "role_id": agent.role_id,
        "role_name": s.roles[agent.role_id].name if agent.role_id and agent.role_id in s.roles else None,
        "supervisor_id": agent.supervisor_id,
    }


@router.patch("/agents/{agent_id}/name")
async def rename_agent(
    agent_id: str,
    req: RenameAgentRequest,
    orc: Orchestrator = Depends(get_orchestrator),
):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    try:
        agent = await orc.rename_agent(agent_id, req.name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"id": agent.id, "name": agent.name}


# ---------------------------------------------------------------------------
# Policy management
# ---------------------------------------------------------------------------

@router.get("/policies")
async def list_policies(orc: Orchestrator = Depends(get_orchestrator)):
    s = orc.society
    if s is None:
        raise HTTPException(status_code=503, detail="Society not initialized")
    return [
        {
            "id": p.id,
            "name": p.name,
            "rule": p.rule,
            "applies_to_roles": p.applies_to_roles,
            "active": p.active,
            "created_at": p.created_at.isoformat(),
        }
        for p in s.policies.values()
    ]


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    req: UpdatePolicyRequest,
    orc: Orchestrator = Depends(get_orchestrator),
):
    try:
        policy = await orc.update_policy(policy_id, rule=req.rule, active=req.active)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"id": policy.id, "name": policy.name, "rule": policy.rule, "active": policy.active}


@router.post("/policies")
async def add_policy(
    req: AddPolicyRequest,
    orc: Orchestrator = Depends(get_orchestrator),
):
    try:
        policy = await orc.add_policy(req.name, req.rule, req.applies_to_roles)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"id": policy.id, "name": policy.name, "rule": policy.rule}


# ---------------------------------------------------------------------------
# Tool endpoints
# ---------------------------------------------------------------------------

@router.post("/tools/propose", response_model=ToolProposalResponse)
async def propose_tools(orc: Orchestrator = Depends(get_orchestrator)) -> ToolProposalResponse:
    proposals = await orc.propose_tools()
    return ToolProposalResponse(
        proposals=[
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "handler_ref": t.handler_ref,
            }
            for t in proposals
        ]
    )


@router.post("/tools/register")
async def register_tool(
    req: RegisterToolRequest,
    orc: Orchestrator = Depends(get_orchestrator),
):
    spec = ToolSpec(
        name=req.name,
        description=req.description,
        parameters=req.parameters,
        handler_ref=req.handler_ref,
    )
    await orc.register_tool(spec)
    return {"registered": spec.id, "name": spec.name}


@router.get("/tools")
async def list_tools(orc: Orchestrator = Depends(get_orchestrator)):
    s = orc.society
    if s is None:
        raise HTTPException(status_code=503, detail="Society not initialized")
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "usage_count": t.usage_count,
        }
        for t in s.tools.values()
    ]


# ---------------------------------------------------------------------------
# Supervision audit
# ---------------------------------------------------------------------------

@router.get("/supervision/last", response_model=SupervisionAuditResponse)
async def last_supervision_audit(
    orc: Orchestrator = Depends(get_orchestrator),
) -> SupervisionAuditResponse:
    return SupervisionAuditResponse(
        reviews=[
            {
                "agent_id": s.agent_id,
                "agent_name": s.agent_name,
                "supervisor_id": s.supervisor_id,
                "supervisor_name": s.supervisor_name,
                "verdict": s.supervisor_verdict,
                "raw_response": s.raw_response[:200],
                "final_response": s.final_response[:200],
            }
            for s in orc._last_supervised
        ]
    )


# ---------------------------------------------------------------------------
# Roles listing
# ---------------------------------------------------------------------------

@router.get("/roles")
async def list_roles(orc: Orchestrator = Depends(get_orchestrator)):
    s = orc.society
    if s is None:
        raise HTTPException(status_code=503, detail="Society not initialized")
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "responsibilities": r.responsibilities,
            "supervises": r.supervises,
            "emerged_at_stage": r.emerged_at_stage.value,
        }
        for r in s.roles.values()
    ]


# ---------------------------------------------------------------------------
# LLM provider configuration (for frontend)
# ---------------------------------------------------------------------------

class LLMConfigRequest(BaseModel):
    backend: str  # openai | anthropic | bedrock | ollama
    model: str | None = None
    api_key: str | None = None  # for openai/anthropic
    aws_token: str | None = None  # for bedrock
    aws_region: str | None = None
    ollama_url: str | None = None
    max_tokens: int | None = None


@router.get("/config/llm")
async def get_llm_config(orc: Orchestrator = Depends(get_orchestrator)):
    cfg = orc._cfg
    return {
        "backend": cfg.llm_backend,
        "model": cfg.llm_model,
        "max_tokens": cfg.llm_max_tokens,
        "ollama_base_url": cfg.ollama_base_url,
        "aws_region": cfg.aws_region,
        # Never expose full keys — just whether they're set
        "openai_key_set": bool(cfg.openai_api_key),
        "anthropic_key_set": bool(cfg.anthropic_api_key),
        "bedrock_token_set": bool(cfg.aws_bearer_token),
    }


@router.put("/config/llm")
async def set_llm_config(
    req: LLMConfigRequest,
    orc: Orchestrator = Depends(get_orchestrator),
):
    """
    Switch LLM provider at runtime. Takes effect on next agent call.
    Society state is preserved — only the backend changes.
    """
    valid = {"openai", "anthropic", "bedrock", "ollama"}
    if req.backend not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid backend: {req.backend}. Use: {valid}")

    cfg = orc._cfg
    cfg.llm_backend = req.backend

    if req.model:
        cfg.llm_model = req.model
    if req.max_tokens:
        cfg.llm_max_tokens = req.max_tokens
    if req.api_key:
        if req.backend == "openai":
            cfg.openai_api_key = req.api_key
        elif req.backend == "anthropic":
            cfg.anthropic_api_key = req.api_key
    if req.aws_token:
        cfg.aws_bearer_token = req.aws_token
    if req.aws_region:
        cfg.aws_region = req.aws_region
    if req.ollama_url:
        cfg.ollama_base_url = req.ollama_url

    return {
        "backend": cfg.llm_backend,
        "model": cfg.llm_model,
        "max_tokens": cfg.llm_max_tokens,
    }
