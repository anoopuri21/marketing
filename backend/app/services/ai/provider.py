"""Pluggable LLM client.

`ai_client.complete_json(system, user)` returns a dict. The provider is picked from
settings (OpenAI / Anthropic). When no key is configured, callers must fall back to
rule-based logic – see `ai_client.available`.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.http import ssl_context

log = logging.getLogger(__name__)


class AIClient:
    def __init__(self) -> None:
        self.provider = settings.resolved_ai_provider

    @property
    def available(self) -> bool:
        return self.provider in ("openai", "anthropic")

    # ------------------------------------------------------------------ #
    async def complete_text(self, system: str, user: str, max_tokens: int = 1500, temperature: float = 0.4) -> str:
        if self.provider == "openai":
            return await self._openai(system, user, max_tokens, temperature)
        if self.provider == "anthropic":
            return await self._anthropic(system, user, max_tokens, temperature)
        raise RuntimeError("No AI provider configured")

    async def complete_json(self, system: str, user: str, max_tokens: int = 2000) -> Dict[str, Any]:
        system_json = system + "\n\nRespond ONLY with a single valid JSON object. No prose, no markdown fences."
        text = await self.complete_text(system_json, user, max_tokens=max_tokens, temperature=0.3)
        return _extract_json(text)

    # ------------------------------------------------------------------ #
    async def _openai(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        url = settings.openai_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": settings.openai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=90, verify=ssl_context()) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def _anthropic(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": settings.anthropic_model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=90, verify=ssl_context()) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []))


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    log.warning("AI response was not valid JSON: %s", text[:200])
    return {}


ai_client = AIClient()
