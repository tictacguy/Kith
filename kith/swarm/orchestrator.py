from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from ..agents.base import KithAgent
from ..agents.roles import SEED_ROLES
from ..api.events import EventType, event_bus
from ..config import Config, make_backend
from ..society.evolution import EvolutionEngine
from ..society.historian import Historian
from ..society.state import (
    Agent, AgentStatus, EvolutionStage, Interaction, Society, SocietyPolicy, ToolSpec,
)
from ..society.reputation import record_verdict, check_lifecycle, update_reputation
from ..society.relationships import (
    record_co_participation, record_supervision_veto, record_supervision_approval,
    get_top_allies,
)
from ..society.store import KithStore
from ..swarm.deliberation import DeliberationEngine
from ..swarm.mobilization import MobilizationEngine
from ..swarm.retrospective import RetrospectiveEngine
from ..swarm.supervision import SupervisionChain, SupervisedResponse
from ..tools.executor import execute_tool_calls, format_tool_results
from ..tools.proposer import ToolProposer
from ..tools.registry import ToolRegistry, build_default_registry


class Orchestrator:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._store = KithStore(cfg)
        self._evolution = EvolutionEngine(cfg)
        self._tool_registry: ToolRegistry = build_default_registry()
        self._historian = Historian(cfg)
        self._deliberation = DeliberationEngine(cfg)
        self._mobilization = MobilizationEngine(cfg)
        self._retrospective = RetrospectiveEngine(cfg)
        self._supervision = SupervisionChain(cfg, self._evolution)
        self._tool_proposer = ToolProposer(cfg)
        self._society: Society | None = None
        self._executor = ThreadPoolExecutor(max_workers=cfg.max_agents)
        self._last_supervised: list[SupervisedResponse] = []
        self._processing = False

    # -- helpers --
    def _emit(self, t: EventType, data=None):
        event_bus.emit(t, data)

    def _snapshot(self) -> dict:
        """Build a full society snapshot for WebSocket clients."""
        s = self._society
        if s is None:
            return {}
        return {
            "stage": s.stage.value,
            "total_interactions": s.total_interactions,
            "society_summary": s.society_summary,
            "dominant_themes": s.dominant_themes,
            "is_processing": self._processing,
            "agents": [
                {
                    "id": a.id, "name": a.name, "role": s.roles[a.role_id].name if a.role_id and a.role_id in s.roles else None,
                    "role_id": a.role_id, "status": a.status.value, "interaction_count": a.interaction_count,
                    "memory_summary": a.memory_summary, "supervisor_id": a.supervisor_id,
                    "expertise": a.expertise_domains,
                    "reputation": round(a.reputation, 2),
                    "vetoed_count": a.vetoed_count,
                    "approved_count": a.approved_count,
                    "debates_won": a.debates_won,
                    "debates_lost": a.debates_lost,
                    "delegations_received": a.delegations_received,
                    "reputation_log": a.reputation_log[-10:],  # last 10 events
                }
                for a in s.agents.values()
            ] + [
                {
                    "id": "__historian__", "name": "Historian", "role": "Historian",
                    "role_id": None, "status": "active", "interaction_count": s.total_interactions,
                    "memory_summary": s.society_summary[:200] if s.society_summary else "",
                    "supervisor_id": None, "expertise": ["memory", "history", "themes"],
                    "reputation": 1.0, "vetoed_count": 0, "approved_count": 0,
                    "debates_won": 0, "debates_lost": 0, "delegations_received": 0,
                    "node_type": "system",
                }
            ],
            "roles": [
                {"id": r.id, "name": r.name, "supervises": r.supervises}
                for r in s.roles.values()
            ],
            "tools": [
                {"id": t.id, "name": t.name, "description": t.description, "usage_count": t.usage_count}
                for t in s.tools.values()
            ],
            "policies": [
                {"id": p.id, "name": p.name, "rule": p.rule, "active": p.active}
                for p in s.policies.values()
            ],
            "last_retrospective": s.last_retrospective or None,
            "relationships": [
                {"agents": k.split(":"), "affinity": v}
                for k, v in s.relationships.items()
                if abs(v) > 0.05  # only send meaningful relationships
            ],
        }

    def broadcast_state(self):
        self._emit(EventType.SOCIETY_STATE, self._snapshot())

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def boot(self) -> Society:
        from ..society.store import init_db
        await init_db(self._cfg)

        society = await self._store.load_society()
        if society is None:
            society = await self._bootstrap_society()

        for a in await self._store.load_agents():
            society.agents[a.id] = a
        for r in await self._store.load_roles():
            society.roles[r.id] = r
        for t in await self._store.load_tools():
            society.tools[t.id] = t
        self._tool_registry.load_from_specs(list(society.tools.values()))
        for p in await self._store.load_policies():
            society.policies[p.id] = p

        self._society = society
        self._evolution.assign_supervisors(society)
        self.broadcast_state()
        return society

    async def _bootstrap_society(self) -> Society:
        """Create the embryonic society — 3 agents, 3 roles, zero tools, zero policies."""
        society = Society()
        for role in SEED_ROLES:
            society.roles[role.id] = role
            await self._store.upsert_role(role)
        for role in SEED_ROLES[: self._cfg.initial_agent_count]:
            agent = Agent(
                name=f"{role.name}_1", role_id=role.id,
                expertise_domains=role.responsibilities[:2],
                personality_traits=self._evolution._traits_for_role(role),
            )
            society.agents[agent.id] = agent
            await self._store.upsert_agent(agent)
        await self._store.save_society(society)
        return society

    # -----------------------------------------------------------------------
    # Main entry point
    # -----------------------------------------------------------------------

    async def process(self, user_prompt: str) -> Interaction:
        if self._processing:
            raise RuntimeError("Society is already processing a prompt")
        self._processing = True
        self._emit(EventType.PROCESSING_START, {"prompt": user_prompt})
        self.broadcast_state()
        try:
            return await self._process_inner(user_prompt)
        finally:
            self._processing = False
            self._emit(EventType.PROCESSING_END, {})
            self.broadcast_state()

    async def _process_inner(self, user_prompt: str) -> Interaction:
        if self._society is None:
            await self.boot()
        society = self._society

        # 1. Retrieve relevant facts (semantic search, not global summary)
        from ..society.historian import Historian
        relevant_facts = Historian.retrieve_relevant_context(user_prompt, self._store, n=8)
        relevant_memory = relevant_facts

        # 2. Mobilize — distributed bid phase, agents self-select
        mob_result = await self._mobilization.mobilize(user_prompt, society, self._executor)
        selected_agents = self._build_agents(society, mob_result.activated_ids)
        selected_ids = mob_result.activated_ids
        mob_level = mob_result.level

        # 3. Run agents — emit thinking/responded per agent
        token_map = await self._run_agents_with_events(selected_agents, user_prompt, society, relevant_memory)

        # 3b. Tool execution
        tool_results_ctx = await self._execute_tools(society)
        tools_used: list[str] = []
        if tool_results_ctx:
            from ..tools.executor import parse_tool_calls
            for resp in self._last_responses.values():
                for name, _ in parse_tool_calls(resp):
                    if name not in tools_used:
                        tools_used.append(name)
            augmented_memory = relevant_memory + [tool_results_ctx]
            token_map_2 = await self._run_agents_with_events(selected_agents, user_prompt, society, augmented_memory)
            for aid, t in token_map_2.items():
                token_map[aid] = token_map.get(aid, 0) + t

        # 4. DELIBERATION — scaled by mobilization level
        #    solo/pair: skip deliberation entirely
        #    team: deliberation without debate
        #    council: full pipeline
        if mob_level in ("team", "council"):
            delib_result = await self._deliberation.deliberate(
                initial_responses=self._last_responses,
                user_prompt=user_prompt,
                society=society,
                agents=selected_agents,
                executor=self._executor,
                skip_debate=(mob_level == "team"),
            )
            self._last_responses = delib_result.responses
            delib_tokens = delib_result.total_tokens
        else:
            # solo/pair — no deliberation
            from ..swarm.deliberation import DeliberationResult
            delib_result = DeliberationResult(
                responses=self._last_responses,
                delegations=[], debates=[], consensus={},
                consensus_position=next(iter(self._last_responses.values()), ""),
            )
            delib_tokens = 0

        # 5. Supervision — only for council level
        if mob_level == "council":
            supervised = await self._supervision_with_events(
                self._last_responses, token_map, society
            )
        else:
            supervised = [
                SupervisedResponse(
                    agent_id=aid,
                    agent_name=society.agents[aid].name if aid in society.agents else aid,
                    raw_response=resp, final_response=resp,
                    tokens=token_map.get(aid, 0),
                )
                for aid, resp in self._last_responses.items()
            ]
        self._last_supervised = supervised
        approved = [s for s in supervised if s.supervisor_verdict != "vetoed"]
        approved_responses = {s.agent_id: s.final_response for s in approved}

        # 6. Synthesis — uses consensus position as primary input
        self._emit(EventType.SYNTHESIS_START, {"agent_ids": selected_ids})
        final_response = await self._synthesize_with_consensus(
            approved_responses, user_prompt, society, delib_result
        )
        self._emit(EventType.SYNTHESIS_END, {"response_length": len(final_response)})

        # 7. Build interaction (before Historian, so it can analyze it)
        total_tokens = sum(s.tokens for s in supervised) + delib_tokens + mob_result.total_bid_tokens
        interaction = Interaction(
            user_prompt=user_prompt,
            assigned_agents=selected_ids,
            responses={s.agent_id: s.final_response for s in supervised},
            final_response=final_response, themes=[], tools_used=tools_used,
            society_stage_at_time=society.stage, token_count=total_tokens,
        )

        # 8. HISTORIAN — extract facts, vectorize, update themes
        mem_update = await self._historian.process_interaction(
            interaction, society, selected_ids, self._executor,
        )
        # Vectorize discrete facts into ChromaDB
        self._historian.vectorize_facts(mem_update.facts, interaction, self._store)
        # Update themes (accumulated by Historian)
        if mem_update.themes:
            # Merge with existing, keep unique, cap at 15
            existing = set(society.dominant_themes)
            for t in mem_update.themes:
                existing.add(t)
            society.dominant_themes = list(existing)[:15]
        interaction.themes = mem_update.themes
        total_tokens += mem_update.tokens_used
        interaction.token_count = total_tokens

        # Update society summary for display (not injected into prompts)
        society.society_summary = await self._historian.build_summary(
            self._store, society, self._executor
        )

        # Update individual agent memories from Historian notes
        for aid, note in mem_update.agent_notes.items():
            if aid in society.agents:
                a = society.agents[aid]
                if a.memory_summary:
                    a.memory_summary = f"{a.memory_summary}\n{note}"
                else:
                    a.memory_summary = note

        # 9. Agent memory compression (Historian handles this too)
        all_active = society.active_agents
        compress_tasks = [
            self._historian.maybe_compress_agent(a, society, self._executor)
            for a in all_active if len(a.memory_summary) >= 1200
        ]
        if compress_tasks:
            await asyncio.gather(*compress_tasks)

        # 10. Record relationships — co-participation
        record_co_participation(society, selected_ids)

        # 11. Persist
        await self._store.save_interaction(interaction)
        society.total_interactions += 1
        for ka in selected_agents:
            ka.agent.interaction_count += 1
            await self._store.upsert_agent(ka.agent)
        for a in all_active:
            if a.id not in set(selected_ids):
                await self._store.upsert_agent(a)

        # 12. Reputation lifecycle — retire/demote/promote based on scores
        lifecycle_log: list[str] = []
        for agent in list(society.active_agents):
            update_reputation(agent)
            action = check_lifecycle(agent, society)
            if action == "retire":
                agent.status = AgentStatus.RETIRED
                lifecycle_log.append(f"Retired {agent.name} (rep: {agent.reputation:.2f})")
            elif action and action.startswith("demote:"):
                target = action.split(":", 1)[1]
                agent.previous_role_id = agent.role_id
                agent.role_id = target
                rn = society.roles[target].name if target in society.roles else target
                lifecycle_log.append(f"Demoted {agent.name} to {rn} (rep: {agent.reputation:.2f})")
            elif action and action.startswith("promote:"):
                target = action.split(":", 1)[1]
                agent.previous_role_id = agent.role_id
                agent.role_id = target
                rn = society.roles[target].name if target in society.roles else target
                lifecycle_log.append(f"Promoted {agent.name} to {rn} (rep: {agent.reputation:.2f})")
        if lifecycle_log:
            self._evolution.assign_supervisors(society)
            for agent in society.agents.values():
                await self._store.upsert_agent(agent)
            self._emit(EventType.SOCIETY_EVOLVED, {"changelog": lifecycle_log})

        # 13. Organic evolution — spawn based on metrics
        recent_for_evolution = await self._store.recent_interactions(n=20)
        organic_changelog = self._evolution.organic_check(society, recent_for_evolution)
        if organic_changelog:
            for agent in society.agents.values():
                await self._store.upsert_agent(agent)
            self._emit(EventType.SOCIETY_EVOLVED, {"changelog": organic_changelog})

        # 14. Tool Smith auto-propose — every 5 interactions, if Tool Smith role exists
        has_tool_smith = any(a.role_id == "role_tool_smith" for a in society.active_agents)
        if has_tool_smith and society.total_interactions > 0 and society.total_interactions % 5 == 0:
            try:
                proposals = await self.propose_tools()
                for spec in proposals:
                    society.tools[spec.id] = spec
                    await self._store.upsert_tool(spec)
                    self._emit(EventType.TOOL_CALLED, {"tool_name": spec.name, "success": True})
            except Exception:
                pass  # tool proposal is best-effort

        # 15. Stage evolution (gate-based)
        if self._evolution.should_evolve(society):
            society, changelog = self._evolution.evolve(society)
            for role in society.roles.values():
                await self._store.upsert_role(role)
            for agent in society.agents.values():
                await self._store.upsert_agent(agent)
            for policy in society.policies.values():
                await self._store.upsert_policy(policy)
            self._emit(EventType.SOCIETY_EVOLVED, {"changelog": changelog})

        # 16. Retrospective — society self-reflects every N interactions
        retro_report = await self._retrospective.maybe_run(
            society, self._store, self._executor,
        )
        if retro_report:
            society.last_retrospective = {
                "timestamp": retro_report.timestamp,
                "range": retro_report.interaction_range,
                "quality": retro_report.quality_assessment,
                "strengths": retro_report.recurring_strengths,
                "weaknesses": retro_report.recurring_weaknesses,
                "actions_taken": retro_report.actions_taken,
            }
            # Persist any new policies created by retrospective
            for policy in society.policies.values():
                await self._store.upsert_policy(policy)

        await self._store.save_society(society)
        return interaction

    # -----------------------------------------------------------------------
    # Agent execution with events
    # -----------------------------------------------------------------------

    async def _run_agents_with_events(self, agents, prompt, society, memory):
        loop = asyncio.get_event_loop()

        async def _run_one(ka: KithAgent):
            self._emit(EventType.AGENT_THINKING, {"agent_id": ka.agent.id, "agent_name": ka.agent.name, "role": ka.role.name if ka.role else None})
            content, tokens = await loop.run_in_executor(self._executor, ka.run, prompt, society, memory)
            self._emit(EventType.AGENT_RESPONDED, {
                "agent_id": ka.agent.id, "agent_name": ka.agent.name,
                "response_preview": content[:150], "tokens": tokens,
            })
            return ka.agent.id, content, tokens

        results = await asyncio.gather(*[_run_one(ka) for ka in agents])
        self._last_responses = {}
        token_map = {}
        for agent_id, content, tokens in results:
            self._last_responses[agent_id] = content
            token_map[agent_id] = tokens
        return token_map

    # -----------------------------------------------------------------------
    # Supervision with events
    # -----------------------------------------------------------------------

    async def _supervision_with_events(self, responses, token_map, society):
        if not self._supervision.is_active(society):
            return await self._supervision.review(responses, token_map, society, self._executor)

        # Emit supervising events
        from ..swarm.supervision import _build_supervision_map
        sup_map = _build_supervision_map(society)
        for aid in responses:
            sup_id = sup_map.get(aid)
            if sup_id and sup_id in society.agents:
                self._emit(EventType.AGENT_SUPERVISING, {
                    "supervisor_id": sup_id, "supervisor_name": society.agents[sup_id].name,
                    "subordinate_id": aid, "subordinate_name": society.agents[aid].name if aid in society.agents else aid,
                })

        supervised = await self._supervision.review(responses, token_map, society, self._executor)

        # Record supervision verdicts into reputation + relationships
        for s in supervised:
            if s.supervisor_id and s.agent_id in society.agents:
                record_verdict(society.agents[s.agent_id], s.supervisor_verdict)
                # Relationship signal
                if s.supervisor_verdict == "vetoed":
                    record_supervision_veto(society, s.supervisor_id, s.agent_id)
                elif s.supervisor_verdict == "approved":
                    record_supervision_approval(society, s.supervisor_id, s.agent_id)
            if s.supervisor_id:
                self._emit(EventType.AGENT_VERDICT, {
                    "supervisor_id": s.supervisor_id, "subordinate_id": s.agent_id,
                    "verdict": s.supervisor_verdict,
                })
        return supervised

    # -----------------------------------------------------------------------
    # Tool execution
    # -----------------------------------------------------------------------

    async def _execute_tools(self, society: Society) -> str:
        name_to_id = {t.name: t.id for t in society.tools.values()}
        all_text = "\n".join(self._last_responses.values())
        if "TOOL_CALL" not in all_text.upper():
            return ""
        results = await execute_tool_calls(all_text, self._tool_registry, name_to_id, store=self._store)
        if not results:
            return ""
        for r in results:
            self._emit(EventType.TOOL_CALLED, {"tool_name": r.tool_name, "success": r.success})
            if r.success and r.tool_id and r.tool_id in society.tools:
                society.tools[r.tool_id].usage_count += 1
        return format_tool_results(results)

    # -----------------------------------------------------------------------
    # Tool proposal / register
    # -----------------------------------------------------------------------

    async def propose_tools(self) -> list[ToolSpec]:
        society = self._society
        if society is None:
            return []
        interactions = await self._store.recent_interactions(n=30)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._tool_proposer.propose_sync, interactions, society)

    async def register_tool(self, spec: ToolSpec) -> None:
        society = self._society
        if society is None:
            return
        society.tools[spec.id] = spec
        await self._store.upsert_tool(spec)
        self._tool_registry.load_from_specs([spec])
        await self._store.save_society(society)
        self.broadcast_state()

    # -----------------------------------------------------------------------
    # Agent selection
    # -----------------------------------------------------------------------

    def _build_agents(self, society, agent_ids):
        """Build KithAgent instances for the given agent IDs."""
        policy = self._evolution.policy_for_society(society)
        return [
            KithAgent(agent=society.agents[aid], role=society.roles.get(society.agents[aid].role_id) if society.agents[aid].role_id else None, cfg=self._cfg, policy=policy)
            for aid in agent_ids if aid in society.agents
        ]

    def _select_agents(self, society, prompt):
        active = society.active_agents
        if not active:
            return []
        if society.stage == EvolutionStage.PRIMITIVE:
            agents_to_use = active
        else:
            hits = self._store.semantic_search(prompt, n=3, filter_type="agent")
            matched_ids = {h["metadata"]["id"] for h in hits}
            agents_to_use = [a for a in active if a.id in matched_ids] or active[:3]
        policy = self._evolution.policy_for_society(society)
        return [
            KithAgent(agent=a, role=society.roles.get(a.role_id) if a.role_id else None, cfg=self._cfg, policy=policy)
            for a in agents_to_use
        ]

    # -----------------------------------------------------------------------
    # Raw LLM call (no caveman — for user-facing output)
    # -----------------------------------------------------------------------

    def _raw_call_sync(self, prompt: str) -> tuple[str, int]:
        """Direct LLM call without caveman. Used for final synthesis to user."""
        # Create backend with NO token limit for user-facing output
        saved = self._cfg.llm_max_tokens
        self._cfg.llm_max_tokens = 4096
        backend = make_backend(self._cfg)
        self._cfg.llm_max_tokens = saved

        messages = [
            {"role": "system", "content": (
                "You are the final voice of a society of AI agents called Kith. "
                "Write clear, well-structured, complete responses for the end user. "
                "Use proper grammar, full sentences, and natural language. "
                "Do not use caveman style, abbreviations, or fragments. "
                "Be thorough — do not truncate or cut short."
            )},
            {"role": "user", "content": prompt},
        ]
        result = backend.generate(messages)
        return result.get("content", "").strip(), result.get("output_tokens", 0)

    # -----------------------------------------------------------------------
    # Synthesis
    # -----------------------------------------------------------------------

    async def _synthesize(self, responses, prompt, society):
        if not responses:
            return "No approved responses from society."
        if len(responses) == 1:
            # Still rewrite the single response in normal prose
            raw = next(iter(responses.values()))
            rewrite_prompt = (
                f"Original question: {prompt}\n\n"
                f"Internal agent response (compressed): {raw}\n\n"
                f"Rewrite this as a clear, complete answer for the end user."
            )
            loop = asyncio.get_event_loop()
            content, _ = await loop.run_in_executor(self._executor, self._raw_call_sync, rewrite_prompt)
            return content

        positions = "\n\n".join(
            f"[{society.agents[aid].name if aid in society.agents else aid}]: {resp}"
            for aid, resp in responses.items()
        )
        synthesis_prompt = (
            f"Original question: {prompt}\n\n"
            f"Internal agent positions (compressed notation):\n{positions}\n\n"
            f"Synthesize the above into a single, clear, well-written answer for the end user."
        )
        loop = asyncio.get_event_loop()
        content, _ = await loop.run_in_executor(self._executor, self._raw_call_sync, synthesis_prompt)
        return content

    async def _synthesize_with_consensus(self, responses, prompt, society, delib_result):
        if not responses:
            return "No approved responses from society."
        if len(responses) == 1 and not delib_result.debates:
            raw = next(iter(responses.values()))
            rewrite_prompt = (
                f"Original question: {prompt}\n\n"
                f"Internal agent response (compressed): {raw}\n\n"
                f"Rewrite this as a clear, complete answer for the end user."
            )
            loop = asyncio.get_event_loop()
            content, _ = await loop.run_in_executor(self._executor, self._raw_call_sync, rewrite_prompt)
            return content

        debate_ctx = ""
        if delib_result.debates:
            debate_ctx = "\nDebates resolved:\n" + "\n".join(
                f"  {d['agent_a']} vs {d['agent_b']}: {d['resolution']}" for d in delib_result.debates
            )
        delegation_ctx = ""
        if delib_result.delegations:
            delegation_ctx = "\nDelegation results:\n" + "\n".join(
                f"  {d['from_name']} delegated to {d['to_name']}: {d.get('result', '')}" for d in delib_result.delegations
            )
        votes = delib_result.consensus
        agree = sum(1 for v in votes.values() if v == "agree")
        disagree = sum(1 for v in votes.values() if v == "disagree")
        vote_ctx = f"\nConsensus: {agree} agree, {disagree} disagree, {len(votes) - agree - disagree} abstain."

        positions = "\n\n".join(
            f"[{society.agents[aid].name if aid in society.agents else aid}] (voted {votes.get(aid, '?')}): {resp}"
            for aid, resp in responses.items()
        )

        synthesis_prompt = (
            f"Original question: {prompt}\n\n"
            f"Internal agent positions after deliberation (compressed notation):\n{positions}\n"
            f"{debate_ctx}{delegation_ctx}{vote_ctx}\n\n"
            f"Consensus position: {delib_result.consensus_position}\n\n"
            f"Synthesize all of the above into a single, clear, well-written answer for the end user. "
            f"Weight the consensus position heavily."
        )
        loop = asyncio.get_event_loop()
        content, _ = await loop.run_in_executor(self._executor, self._raw_call_sync, synthesis_prompt)
        return content

    # -----------------------------------------------------------------------
    # Society management
    # -----------------------------------------------------------------------

    async def set_agent_status(self, agent_id, status):
        society = self._society
        if society is None or agent_id not in society.agents:
            raise ValueError(f"Agent not found: {agent_id}")
        society.agents[agent_id].status = status
        await self._store.upsert_agent(society.agents[agent_id])
        await self._store.save_society(society)
        self.broadcast_state()
        return society.agents[agent_id]

    async def reassign_role(self, agent_id, role_id):
        society = self._society
        if society is None or agent_id not in society.agents:
            raise ValueError(f"Agent not found: {agent_id}")
        if role_id not in society.roles:
            raise ValueError(f"Role not found: {role_id}")
        agent = society.agents[agent_id]
        agent.role_id = role_id
        agent.supervisor_id = None
        self._evolution.assign_supervisors(society)
        await self._store.upsert_agent(agent)
        await self._store.save_society(society)
        self.broadcast_state()
        return agent

    async def rename_agent(self, agent_id: str, name: str) -> Agent:
        society = self._society
        if society is None or agent_id not in society.agents:
            raise ValueError(f"Agent not found: {agent_id}")
        society.agents[agent_id].name = name.strip()
        await self._store.upsert_agent(society.agents[agent_id])
        await self._store.save_society(society)
        self.broadcast_state()
        return society.agents[agent_id]

    async def update_policy(self, policy_id, rule=None, active=None):
        society = self._society
        if society is None or policy_id not in society.policies:
            raise ValueError(f"Policy not found: {policy_id}")
        p = society.policies[policy_id]
        if rule is not None: p.rule = rule
        if active is not None: p.active = active
        await self._store.upsert_policy(p)
        await self._store.save_society(society)
        self.broadcast_state()
        return p

    async def add_policy(self, name, rule, applies_to_roles=None):
        society = self._society
        if society is None:
            raise ValueError("Society not initialized")
        p = SocietyPolicy(name=name, rule=rule, applies_to_roles=applies_to_roles or [])
        society.policies[p.id] = p
        await self._store.upsert_policy(p)
        await self._store.save_society(society)
        self.broadcast_state()
        return p

    async def reset_society(self) -> Society:
        """Wipe all state and bootstrap a fresh primitive society."""
        if self._processing:
            raise RuntimeError("Cannot reset while processing")
        from ..society.store import reset_singletons, init_db
        await reset_singletons()
        # Delete DB file
        if self._cfg.db_path.exists():
            self._cfg.db_path.unlink()
        # Re-init
        self._store = KithStore(self._cfg)
        self._tool_registry = build_default_registry()
        self._last_supervised = []
        self._society = None
        await init_db(self._cfg)
        society = await self._bootstrap_society()
        self._society = society
        self._evolution.assign_supervisors(society)
        self.broadcast_state()
        return society

    # -----------------------------------------------------------------------
    # Shutdown / accessors
    # -----------------------------------------------------------------------

    async def shutdown(self):
        if self._processing:
            import time
            deadline = time.monotonic() + 30
            while self._processing and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
        if self._society is not None:
            await self._store.save_society(self._society)
        self._executor.shutdown(wait=False)

    @property
    def is_processing(self): return self._processing
    @property
    def society(self): return self._society
    @property
    def store(self): return self._store
