from __future__ import annotations

import json
import os
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from ..config import Config


def _build_client(cfg: Config):
    boto_cfg = BotoConfig(
        read_timeout=300,
        connect_timeout=10,
        retries={"max_attempts": 3, "mode": "adaptive"},
    )
    token = cfg.aws_bearer_token
    region = cfg.aws_region

    if token:
        return boto3.client(
            service_name="bedrock-runtime",
            region_name=region,
            aws_access_key_id="BEDROCK_API_KEY",
            aws_secret_access_key=token,
            config=boto_cfg,
        )
    return boto3.client(
        service_name="bedrock-runtime",
        region_name=region,
        config=boto_cfg,
    )


class BedrockBackend:
    """
    AWS Bedrock implementation of Meta-Reasoning's LLMBackend protocol.
    Uses the Converse API for broad model compatibility.
    """

    def __init__(self, cfg: Config) -> None:
        self._client = _build_client(cfg)
        self._model = cfg.llm_model
        self._max_tokens = cfg.llm_max_tokens

    def generate(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        system_parts: list[str] = []
        chat: list[dict[str, Any]] = []

        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                chat.append({
                    "role": m["role"],
                    "content": [{"text": m["content"]}],
                })

        if not chat:
            chat = [{"role": "user", "content": [{"text": "(begin)"}]}]

        kwargs: dict[str, Any] = {
            "modelId": self._model,
            "messages": chat,
            "inferenceConfig": {"maxTokens": self._max_tokens},
        }
        if system_parts:
            kwargs["system"] = [{"text": "\n\n".join(system_parts)}]

        response = self._client.converse(**kwargs)

        # Extract text from response
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])
        text = ""
        for block in content_blocks:
            if "text" in block:
                text += block["text"]

        usage = response.get("usage", {})
        return {
            "content": text,
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
        }
