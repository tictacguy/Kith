from __future__ import annotations

from pathlib import Path
from typing import Any

# Caveman SKILL.md bundled inside kith/assets/ — no external repo needed
_SKILL_PATH = Path(__file__).parents[1] / "assets" / "caveman_skill.md"

# Strip YAML frontmatter (between --- delimiters) — keep only the rules body
def _load_skill(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---")
    # parts[0] = empty, parts[1] = frontmatter, parts[2+] = body
    body = "---".join(parts[2:]).strip() if len(parts) >= 3 else text.strip()
    return body


_CAVEMAN_RULES: str = _load_skill(_SKILL_PATH) if _SKILL_PATH.exists() else (
    "Respond terse like smart caveman. Drop articles, filler, pleasantries, hedging. "
    "Fragments OK. Technical terms exact. Code blocks unchanged."
)

_INTENSITY_OVERRIDE: dict[str, str] = {
    "lite": "Use caveman LITE: no filler/hedging, keep articles + full sentences.",
    "full": "",   # default — rules already say full
    "ultra": "Use caveman ULTRA: abbreviate (DB/auth/config/req/res/fn/impl), arrows for causality (X→Y), one word when enough.",
}


def build_caveman_system_prompt(intensity: str = "full") -> str:
    override = _INTENSITY_OVERRIDE.get(intensity, "")
    prefix = f"{override}\n\n" if override else ""
    return f"{prefix}{_CAVEMAN_RULES}"


# ---------------------------------------------------------------------------
# CavemanBackend — wraps any Meta-Reasoning LLMBackend
# ---------------------------------------------------------------------------

class CavemanBackend:
    """
    Wraps an LLMBackend, prepending the Caveman system prompt to every call.
    Transparent to Meta-Reasoning's Substrate — satisfies LLMBackend protocol.
    """

    def __init__(self, inner: Any, intensity: str = "full") -> None:
        self._inner = inner
        self._caveman_prompt = build_caveman_system_prompt(intensity)

    def generate(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        patched = list(messages)
        # Inject caveman rules as the very first system message
        patched.insert(0, {"role": "system", "content": self._caveman_prompt})
        return self._inner.generate(patched)
