from __future__ import annotations

from typing import Any

from openai import OpenAI

from ..config import Config


class OpenAIBackend:
    """
    OpenAI implementation of Meta-Reasoning's LLMBackend protocol.
    Also used for Ollama (OpenAI-compatible API with custom base_url).
    """

    def __init__(self, cfg: Config, base_url: str | None = None) -> None:
        kwargs: dict[str, Any] = {"api_key": cfg.openai_api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = cfg.llm_model
        self._max_tokens = cfg.llm_max_tokens

    def generate(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        # OpenAI accepts system role natively — pass through
        if not messages:
            messages = [{"role": "user", "content": "(begin)"}]

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=self._max_tokens,
        )

        choice = response.choices[0] if response.choices else None
        text = choice.message.content or "" if choice else ""
        usage = response.usage

        return {
            "content": text,
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
        }
