from __future__ import annotations

import json

from ..config import Config, make_backend
from ..agents.caveman import CavemanBackend
from ..society.state import Interaction, Society, ToolSpec


class ToolProposer:
    """
    Tool Smith role logic: given recent interactions, propose new ToolSpecs
    the society needs but doesn't have yet.

    Returns structured JSON parsed into ToolSpec objects.
    The caller decides whether to accept/register them.
    """

    def __init__(self, cfg: Config) -> None:
        backend = make_backend(cfg)
        self._backend = CavemanBackend(backend, intensity="full")

    def propose_sync(
        self,
        interactions: list[Interaction],
        society: Society,
    ) -> list[ToolSpec]:
        existing = [t.name for t in society.tools.values()]
        themes = society.dominant_themes

        # Summarize recurring task patterns from recent interactions
        pattern_text = "\n".join(
            f"- [{', '.join(i.themes)}]: {i.user_prompt[:120]}"
            for i in interactions[-20:]
        )

        prompt = (
            f"You are Tool Smith. Analyze these recurring task patterns:\n{pattern_text}\n\n"
            f"Existing tools: {existing}\n"
            f"Dominant themes: {themes}\n\n"
            f"Propose 1-3 NEW tools the society needs. "
            f"Return JSON array only, no prose:\n"
            f'[{{"name":"tool_name","description":"what it does","parameters":{{"param":"type"}},"handler_ref":"kith.tools.custom.tool_name"}}]'
        )

        result = self._backend.generate([{"role": "user", "content": prompt}])
        raw = result.get("content", "[]").strip()

        # Extract JSON array robustly
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return []

        try:
            items = json.loads(raw[start:end])
        except json.JSONDecodeError:
            return []

        specs: list[ToolSpec] = []
        for item in items:
            if not isinstance(item, dict) or "name" not in item:
                continue
            # Skip if tool with same name already exists
            if item["name"] in existing:
                continue
            specs.append(ToolSpec(
                name=item["name"],
                description=item.get("description", ""),
                parameters=item.get("parameters", {}),
                handler_ref=item.get("handler_ref", f"kith.tools.custom.{item['name']}"),
            ))

        return specs
