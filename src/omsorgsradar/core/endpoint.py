"""Execution-mode -> LLM client resolution (the only LLM touchpoint the engine has).

The engine computes nothing with an LLM; `report.render_llm` optionally narrates
pre-computed findings. This module turns workflow.toml's [endpoint] + [models] into
a provider-agnostic client (or None for subscription, where the agentic shell
narrates instead). API keys are read ONLY from the environment -- never from config,
never logged, never journaled (DECISIONS.md / spec security gate).

Modes:
  subscription -> None  (engine makes no calls; Claude Code/Codex shell narrates)
  api          -> AnthropicClient | OpenAIClient, key from env per provider
  local        -> AnthropicClient | OpenAIClient pointed at [endpoint.local].base_url
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Per-MTok USD pricing for cost estimates (informational, COSTS.md). Estimates as of
# 2026-06. Models absent here -> cost unknown (None).
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
}

_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient(Protocol):
    def complete(self, prompt: str, *, model: str, max_tokens: int) -> LLMResponse: ...


class AnthropicClient:
    """Anthropic Messages API -- cloud (key) or local/compatible (base_url)."""
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or "not-needed-local"
        self.base_url = base_url

    def _sdk_create(self, **kwargs: Any) -> Any:
        import anthropic
        kw: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kw["base_url"] = self.base_url
        return anthropic.Anthropic(**kw).messages.create(**kwargs)

    def complete(self, prompt: str, *, model: str, max_tokens: int) -> LLMResponse:
        msg = self._sdk_create(model=model, max_tokens=max_tokens,
                               messages=[{"role": "user", "content": prompt}])
        return LLMResponse(text=msg.content[0].text,
                           input_tokens=msg.usage.input_tokens,
                           output_tokens=msg.usage.output_tokens, model=model)


class OpenAIClient:
    """OpenAI Chat Completions API -- openai cloud, openrouter, or OpenAI-compatible local."""
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or "not-needed-local"
        self.base_url = base_url

    def _sdk_create(self, **kwargs: Any) -> Any:
        import openai
        kw: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kw["base_url"] = self.base_url
        return openai.OpenAI(**kw).chat.completions.create(**kwargs)

    def complete(self, prompt: str, *, model: str, max_tokens: int) -> LLMResponse:
        resp = self._sdk_create(model=model, max_tokens=max_tokens,
                                messages=[{"role": "user", "content": prompt}])
        u = resp.usage
        return LLMResponse(text=resp.choices[0].message.content,
                           input_tokens=u.prompt_tokens, output_tokens=u.completion_tokens,
                           model=model)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = MODEL_PRICING.get(model)
    if price is None:
        return None
    return round(input_tokens / 1_000_000 * price[0]
                 + output_tokens / 1_000_000 * price[1], 6)


def build_client(workflow: Mapping[str, Any], role: str = "report") -> tuple[LLMClient | None, str | None]:
    """Resolve (client, model) for a role from workflow config.

    Returns (None, model) when the engine should NOT call an LLM itself:
    subscription mode, an api provider with no env key, or models[role] in (None, "none").
    """
    endpoint = dict(workflow.get("endpoint", {}))
    mode = endpoint.get("mode", "subscription")
    model = dict(workflow.get("models", {})).get(role)
    if model in (None, "none"):
        return None, model

    if mode == "subscription":
        return None, model

    if mode == "local":
        local = dict(endpoint.get("local", {}))
        base_url = local.get("base_url")
        flavor = local.get("api", "anthropic")
        if flavor == "openai":
            return OpenAIClient(api_key=os.environ.get("OPENAI_API_KEY"), base_url=base_url), model
        return AnthropicClient(api_key=os.environ.get("ANTHROPIC_API_KEY"), base_url=base_url), model

    if mode == "api":
        provider = dict(endpoint.get("api", {})).get("provider", "anthropic")
        key = os.environ.get(_PROVIDER_ENV.get(provider, ""))
        if not key:
            return None, model
        if provider == "anthropic":
            return AnthropicClient(api_key=key), model
        if provider == "openrouter":
            return OpenAIClient(api_key=key, base_url=_OPENROUTER_BASE), model
        return OpenAIClient(api_key=key), model
    return None, model
