"""
Kith smoke tests — end-to-end with real Bedrock LLM calls.

Run: pytest tests/test_smoke.py -v -s
Requires: .env with valid AWS_BEARER_TOKEN_BEDROCK
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from kith.config import Config, make_backend
from kith.society.store import init_db, KithStore
from kith.society.state import Society, EvolutionStage
from kith.society.memory import MemoryCompressor
from kith.swarm.orchestrator import Orchestrator
from kith.agents.caveman import CavemanBackend

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TEST_DATA = Path("/tmp/kith_test_data")


@pytest.fixture(autouse=True)
async def clean_test_data():
    """Reset store singletons and wipe DB state between tests."""
    from kith.society.store import reset_singletons

    await reset_singletons()
    # Ensure directory exists (don't rmtree — ChromaDB Rust bindings hold file locks)
    _TEST_DATA.mkdir(parents=True, exist_ok=True)
    # Wipe SQLite by removing the file (engine is already disposed)
    db_file = _TEST_DATA / "kith.db"
    if db_file.exists():
        db_file.unlink()
    yield
    await reset_singletons()


@pytest.fixture
def cfg() -> Config:
    return Config(
        db_path=_TEST_DATA / "kith.db",
        chroma_path=_TEST_DATA / "chroma",
        chroma_collection="kith_test",
        max_reasoning_cycles=2,  # keep fast
        llm_max_tokens=512,
        initial_agent_count=3,
    )


# ---------------------------------------------------------------------------
# 1. Backend connectivity — can we talk to Bedrock?
# ---------------------------------------------------------------------------

def test_bedrock_backend_generates(cfg: Config):
    """Verify Bedrock returns a non-empty response."""
    backend = make_backend(cfg)
    result = backend.generate([{"role": "user", "content": "Say hello in 5 words."}])
    assert "content" in result
    assert len(result["content"]) > 0
    print(f"  Bedrock response: {result['content'][:100]}")
    print(f"  Tokens: in={result.get('input_tokens')}, out={result.get('output_tokens')}")


# ---------------------------------------------------------------------------
# 2. Caveman wrapping — does caveman compress output?
# ---------------------------------------------------------------------------

def test_caveman_wrapping(cfg: Config):
    """Verify CavemanBackend wraps and still produces output."""
    raw = make_backend(cfg)
    caveman = CavemanBackend(raw, intensity="full")
    result = caveman.generate([{"role": "user", "content": "Explain what a database index is."}])
    text = result["content"]
    assert len(text) > 0
    print(f"  Caveman output ({len(text)} chars): {text[:200]}")


# ---------------------------------------------------------------------------
# 3. Society bootstrap — boot creates agents, roles, tools in DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_society_bootstrap(cfg: Config):
    """Boot a fresh society and verify state is persisted."""
    orc = Orchestrator(cfg)
    society = await orc.boot()

    assert society.stage == EvolutionStage.PRIMITIVE
    assert len(society.agents) == cfg.initial_agent_count
    assert len(society.roles) >= 3  # Elder, Scout, Builder
    assert len(society.tools) >= 2  # summarize, search_memory

    # Verify persistence — reload from DB
    store = KithStore(cfg)
    loaded = await store.load_society()
    assert loaded is not None
    assert loaded.stage == EvolutionStage.PRIMITIVE

    agents = await store.load_agents()
    assert len(agents) == cfg.initial_agent_count

    roles = await store.load_roles()
    assert len(roles) >= 3

    print(f"  Society: {len(society.agents)} agents, {len(society.roles)} roles, {len(society.tools)} tools")
    for a in society.agents.values():
        print(f"    Agent: {a.name} (role={a.role_id})")


# ---------------------------------------------------------------------------
# 4. Full prompt cycle — process a prompt end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_prompt_cycle(cfg: Config):
    """Process a prompt through the society and verify interaction is persisted."""
    orc = Orchestrator(cfg)
    await orc.boot()

    interaction = await orc.process("What are the pros and cons of microservices?")

    assert interaction.final_response
    assert len(interaction.final_response) > 10
    assert len(interaction.assigned_agents) > 0
    assert len(interaction.themes) > 0
    assert interaction.society_stage_at_time == EvolutionStage.PRIMITIVE

    # Verify persisted
    store = orc.store
    recent = await store.recent_interactions(n=1)
    assert len(recent) == 1
    assert recent[0].id == interaction.id

    # Verify society interaction count incremented
    society = orc.society
    assert society.total_interactions == 1

    print(f"  Response ({len(interaction.final_response)} chars): {interaction.final_response[:200]}")
    print(f"  Agents: {interaction.assigned_agents}")
    print(f"  Themes: {interaction.themes}")
    print(f"  Tokens: {interaction.token_count}")


# ---------------------------------------------------------------------------
# 5. Semantic memory — vectorized interactions are searchable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_memory(cfg: Config):
    """After processing a prompt, semantic search should find it."""
    orc = Orchestrator(cfg)
    await orc.boot()

    await orc.process("How does Kubernetes handle pod scheduling?")

    results = orc.store.semantic_search("kubernetes scheduling", n=3)
    assert len(results) > 0
    assert any("kubernetes" in r["document"].lower() or "scheduling" in r["document"].lower() for r in results)

    print(f"  Search results: {len(results)}")
    for r in results:
        print(f"    [{r['distance']:.3f}] {r['document'][:80]}")


# ---------------------------------------------------------------------------
# 6. Memory compression — verify compressor works on long memory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_compression(cfg: Config):
    """Verify MemoryCompressor compresses long agent memory."""
    from concurrent.futures import ThreadPoolExecutor

    orc = Orchestrator(cfg)
    society = await orc.boot()

    compressor = MemoryCompressor(cfg)
    agent = list(society.agents.values())[0]

    # Stuff agent memory beyond threshold
    agent.memory_summary = "Important context about microservices. " * 50  # ~1900 chars
    original_len = len(agent.memory_summary)
    assert original_len > 1200

    executor = ThreadPoolExecutor(max_workers=2)
    compressed = await compressor.maybe_compress(agent, society, executor)
    executor.shutdown(wait=False)

    assert compressed is True
    assert len(agent.memory_summary) < original_len
    assert len(agent.memory_summary) > 0

    print(f"  Before: {original_len} chars")
    print(f"  After:  {len(agent.memory_summary)} chars")
    print(f"  Compressed: {agent.memory_summary[:200]}")


# ---------------------------------------------------------------------------
# 7. Multi-prompt persistence — society state accumulates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_prompt_persistence(cfg: Config):
    """Process two prompts and verify state accumulates correctly."""
    orc = Orchestrator(cfg)
    await orc.boot()

    i1 = await orc.process("Explain REST APIs briefly.")
    i2 = await orc.process("What is GraphQL and how does it differ from REST?")

    society = orc.society
    assert society.total_interactions == 2

    recent = await orc.store.recent_interactions(n=5)
    assert len(recent) == 2

    # Themes should accumulate
    assert len(society.dominant_themes) > 0

    # Agent interaction counts should have incremented
    for a in society.active_agents:
        assert a.interaction_count >= 1

    print(f"  Interactions: {society.total_interactions}")
    print(f"  Themes: {society.dominant_themes}")
    print(f"  Response 1: {i1.final_response[:100]}")
    print(f"  Response 2: {i2.final_response[:100]}")


# ---------------------------------------------------------------------------
# 8. Supervisor assignment — verify supervisor_id is set at ORGANIZED stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_supervisor_assignment(cfg: Config):
    """Verify that evolving to ORGANIZED assigns supervisor_id on agents."""
    from kith.society.evolution import EvolutionEngine
    from kith.society.state import Society, EvolutionStage
    from kith.agents.roles import SEED_ROLES, TRIBAL_ROLES, ORGANIZED_ROLES

    engine = EvolutionEngine(cfg)

    # Build a society at TRIBAL stage ready to evolve to ORGANIZED
    society = Society(stage=EvolutionStage.TRIBAL, total_interactions=30)
    for role in SEED_ROLES + TRIBAL_ROLES:
        society.roles[role.id] = role

    # Spawn agents for each seed role
    from kith.society.state import Agent
    for i, role in enumerate(SEED_ROLES):
        agent = Agent(
            name=f"{role.name}_{i+1}",
            role_id=role.id,
            expertise_domains=role.responsibilities[:2],
        )
        society.agents[agent.id] = agent

    # Evolve to ORGANIZED
    society, changelog = engine.evolve(society)

    assert society.stage == EvolutionStage.ORGANIZED
    assert "role_governor" in society.roles

    # Check that at least one agent has supervisor_id set
    supervised = [a for a in society.active_agents if a.supervisor_id is not None]
    assert len(supervised) > 0, "No agents have supervisor_id after ORGANIZED evolution"

    # Verify the supervisor is a Governor
    for a in supervised:
        sup = society.agents[a.supervisor_id]
        assert sup.role_id == "role_governor", f"Supervisor {sup.name} is not Governor"

    print(f"  Stage: {society.stage.value}")
    print(f"  Supervised agents: {len(supervised)}")
    for a in supervised:
        sup = society.agents[a.supervisor_id]
        print(f"    {a.name} ({a.role_id}) → supervised by {sup.name}")
    print(f"  Changelog: {changelog}")


# ---------------------------------------------------------------------------
# 9. Tool execution — verify tool calls are parsed and executed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_execution_parsing():
    """Verify tool call parsing and execution works."""
    from kith.tools.executor import parse_tool_calls, execute_tool_calls
    from kith.tools.registry import build_default_registry, BUILTIN_TOOLS

    # Test parsing
    text = 'Need info. TOOL_CALL: search_memory(query="kubernetes pods") then summarize.'
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0][0] == "search_memory"
    assert "query" in calls[0][1]

    # Test with multiple calls
    text2 = (
        'TOOL_CALL: summarize(text="long text here")\n'
        'Also TOOL_CALL: search_memory(query="REST API")'
    )
    calls2 = parse_tool_calls(text2)
    assert len(calls2) == 2

    # Test execution with registry
    registry = build_default_registry()
    name_to_id = {spec.name: spec.id for spec, _ in BUILTIN_TOOLS}

    results = await execute_tool_calls(
        'TOOL_CALL: summarize(text="hello world this is a test")',
        registry,
        name_to_id,
    )
    assert len(results) == 1
    assert results[0].success is True
    assert "summary" in str(results[0].result).lower()

    # Test unknown tool
    results2 = await execute_tool_calls(
        'TOOL_CALL: nonexistent_tool(x=1)',
        registry,
        name_to_id,
    )
    assert len(results2) == 1
    assert results2[0].success is False

    print(f"  Parse test: {len(calls)} calls found")
    print(f"  Execution test: {results[0].result}")
    print(f"  Unknown tool test: {results2[0].error}")


# ---------------------------------------------------------------------------
# 10. Society memory — global summary compression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_society_memory_compression(cfg: Config):
    """Verify SocietyMemoryKeeper compresses global society summary."""
    from concurrent.futures import ThreadPoolExecutor
    from kith.society.memory import SocietyMemoryKeeper
    from kith.society.state import Society, Interaction, EvolutionStage

    keeper = SocietyMemoryKeeper(cfg)

    # Build a society at interaction 5 (triggers compression)
    society = Society(total_interactions=5)

    # Fake some interactions
    interactions = [
        Interaction(
            user_prompt=f"Question about topic {i}",
            final_response=f"Answer about topic {i} with details",
            themes=[f"topic{i}", "general"],
        )
        for i in range(10)
    ]

    assert keeper.should_compress(society)

    executor = ThreadPoolExecutor(max_workers=2)
    compressed = await keeper.maybe_compress(society, interactions, executor)
    executor.shutdown(wait=False)

    assert compressed is True
    assert len(society.society_summary) > 0
    assert len(society.society_summary) < 1000

    print(f"  Society summary ({len(society.society_summary)} chars): {society.society_summary[:200]}")


# ---------------------------------------------------------------------------
# 11. Per-role caveman intensity
# ---------------------------------------------------------------------------

def test_per_role_caveman_intensity():
    """Verify each role gets the correct caveman intensity."""
    from kith.agents.base import intensity_for_role

    assert intensity_for_role("Scout") == "lite"
    assert intensity_for_role("Builder") == "ultra"
    assert intensity_for_role("Critic") == "full"
    assert intensity_for_role("Tool Smith") == "ultra"
    assert intensity_for_role("Elder") == "full"
    assert intensity_for_role("Governor") == "full"
    assert intensity_for_role("Analyst") == "full"
    assert intensity_for_role(None) == "full"
    assert intensity_for_role("UnknownRole") == "full"

    print("  All role intensities correct")


@pytest.mark.asyncio
async def test_role_intensity_affects_output(cfg: Config):
    """Verify different roles use different caveman intensities and produce output."""
    from kith.agents.base import KithAgent, intensity_for_role
    from kith.agents.roles import SEED_ROLES
    from kith.society.state import Society, Agent

    society = Society()
    for role in SEED_ROLES:
        society.roles[role.id] = role

    prompt = "Explain what a load balancer does."

    # Builder = ultra (max compression)
    builder_role = society.roles["role_builder"]
    builder = Agent(name="Builder_test", role_id="role_builder")
    ka_builder = KithAgent(agent=builder, role=builder_role, cfg=cfg)

    # Elder = full
    elder_role = society.roles["role_elder"]
    elder = Agent(name="Elder_test", role_id="role_elder")
    ka_elder = KithAgent(agent=elder, role=elder_role, cfg=cfg)

    builder_resp, _ = ka_builder.run(prompt, society)
    elder_resp, _ = ka_elder.run(prompt, society)

    print(f"  Builder (ultra, {len(builder_resp)} chars): {builder_resp[:150]}")
    print(f"  Elder (full, {len(elder_resp)} chars): {elder_resp[:150]}")

    # Both should produce content
    assert len(builder_resp) > 0, "Builder produced empty output"
    assert len(elder_resp) > 0, "Elder produced empty output"

    # Verify the intensity mapping is correct
    assert intensity_for_role("Builder") == "ultra"
    assert intensity_for_role("Elder") == "full"
    assert intensity_for_role("Scout") == "lite"


# ---------------------------------------------------------------------------
# 12. Agent management — dormant/active toggle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_status_management(cfg: Config):
    """Verify agents can be set to dormant and back to active."""
    orc = Orchestrator(cfg)
    await orc.boot()
    society = orc.society

    agent = list(society.agents.values())[0]
    assert agent.status.value == "active"

    # Set dormant
    from kith.society.state import AgentStatus
    updated = await orc.set_agent_status(agent.id, AgentStatus.DORMANT)
    assert updated.status == AgentStatus.DORMANT

    # Dormant agent should not be in active_agents
    assert agent.id not in [a.id for a in society.active_agents]

    # Reactivate
    updated = await orc.set_agent_status(agent.id, AgentStatus.ACTIVE)
    assert updated.status == AgentStatus.ACTIVE
    assert agent.id in [a.id for a in society.active_agents]

    print(f"  Agent {agent.name}: active → dormant → active")


# ---------------------------------------------------------------------------
# 13. Role reassignment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_role_reassignment(cfg: Config):
    """Verify an agent can be reassigned to a different role."""
    orc = Orchestrator(cfg)
    await orc.boot()
    society = orc.society

    # Find the Scout agent
    scout = next(a for a in society.agents.values() if a.role_id == "role_scout")
    original_role = scout.role_id

    # Reassign to Builder
    updated = await orc.reassign_role(scout.id, "role_builder")
    assert updated.role_id == "role_builder"
    assert updated.role_id != original_role

    print(f"  {scout.name}: {original_role} → {updated.role_id}")


# ---------------------------------------------------------------------------
# 14. Policy management — add, update, deactivate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_management(cfg: Config):
    """Verify policies can be added, updated, and deactivated."""
    orc = Orchestrator(cfg)
    await orc.boot()
    society = orc.society

    # Add a custom policy
    policy = await orc.add_policy(
        name="Test Policy",
        rule="All agents must cite sources.",
        applies_to_roles=["role_scout"],
    )
    assert policy.id in society.policies
    assert policy.active is True

    # Update rule text
    updated = await orc.update_policy(policy.id, rule="All agents must cite at least 2 sources.")
    assert "2 sources" in updated.rule

    # Deactivate
    deactivated = await orc.update_policy(policy.id, active=False)
    assert deactivated.active is False
    assert policy.id not in [p.id for p in society.active_policies]

    print(f"  Policy '{policy.name}': created → updated → deactivated")


# ---------------------------------------------------------------------------
# 15. Processing guard — concurrent calls rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_processing_guard(cfg: Config):
    """Verify that concurrent process() calls are rejected."""
    orc = Orchestrator(cfg)
    await orc.boot()

    # Manually set processing flag
    orc._processing = True

    with pytest.raises(RuntimeError, match="already processing"):
        await orc.process("This should fail")

    orc._processing = False
    print("  Concurrent processing guard works")


# ---------------------------------------------------------------------------
# 16. Graceful shutdown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_graceful_shutdown(cfg: Config):
    """Verify shutdown persists state and closes executor."""
    orc = Orchestrator(cfg)
    await orc.boot()

    # Process one prompt to have state
    await orc.process("What is Docker?")
    assert orc.society.total_interactions == 1

    # Shutdown
    await orc.shutdown()

    # Verify state was persisted by loading from a fresh store
    from kith.society.store import KithStore
    store = KithStore(cfg)
    loaded = await store.load_society()
    assert loaded is not None
    assert loaded.total_interactions == 1

    print(f"  Shutdown complete, state persisted ({loaded.total_interactions} interactions)")
