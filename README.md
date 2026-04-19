<p align="center">
  <img src="static/cover.png" alt="Kith" width="100%" />
</p>

<p align="center">
  <strong>Decision intelligence through a persistent, self-governing AI society.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#api">API</a> ·
  <a href="#configuration">Configuration</a>
</p>

---

Kith is a decision-making engine built on a persistent society of AI agents. Instead of routing your question to a single model, Kith mobilizes a society that deliberates, challenges, and converges — producing decisions that are more robust, more diverse, and more thoroughly examined than any single agent could achieve.

The society persists across sessions. It develops internal policies from observed problems, promotes high-performing agents and retires underperformers, builds bilateral trust relationships between members, transfers institutional knowledge when agents are retired, and periodically self-reflects on its own decision quality. Every decision is informed by vectorized institutional memory — not a static summary, but semantically retrieved facts relevant to the question at hand.

Internal communication uses [caveman](https://github.com/JuliusBrussee/caveman) compression (~70% token savings). Reasoning is governed by [Meta-Reasoning](https://github.com/tictacguy/meta-reasoning), an SDK that controls cognitive dynamics through formal policies and mutation operators. The final response to the user is always clear, well-structured prose.

## Why Kith?

Traditional AI assistants give you one perspective from one model. Kith gives you a **decision process**:

| Role | Stage | Purpose |
|------|-------|---------|
| **Elder** | Primitive | Synthesizes conflicting viewpoints into a coherent recommendation |
| **Scout** | Primitive | Explores unconventional angles your team might miss |
| **Builder** | Primitive | Translates abstract ideas into concrete implementation plans |
| **Critic** | Tribal | Finds flaws in reasoning, red-teams the emerging consensus |
| **Tool Smith** | Tribal | Analyzes patterns and proposes new tools for the society |
| **Governor** | Organized | Enforces quality standards and mediates unresolved disputes |
| **Analyst** | Organized | Provides data-driven insights and quantitative evaluation |
| **Historian** | System | Extracts facts, maintains vectorized memory (◑ in the graph) |

The society doesn't just answer — it **frames, challenges, and converges**. The final recommendation includes the reasoning, the process, and any dissenting views or risks identified.

## Frontend

<p align="center">
  <img src="static/screen.png" alt="Kith UI" width="100%" />
</p>

The interface is a real-time visualization of the society. A D3 force-directed graph shows agents as nodes and bilateral relationships as colored links (green for allies, red for rivals). When the society grows beyond 12 agents, nodes are automatically clustered by role — click a cluster to expand. Everything updates live via WebSocket.

- **Graph canvas** — drag, zoom, click any agent to inspect. Historian visible as a system entity (◑). Clusters collapse/expand on click.
- **Console tab** — live event feed: mobilization, deliberation, debate, convergence, evolution events (blue), retrospective actions
- **Entities tab** — agent list with reputation scores, thematic affinity tags, cooldown indicators, legacy badges
- **Memory tab** — vectorized facts, retrospective reports, society summary, active policies with source and effectiveness score
- **Tools tab** — tools proposed by the Tool Smith with parameters, usage count, and creation date
- **Settings** — switch LLM provider and model at runtime (opens as overlay from header)
- **Chat input** — bottom-center of the canvas
- **Response sheet** — slides up with the final synthesized recommendation, including process transparency and risk caveats

## Quick Start

### Docker Hub

```bash
docker run -d \
  --name kith \
  -p 8000:8000 \
  -v kith_data:/data/kith \
  -e KITH_LLM_BACKEND=openai \
  -e OPENAI_API_KEY=your_key \
  -e KITH_LLM_MODEL=gpt-4o \
  tictacguy/kith:latest
```

### GitHub Container Registry

```bash
docker run -d \
  --name kith \
  -p 8000:8000 \
  -v kith_data:/data/kith \
  -e KITH_LLM_BACKEND=openai \
  -e OPENAI_API_KEY=your_key \
  -e KITH_LLM_MODEL=gpt-4o \
  ghcr.io/tictacguy/kith:latest
```

Open `http://localhost:8000`.

### Docker Compose

```bash
git clone https://github.com/tictacguy/kith.git
cd kith
cp .env.example .env
# Edit .env with your provider credentials
docker compose up -d
```

### From Source

```bash
git clone https://github.com/tictacguy/kith.git
cd kith
pip install -e ".[dev]"
uvicorn kith.main:app --port 8000 --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

## How It Works

### Decision Pipeline

Every question goes through a structured decision process. The depth scales automatically with complexity.

```
Question arrives
       │
  FRAMING ── identify decision dimensions (cost, risk, timeline...)
       │      simple questions skip this step
       │
  MOBILIZATION ── each agent bids on relevance
       │           bid = 60% LLM self-assessment + 40% thematic affinity
       │           attention economy: consecutive activations penalized
       │           simple question → 1 agent (SOLO)
       │           complex question → full society (COUNCIL)
       │
  PARALLEL RESPONSES ── activated agents reason independently
       │                  each sees: charter, framing, relevant memory, policies, legacy
       │
  DELIBERATION ── agents read peers and update positions
       │           can CHALLENGE specific reasoning flaws (max 1 per agent)
       │
  DEBATE ── challenged pairs argue with evidence (max 3 debates)
       │    Governor mediates and rules
       │
  CONVERGENCE ── consensus inferred from updated positions
       │          no explicit voting — alignment measured naturally
       │
  RED TEAM ── Critic stress-tests the emerging position
       │       identifies blind spots, flaws, risks
       │
  SYNTHESIS ── structured recommendation for the user:
       │        1. Recommendation
       │        2. Key reasoning
       │        3. How the society reached this conclusion
       │        4. Risks and caveats (from red team + dissenters)
       │
  HISTORIAN ── extracts facts, vectorizes in ChromaDB
       │
  EVOLUTION ── reputation updates, policy lifecycle, organic spawning
       │
  RETROSPECTIVE ── society self-reflects every 10 decisions
```

### Mobilization Levels

| Level | Agents | Pipeline |
|-------|--------|----------|
| SOLO | 1 | Direct response, no deliberation |
| PAIR | 2 | Responses + synthesis |
| TEAM | 3-4 | Deliberation without debate |
| COUNCIL | 5+ | Full pipeline: deliberation + debate + red team |

### Society Charter

Every agent knows it belongs to a self-governing society. The charter is injected into every prompt:

> You belong to a self-governing AI society whose sole purpose is producing decisions superior to what any single agent could reach. The society evolves: high-performing members gain influence, underperformers are retired, new members spawn when needed. Disagreement is a feature — challenge weak reasoning with specific evidence. Respond ONLY when genuinely relevant; silence is better than noise.

### Thematic Clusters

Agents develop thematic profiles from participation history. When a new prompt arrives, agents with high thematic affinity get a mobilization boost — pure vector similarity, zero extra LLM calls. If you use Kith for tech, business, and legal decisions, agents naturally specialize and the right ones activate for each domain.

### Attention Economy

Agents activated 3+ times in a row get diminishing bid scores (15% penalty per consecutive activation beyond 2, cap -40%). This forces perspective rotation and prevents the same agents from dominating every decision.

### Legacy Transfer

When an agent is retired for low reputation, its knowledge is condensed into a testament and transferred to a successor: memory, failure patterns, thematic expertise. Institutional knowledge survives agent death.

### Policy Governance

Policies are capped per stage (PRIMITIVE: 1, TRIBAL: 3, ORGANIZED: 5, COMPLEX: 7). Each policy has an effectiveness score that decays if unused. Policies idle for 15+ interactions expire automatically. Sources: organic (from metrics), retrospective (from self-reflection), manual (from user).

### Bilateral Relationships

Every pair of agents has an affinity score [-1.0, 1.0]. Co-participation, consensus alignment, and supervision approval build trust. Debate losses and supervision vetoes create friction. Relationships influence mobilization — strong allies get pulled in together.

### Vectorized Memory

The Historian extracts discrete facts from every interaction and vectorizes them individually in ChromaDB. When a new question arrives, only semantically relevant facts are retrieved — no global summary polluting unrelated decisions. The society summary in the UI is reconstructed from recent facts for human readability, but is never injected into agent prompts.

### Organic Evolution

The society grows without hard caps. Spawn triggers:

- **Role overload** — if a role is mobilized > 2.5x the average in recent interactions, a new agent is spawned for that role
- **Theme coverage** — if 2+ dominant themes aren't covered by any agent's expertise, a new agent is spawned with those themes
- **Stage evolution** — advancing stages (Primitive → Tribal → Organized → Complex) unlocks new roles and spawns agents for them

Max 1 spawn per interaction to prevent explosions.

### Storage

- **SQLite** — structured state (agents, roles, tools, policies, interactions, relationships, thematic profiles)
- **ChromaDB** — vectorized memory (all-MiniLM-L6-v2 via built-in ONNX)

### LLM Providers

Switchable at runtime from the Settings panel.

| Provider | Variables |
|----------|-----------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| AWS Bedrock | `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION` |
| Ollama | `OLLAMA_BASE_URL` (default: `http://localhost:11434/v1`) |

## Configuration

All via environment variables or `.env` file.

| Variable | Description | Default |
|----------|-------------|---------|
| `KITH_LLM_BACKEND` | `openai` / `anthropic` / `bedrock` / `ollama` | `bedrock` |
| `KITH_LLM_MODEL` | Model name | `claude-3-5-haiku-20241022` |
| `KITH_LLM_MAX_TOKENS` | Max tokens for internal agent calls | `1024` |
| `KITH_DATA_DIR` | Persistent data directory | `/data/kith` |
| `CAVEMAN_INTENSITY` | Default compression: `lite` / `full` / `ultra` | `full` |

## API

All endpoints under `/api/v1/`. Real-time events via WebSocket at `/ws`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/prompt` | Submit a decision question |
| `GET` | `/society` | Society state |
| `GET` | `/agents` | List agents |
| `PATCH` | `/agents/{id}/name` | Rename |
| `PATCH` | `/agents/{id}/status` | Set active/dormant/retired |
| `PATCH` | `/agents/{id}/role` | Reassign role |
| `GET` | `/roles` | List roles |
| `GET` | `/tools` | List tools |
| `POST` | `/tools/propose` | Tool Smith proposals |
| `POST` | `/tools/register` | Register tool |
| `GET` | `/policies` | List policies |
| `POST` | `/policies` | Add policy |
| `PATCH` | `/policies/{id}` | Update policy |
| `POST` | `/society/evolve` | Force evolution check |
| `POST` | `/society/reset` | Reset to primitive |
| `GET` | `/config/llm` | Current LLM config |
| `PUT` | `/config/llm` | Switch provider at runtime |
| `GET` | `/memory/search?q=` | Semantic memory search |
| `GET` | `/interactions/recent` | Recent interactions |
| `WS` | `/ws` | Real-time event stream |

## License

AGPL-3.0
