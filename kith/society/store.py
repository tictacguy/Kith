from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import os

import chromadb
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import Config
from .state import Agent, Interaction, Role, Society, SocietyPolicy, ToolSpec

# ---------------------------------------------------------------------------
# SQLAlchemy async engine
# ---------------------------------------------------------------------------

_engine: Any = None
_session_factory: Any = None


def _get_engine(cfg: Config):
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(f"sqlite+aiosqlite:///{cfg.db_path}", echo=False)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine, _session_factory


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS society (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS tools (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS interactions (
    id TEXT PRIMARY KEY,
    data JSON NOT NULL,
    created_at TEXT NOT NULL
);
"""


async def init_db(cfg: Config) -> None:
    engine, _ = _get_engine(cfg)
    async with engine.begin() as conn:
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))


# ---------------------------------------------------------------------------
# ChromaDB vector store
# ---------------------------------------------------------------------------

_chroma_client: chromadb.ClientAPI | None = None
_chroma_collection: Any = None


def _get_chroma(cfg: Config):
    global _chroma_client, _chroma_collection
    if _chroma_client is None:
        # ChromaDB hardcodes ONNX cache to ~/.cache/chroma/onnx_models/
        # Symlink it to persistent data dir so the model isn't re-downloaded
        home_cache = Path.home() / ".cache" / "chroma" / "onnx_models"
        persistent_cache = cfg.chroma_path.parent / "onnx_cache" / "onnx_models"
        persistent_cache.mkdir(parents=True, exist_ok=True)
        home_cache.parent.mkdir(parents=True, exist_ok=True)
        if not home_cache.exists():
            try:
                home_cache.symlink_to(persistent_cache)
            except OSError:
                pass  # symlink failed (e.g. Windows) — fall back to default
        elif home_cache.is_symlink():
            pass  # already linked
        # If home_cache is a real dir with the model, that's fine too

        _chroma_client = chromadb.PersistentClient(path=str(cfg.chroma_path))
        _chroma_collection = _chroma_client.get_or_create_collection(
            name=cfg.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )
    return _chroma_collection


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

async def reset_singletons() -> None:
    """Dispose engine and clear chroma state. For testing only."""
    global _engine, _session_factory, _chroma_client, _chroma_collection
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
    if _chroma_client is not None:
        for col in _chroma_client.list_collections():
            _chroma_client.delete_collection(col.name if hasattr(col, 'name') else str(col))
    _chroma_client = None
    _chroma_collection = None


class KithStore:
    """Unified persistence: SQLite for structured data, ChromaDB for semantic search."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        _, self._sf = _get_engine(cfg)
        self._vec = _get_chroma(cfg)

    # ---- helpers -----------------------------------------------------------

    def _session(self) -> AsyncSession:
        return self._sf()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ---- Society -----------------------------------------------------------

    async def save_society(self, society: Society) -> None:
        society.updated_at = datetime.now(timezone.utc)
        async with self._session() as s, s.begin():
            await s.execute(
                text("INSERT OR REPLACE INTO society(id, data, updated_at) VALUES(:id,:data,:ts)"),
                {"id": society.id, "data": society.model_dump_json(), "ts": self._now()},
            )

    async def load_society(self) -> Society | None:
        async with self._session() as s:
            row = (await s.execute(text("SELECT data FROM society WHERE id='kith_society'"))).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        # Rebuild nested models
        soc = Society.model_validate(data)
        return soc

    # ---- Agents ------------------------------------------------------------

    async def upsert_agent(self, agent: Agent) -> None:
        agent.last_active = datetime.now(timezone.utc)
        async with self._session() as s, s.begin():
            await s.execute(
                text("INSERT OR REPLACE INTO agents(id, data, updated_at) VALUES(:id,:data,:ts)"),
                {"id": agent.id, "data": agent.model_dump_json(), "ts": self._now()},
            )
        # Vectorize agent identity for semantic lookup
        self._vec.upsert(
            ids=[f"agent:{agent.id}"],
            documents=[f"{agent.name} {' '.join(agent.expertise_domains)} {agent.memory_summary}"],
            metadatas=[{"type": "agent", "id": agent.id, "name": agent.name}],
        )

    async def load_agents(self) -> list[Agent]:
        async with self._session() as s:
            rows = (await s.execute(text("SELECT data FROM agents"))).fetchall()
        return [Agent.model_validate(json.loads(r[0])) for r in rows]

    # ---- Interactions ------------------------------------------------------

    async def save_interaction(self, interaction: Interaction) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                text("INSERT OR REPLACE INTO interactions(id, data, created_at) VALUES(:id,:data,:ts)"),
                {"id": interaction.id, "data": interaction.model_dump_json(), "ts": self._now()},
            )
        # Vectorize prompt + themes for thematic memory
        doc = f"{interaction.user_prompt} {' '.join(interaction.themes)}"
        self._vec.upsert(
            ids=[f"interaction:{interaction.id}"],
            documents=[doc],
            metadatas=[{
                "type": "interaction",
                "id": interaction.id,
                "themes": ",".join(interaction.themes),
                "stage": interaction.society_stage_at_time.value,
            }],
        )

    async def recent_interactions(self, n: int = 20) -> list[Interaction]:
        async with self._session() as s:
            rows = (await s.execute(
                text("SELECT data FROM interactions ORDER BY created_at DESC LIMIT :n"),
                {"n": n},
            )).fetchall()
        return [Interaction.model_validate(json.loads(r[0])) for r in rows]

    # ---- Semantic search ---------------------------------------------------

    def semantic_search(
        self,
        query: str,
        n: int = 5,
        filter_type: str | None = None,
    ) -> list[dict[str, Any]]:
        where = {"type": filter_type} if filter_type else None
        results = self._vec.query(
            query_texts=[query],
            n_results=n,
            where=where,
        )
        out = []
        for i, doc in enumerate(results["documents"][0]):
            out.append({
                "id": results["ids"][0][i],
                "document": doc,
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return out

    # ---- Roles / Tools / Policies (lightweight, full JSON) -----------------

    async def upsert_role(self, role: Role) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                text("INSERT OR REPLACE INTO roles(id, data) VALUES(:id,:data)"),
                {"id": role.id, "data": role.model_dump_json()},
            )

    async def load_roles(self) -> list[Role]:
        async with self._session() as s:
            rows = (await s.execute(text("SELECT data FROM roles"))).fetchall()
        return [Role.model_validate(json.loads(r[0])) for r in rows]

    async def upsert_tool(self, tool: ToolSpec) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                text("INSERT OR REPLACE INTO tools(id, data) VALUES(:id,:data)"),
                {"id": tool.id, "data": tool.model_dump_json()},
            )

    async def load_tools(self) -> list[ToolSpec]:
        async with self._session() as s:
            rows = (await s.execute(text("SELECT data FROM tools"))).fetchall()
        return [ToolSpec.model_validate(json.loads(r[0])) for r in rows]

    async def upsert_policy(self, policy: SocietyPolicy) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                text("INSERT OR REPLACE INTO policies(id, data, active) VALUES(:id,:data,:active)"),
                {"id": policy.id, "data": policy.model_dump_json(), "active": int(policy.active)},
            )

    async def load_policies(self) -> list[SocietyPolicy]:
        async with self._session() as s:
            rows = (await s.execute(text("SELECT data FROM policies WHERE active=1"))).fetchall()
        return [SocietyPolicy.model_validate(json.loads(r[0])) for r in rows]
