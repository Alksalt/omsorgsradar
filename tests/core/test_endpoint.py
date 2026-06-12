import pytest
from omsorgsradar.core.endpoint import (
    build_client, AnthropicClient, OpenAIClient, LLMResponse, estimate_cost,
)


class _FakeAnthropicMsg:
    def __init__(self):
        self.content = [type("B", (), {"text": "narrert"})()]
        self.usage = type("U", (), {"input_tokens": 100, "output_tokens": 50})()


def test_subscription_builds_no_client():
    client, model = build_client({"endpoint": {"mode": "subscription"},
                                  "models": {"report": "claude-fable-5"}}, role="report")
    assert client is None
    assert model == "claude-fable-5"


def test_model_none_builds_no_client():
    client, model = build_client({"endpoint": {"mode": "api", "api": {"provider": "anthropic"}},
                                  "models": {"report": "none"}}, role="report")
    assert client is None


def test_local_builds_anthropic_client_no_key_needed(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    wf = {"endpoint": {"mode": "local", "local": {"base_url": "http://localhost:1234"}},
          "models": {"report": "local-model"}}
    client, model = build_client(wf, role="report")
    assert isinstance(client, AnthropicClient)
    assert client.base_url == "http://localhost:1234"


def test_local_openai_flavor(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    wf = {"endpoint": {"mode": "local",
                       "local": {"base_url": "http://localhost:1234/v1", "api": "openai"}},
          "models": {"report": "lmstudio"}}
    client, _ = build_client(wf, role="report")
    assert isinstance(client, OpenAIClient)


def test_api_anthropic_requires_env_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    wf = {"endpoint": {"mode": "api", "api": {"provider": "anthropic"}},
          "models": {"report": "claude-fable-5"}}
    client, _ = build_client(wf, role="report")
    assert client is None


def test_api_openrouter_uses_openai_client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    wf = {"endpoint": {"mode": "api", "api": {"provider": "openrouter"}},
          "models": {"report": "anthropic/claude-3.5"}}
    client, _ = build_client(wf, role="report")
    assert isinstance(client, OpenAIClient)
    assert "openrouter.ai" in client.base_url


def test_api_anthropic_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    wf = {"endpoint": {"mode": "api", "api": {"provider": "anthropic"}},
          "models": {"report": "claude-fable-5"}}
    client, _ = build_client(wf, role="report")
    assert isinstance(client, AnthropicClient)


def test_anthropic_client_normalizes_response(monkeypatch):
    ac = AnthropicClient(api_key="k")
    monkeypatch.setattr(ac, "_sdk_create", lambda **kw: _FakeAnthropicMsg())
    resp = ac.complete("hei", model="claude-fable-5", max_tokens=100)
    assert isinstance(resp, LLMResponse)
    assert resp.text == "narrert"
    assert resp.input_tokens == 100 and resp.output_tokens == 50


def test_estimate_cost_known_model_and_unknown():
    known = estimate_cost("claude-fable-5", 1_000_000, 1_000_000)
    assert known is not None and known > 0
    assert estimate_cost("some-local-model", 100, 100) is None
