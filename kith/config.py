from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

DATA_DIR = Path(os.getenv("KITH_DATA_DIR", "/tmp/kith_data"))
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_DIR = Path("/tmp/kith_data")
    DATA_DIR.mkdir(parents=True, exist_ok=True)


class Config(BaseModel):
    # Backend selector: "openai" | "anthropic" | "bedrock" | "ollama"
    llm_backend: str = Field(default_factory=lambda: os.getenv("KITH_LLM_BACKEND", "bedrock"))

    # Model name — shared across all providers
    llm_model: str = Field(default_factory=lambda: os.getenv(
        "KITH_LLM_MODEL",
        os.getenv("BEDROCK_CHAT_MODEL", "claude-3-5-haiku-20241022"),
    ))
    llm_max_tokens: int = int(os.getenv("KITH_LLM_MAX_TOKENS", "1024"))

    # OpenAI
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))

    # Anthropic
    anthropic_api_key: str = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # Bedrock
    aws_bearer_token: str = Field(default_factory=lambda: os.getenv("AWS_BEARER_TOKEN_BEDROCK", ""))
    aws_region: str = Field(default_factory=lambda: os.getenv("AWS_REGION", "eu-west-2"))

    # Ollama
    ollama_base_url: str = Field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"))

    # Caveman
    caveman_intensity: str = Field(default_factory=lambda: os.getenv("CAVEMAN_INTENSITY", "full"))

    # Meta-Reasoning
    max_reasoning_cycles: int = 4
    max_violations: int = 2

    # Society
    initial_agent_count: int = 3
    max_agents: int = 50
    evolution_threshold: int = 5

    # Storage
    db_path: Path = DATA_DIR / "kith.db"
    chroma_path: Path = DATA_DIR / "chroma"
    chroma_collection: str = "kith_society"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    model_config = {"arbitrary_types_allowed": True}


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()


def make_backend(cfg: Config):
    """Factory: returns the right LLMBackend based on cfg.llm_backend."""
    match cfg.llm_backend:
        case "openai":
            from .agents.openai_backend import OpenAIBackend
            return OpenAIBackend(cfg)
        case "anthropic":
            from .agents.backend import AnthropicBackend
            return AnthropicBackend(cfg)
        case "bedrock":
            from .agents.bedrock_backend import BedrockBackend
            return BedrockBackend(cfg)
        case "ollama":
            from .agents.openai_backend import OpenAIBackend
            return OpenAIBackend(cfg, base_url=cfg.ollama_base_url)
        case _:
            raise ValueError(
                f"Unknown LLM backend: '{cfg.llm_backend}'. "
                f"Use: openai, anthropic, bedrock, ollama"
            )
