"""Talks to the LLM provider. Only the AI layer imports this; the engine never does.

Plain httpx instead of the vendor SDK: we use one endpoint, and this keeps the
dependency list short and the request easy to see.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings


class LLMUnavailable(Exception):
    """Any reason we couldn't get a usable response. Callers fall back to the rule-based path."""


@dataclass
class LLMResponse:
    content: list[dict]
    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)  # provider metadata (message id), kept for debugging

    def tool_uses(self) -> list[dict]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    def text(self) -> str:
        return "\n".join(b.get("text", "") for b in self.content if b.get("type") == "text").strip()


class LLMClient(Protocol):
    """What the report and query code need from a client. Tests pass a fake with the same shape."""

    model: str

    def create(self, *, system: str, messages: list[dict], tools: list[dict] | None = None,
               tool_choice: dict | None = None, max_tokens: int | None = None) -> LLMResponse: ...


_HTTP_ERRORS = {
    401: "the API key was rejected",
    403: "the API key isn't allowed to use this model",
    404: "the model name wasn't found (check LLM_MODEL)",
    429: "rate limited or out of quota",
}


class AnthropicClient:

    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set.")
        self.model = settings.llm_model
        self._settings = settings
        self._client = httpx.Client(base_url=settings.anthropic_base_url, timeout=settings.llm_timeout_s, headers={
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })

    def create(self, *, system, messages, tools=None, tool_choice=None, max_tokens=None) -> LLMResponse:
        body: dict = {"model": self.model, "max_tokens": max_tokens or self._settings.llm_max_tokens,
                      "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        t0 = time.perf_counter()
        try:
            resp = self._client.post("/v1/messages", json=body)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"LLM request timed out after {self._settings.llm_timeout_s:g}s") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Could not reach the LLM API ({type(exc).__name__})") from exc
        latency = int((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 400:
            reason = _HTTP_ERRORS.get(resp.status_code) or (
                "provider error" if resp.status_code >= 500 else resp.text[:300])
            raise LLMUnavailable(f"LLM request failed with HTTP {resp.status_code}: {reason}")
        data = resp.json()
        usage = data.get("usage", {})
        return LLMResponse(content=data.get("content", []), stop_reason=data.get("stop_reason", ""),
                           input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
                           latency_ms=latency, raw={"id": data.get("id")})


def build_client(settings: Settings) -> LLMClient | None:
    """None means "no LLM configured"; callers then use the rule-based path."""
    if not settings.llm_enabled:
        return None
    try:
        return AnthropicClient(settings)
    except LLMUnavailable:
        return None


@lru_cache
def shared_client() -> LLMClient | None:
    # One client per process so HTTP connections get reused across requests.
    return build_client(get_settings())


def estimate_cost(settings: Settings, input_tokens: int, output_tokens: int) -> float | None:
    if not (settings.llm_price_in_per_mtok or settings.llm_price_out_per_mtok):
        return None
    return round(input_tokens / 1e6 * settings.llm_price_in_per_mtok
                 + output_tokens / 1e6 * settings.llm_price_out_per_mtok, 6)
