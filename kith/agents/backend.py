from __future__ import annotations

from typing import Any

import anthropic

from ..config import Config


class AnthropicBackend:
    """
    Anthropic implementation of Meta-Reasoning's LLMBackend protocol.
    Handles message role mapping (system messages → system param).
    """

    def __init__(self, cfg: Config) -> None:
        self._client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        self._model = cfg.llm_model
        self._max_tokens = cfg.llm_max_tokens

    def generate(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        # Anthropic separates system from user/assistant messages
        system_parts: list[str] = []
        chat: list[dict[str, str]] = []

        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                chat.append(m)

        system = "\n\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN

        # Ensure at least one user message
        if not chat:
            chat = [{"role": "user", "content": "(begin)"}]

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=chat,
        )

        text = response.content[0].text if response.content else ""
        return {
            "content": text,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
