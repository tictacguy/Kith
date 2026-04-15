<p align="center">
  <img src="static/cover.png" alt="Kith" width="100%" />
</p>

<p align="center">
  <strong>A persistent AI society that deliberates, debates, delegates, and evolves.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#configuration">Configuration</a>
</p>

---

Kith is not a chatbot wrapper. It's a living society of AI agents that persists across sessions, develops internal policies, promotes and retires members based on performance, and allocates resources proportionally to the complexity of each question.

Agents communicate internally using [caveman](https://github.com/JuliusBrussee/caveman) compression (~70% token savings), while delivering clear, well-structured responses to the end user. Reasoning is governed by [Meta-Reasoning](https://github.com/tictacguy/meta-reasoning), an SDK that controls cognitive dynamics through formal policies and mutation operators.

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

Open `http://localhost:8000`.

### Docker Compose

```bash
git clone https://github.com/tictacguy/kith.git
cd kith
cp .env.example .env
# Edit .env with your provider credentials
docker compose up -d
```

Open `http://localhost:8000`.

### From Source

```bash
git clone https://github.com/tictacguy/kith.git
cd kith

# Backend
pip install -e ".[dev]"
uvicorn kith.main:app --port 8000 --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Backend at `http://localhost:8000`, frontend at `http://localhost:3000`.

### Caveman Compression

Internal agent communication uses caveman compression. Each role uses a different intensity:

| Role | Intensity | Reason |
|------|-----------|--------|
| Scout | lite | Needs articulated reasoning |
| Elder, Governor, Analyst, Critic | full | Clarity for decisions |
| Builder, Tool Smith | ultra | Dense technical output |

The final response to the user is always clear, normal prose.

### LLM Providers

Switchable at runtime from the frontend. No restart needed.

| Provider | Config |
|----------|--------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| AWS Bedrock | `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION` |
| Ollama | `OLLAMA_BASE_URL` |

## Configuration

All via environment variables or `.env` file.

| Variable | Description | Default |
|----------|-------------|---------|
| `KITH_LLM_BACKEND` | `openai` / `anthropic` / `bedrock` / `ollama` | `bedrock` |
| `KITH_LLM_MODEL` | Model name | `claude-3-5-haiku-20241022` |
| `KITH_LLM_MAX_TOKENS` | Max tokens for internal calls | `1024` |
| `KITH_DATA_DIR` | Persistent data directory | `/data/kith` |
| `CAVEMAN_INTENSITY` | Default compression: `lite` / `full` / `ultra` | `full` |

## License

AGPL-3.0
