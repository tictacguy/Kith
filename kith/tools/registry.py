from __future__ import annotations

import importlib
from typing import Any, Callable, Awaitable

from ..society.state import ToolSpec


class ToolRegistry:
    """
    Runtime registry for society tools.
    Starts empty. Tools are proposed by Tool Smith and registered at runtime.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., Awaitable[Any]]] = {}

    def register(self, tool: ToolSpec, handler: Callable[..., Awaitable[Any]]) -> None:
        self._handlers[tool.id] = handler

    def register_by_ref(self, tool: ToolSpec) -> None:
        module_path, fn_name = tool.handler_ref.rsplit(".", 1)
        module = importlib.import_module(module_path)
        self._handlers[tool.id] = getattr(module, fn_name)

    async def call(self, tool_id: str, **kwargs: Any) -> Any:
        handler = self._handlers.get(tool_id)
        if handler is None:
            raise KeyError(f"Tool '{tool_id}' not registered")
        return await handler(**kwargs)

    def available(self) -> list[str]:
        return list(self._handlers.keys())

    def load_from_specs(self, specs: list[ToolSpec]) -> None:
        for spec in specs:
            if spec.handler_ref and spec.id not in self._handlers:
                try:
                    self.register_by_ref(spec)
                except (ImportError, AttributeError):
                    pass


def build_default_registry() -> ToolRegistry:
    """Empty registry. Tools emerge from Tool Smith proposals."""
    return ToolRegistry()
