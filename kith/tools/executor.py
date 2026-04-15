from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ..tools.registry import ToolRegistry


# Pattern: TOOL_CALL: tool_name({"param": "value"})
# or:      TOOL_CALL: tool_name(param=value)
_TOOL_CALL_RE = re.compile(
    r"TOOL_CALL:\s*(\w+)\(([^)]*)\)",
    re.IGNORECASE,
)


@dataclass
class ToolCallResult:
    tool_name: str
    tool_id: str | None
    args: dict[str, Any]
    result: Any
    success: bool
    error: str = ""


def parse_tool_calls(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Extract tool calls from agent output text."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for match in _TOOL_CALL_RE.finditer(text):
        name = match.group(1)
        raw_args = match.group(2).strip()
        args = _parse_args(raw_args)
        calls.append((name, args))
    return calls


def _parse_args(raw: str) -> dict[str, Any]:
    """Parse tool arguments — tries JSON first, then key=value pairs."""
    if not raw:
        return {}
    # Try JSON
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # Try key=value
    args: dict[str, Any] = {}
    for part in raw.split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            args[k.strip()] = v.strip().strip("\"'")
        elif part:
            # Single positional arg
            args["text" if len(args) == 0 else f"arg{len(args)}"] = part.strip("\"'")
    return args


async def execute_tool_calls(
    text: str,
    registry: ToolRegistry,
    tool_name_to_id: dict[str, str],
    **extra_kwargs: Any,
) -> list[ToolCallResult]:
    """
    Parse tool calls from agent text, execute them, return results.
    extra_kwargs are passed to every tool handler (e.g. store=...).
    """
    calls = parse_tool_calls(text)
    results: list[ToolCallResult] = []

    for name, args in calls:
        tool_id = tool_name_to_id.get(name)
        if tool_id is None:
            results.append(ToolCallResult(
                tool_name=name, tool_id=None, args=args,
                result=None, success=False, error=f"Unknown tool: {name}",
            ))
            continue

        merged_args = {**args, **extra_kwargs}
        try:
            result = await registry.call(tool_id, **merged_args)
            results.append(ToolCallResult(
                tool_name=name, tool_id=tool_id, args=args,
                result=result, success=True,
            ))
        except Exception as e:
            results.append(ToolCallResult(
                tool_name=name, tool_id=tool_id, args=args,
                result=None, success=False, error=str(e),
            ))

    return results


def format_tool_results(results: list[ToolCallResult]) -> str:
    """Format tool results as context to inject back into agent prompt."""
    if not results:
        return ""
    lines = ["Tool results:"]
    for r in results:
        if r.success:
            lines.append(f"  {r.tool_name}: {r.result}")
        else:
            lines.append(f"  {r.tool_name}: ERROR — {r.error}")
    return "\n".join(lines)
