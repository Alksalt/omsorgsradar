# G5 — Execution Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Sonnet implementers; opus review panel (correctness/security/integration) at phase close. ≤10-agent budget — one implementer at a time, fan-out only for the closing panel.

**Goal:** Make the engine's optional LLM use config-selectable across **subscription / api / local** execution modes (and anthropic / openai / openrouter providers + Anthropic- or OpenAI-compatible local servers), with a working, verifiable local-inference path, a hardened endpoint schema that keeps key material out of TOML, and a documented Normen privacy→placement mapping.

**Architecture:** The engine stays LLM-free for all computation; the *only* LLM touchpoint is `report.render_llm` (optional narration of pre-computed findings). Today it hardcodes `anthropic.Anthropic(...)`, the model, and pricing, and ignores `workflow.toml`'s `[endpoint]`/`[models]`. G5 adds a thin `core/endpoint.py` that resolves `[endpoint]` + `[models]` into a provider-agnostic `LLMClient` (or `None` for subscription, where narration is deferred to the agentic shell). `report` consumes it; nothing else in the engine changes. Keys are read **only** from environment, never from config, never journaled.

**Tech Stack:** Python via `uv`; `anthropic` (present) + `openai` (new, lazy-imported) SDKs behind one `LLMClient` protocol; existing config/schema layer (`core/config.py`); existing report stage.

---

## What exists (blast radius)

- `src/omsorgsradar/report.py:380-518` `render_llm` — builds `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`, hardcodes `model="claude-sonnet-4-5"` and pricing `3.0/15.0`. `run_report:526-580` auto-detects `use_llm` from `ANTHROPIC_API_KEY` presence and falls back to template on any error.
- `src/omsorgsradar/stages.py:170-191` `stage_report` → `run_report(..., use_llm=ctx.state.get("use_llm"))`. Has `ctx.config.workflow` available but does not pass it.
- `src/omsorgsradar/core/config.py:26-66` `WORKFLOW_SCHEMA` — `[endpoint]` (mode/api.provider/local.base_url), `[models]` (additionalProperties string), `[defaults]`, `[security]`. `[endpoint]` blocks allow arbitrary extra keys today.
- `workflow.toml` — `[models] profile/report`, `[endpoint] mode="subscription"`, `[endpoint.api] provider="anthropic"`, `[endpoint.local] base_url`.
- Only the **omsorgsradar** core analysis uses the LLM path; `nordisk-omsorg` and `brfss-demo` render bokmål deterministically (no LLM). So the wiring touches exactly `report.py` + `stages.py` + the new `core/endpoint.py`.
- `openai` is **not** installed.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | add `openai` (lazy-imported, like the anthropic/ml deps) |
| `src/omsorgsradar/core/endpoint.py` | `EndpointConfig`, `LLMResponse`, `LLMClient` protocol, `AnthropicClient`, `OpenAIClient`, `build_client()`, `MODEL_PRICING` |
| `src/omsorgsradar/core/config.py` | harden `WORKFLOW_SCHEMA` (`additionalProperties:false` on endpoint blocks) + `reject_key_material()` |
| `src/omsorgsradar/report.py` | `render_llm` takes an `LLMClient` + model; `run_report` becomes endpoint-aware |
| `src/omsorgsradar/stages.py` | `stage_report` threads `ctx.config.workflow` into `run_report` |
| `workflow.toml` | commented example of all three modes; `[endpoint.local].api` |
| `docs/execution-modes.md` | modes, providers, env vars, Normen privacy→placement mapping, LM Studio recipe |
| `tests/core/test_endpoint.py` | resolution + client wiring + pricing (monkeypatched SDKs) |
| `tests/core/test_config.py` | extend: key-material rejection + strict endpoint schema |
| `tests/test_report_modes.py` | report stage per mode (subscription→template; local→client round-trip; api-no-key→fallback) |

---

### Task 1: `core/endpoint.py` — provider-agnostic LLM layer

**Files:**
- Modify: `pyproject.toml` (add `openai`)
- Create: `src/omsorgsradar/core/endpoint.py`
- Test: `tests/core/test_endpoint.py`

- [ ] **Step 1: Add the dep**

```bash
uv add openai
uv run pytest -q   # expect 272 passed, 5 deselected — no regression
```

- [ ] **Step 2: Write the failing tests** (`tests/core/test_endpoint.py`)

```python
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
    assert client is None              # engine makes no calls; shell narrates
    assert model == "claude-fable-5"


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
    assert client is None             # no key -> caller falls back to template


def test_api_openrouter_uses_openai_client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    wf = {"endpoint": {"mode": "api", "api": {"provider": "openrouter"}},
          "models": {"report": "anthropic/claude-3.5"}}
    client, _ = build_client(wf, role="report")
    assert isinstance(client, OpenAIClient)
    assert "openrouter.ai" in client.base_url


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
```

- [ ] **Step 3: Run to confirm failure.**

- [ ] **Step 4: Implement `core/endpoint.py`**

```python
"""Execution-mode → LLM client resolution (the only LLM touchpoint the engine has).

The engine computes nothing with an LLM; `report.render_llm` optionally narrates
pre-computed findings. This module turns workflow.toml's [endpoint] + [models] into
a provider-agnostic client (or None for subscription, where the agentic shell
narrates instead). API keys are read ONLY from the environment — never from config,
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

# Known cloud base URLs (provider -> OpenAI-compatible base). Anthropic/OpenAI use
# their SDK defaults; only openrouter needs an explicit base.
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Per-MTok USD pricing for cost estimates (informational, COSTS.md). Estimates as of
# 2026-06; refine from the claude-api skill. Models absent here -> cost unknown (None).
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model: (input_per_mtok, output_per_mtok)
    "claude-fable-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
}

# Env var holding the API key per provider. Key material lives ONLY here.
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
    """Anthropic Messages API — cloud (key) or local/compatible (base_url)."""
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
    """OpenAI Chat Completions API — openai cloud, openrouter, or OpenAI-compatible local."""
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
    subscription mode, an api provider with no env key, or models[role] == "none".
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
            return None, model               # caller falls back to template
        if provider == "anthropic":
            return AnthropicClient(api_key=key), model
        if provider == "openrouter":
            return OpenAIClient(api_key=key, base_url=_OPENROUTER_BASE), model
        return OpenAIClient(api_key=key), model   # openai

    return None, model
```

- [ ] **Step 5: Run** `uv run pytest tests/core/test_endpoint.py -v` → PASS.

- [ ] **Step 6: Commit** — `git commit -m "G5: core/endpoint.py — provider-agnostic LLM client + mode resolution"`

---

### Task 2: WORKFLOW_SCHEMA security hardening (key material never in TOML)

**Files:**
- Modify: `src/omsorgsradar/core/config.py`
- Test: `tests/core/test_config.py`

Spec security gate: "set `additionalProperties: false` in WORKFLOW_SCHEMA and reject key-material field names (api_key/key/token/secret) — keys live in env, never in TOML, never in run journals."

- [ ] **Step 1: Write the failing tests** (append to `tests/core/test_config.py`)

```python
class TestEndpointSecurity:
    def _wf(self, tmp_path, body: str):
        p = tmp_path / "workflow.toml"
        p.write_text(body, encoding="utf-8")
        return p

    def test_api_key_in_toml_rejected(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config, ConfigError
        import pytest
        body = ('[endpoint]\nmode = "api"\n[endpoint.api]\nprovider = "anthropic"\n'
                'api_key = "sk-leak"\n')
        with pytest.raises(ConfigError, match="key material"):
            load_workflow_config(self._wf(tmp_path, body))

    def test_secret_named_field_anywhere_rejected(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config, ConfigError
        import pytest
        body = '[endpoint]\nmode = "subscription"\n[models]\ntoken = "x"\n'
        with pytest.raises(ConfigError, match="key material"):
            load_workflow_config(self._wf(tmp_path, body))

    def test_unknown_endpoint_field_rejected(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config, ConfigError
        import pytest
        body = '[endpoint]\nmode = "subscription"\nflavour = "x"\n'
        with pytest.raises(ConfigError):
            load_workflow_config(self._wf(tmp_path, body))

    def test_local_api_flavor_allowed(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config
        body = ('[endpoint]\nmode = "local"\n[endpoint.local]\n'
                'base_url = "http://localhost:1234"\napi = "openai"\n')
        cfg = load_workflow_config(self._wf(tmp_path, body))
        assert cfg["endpoint"]["local"]["api"] == "openai"
```

Confirm the existing repo `workflow.toml` still loads (no key-material names, no unknown endpoint fields).

- [ ] **Step 2: Run to confirm failure.**

- [ ] **Step 3: Harden the schema** — in `WORKFLOW_SCHEMA`, set the `endpoint` object and its `api`/`local` sub-objects to `"additionalProperties": false`, and add the allowed fields:

```python
        "endpoint": {
            "type": "object",
            "required": ["mode"],
            "additionalProperties": False,
            "properties": {
                "mode": {"enum": ENDPOINT_MODES},
                "api": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "provider": {"enum": ["anthropic", "openai", "openrouter"]},
                        "base_url": {"type": "string"},
                    },
                },
                "local": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "base_url": {"type": "string"},
                        "api": {"enum": ["anthropic", "openai"]},
                    },
                },
            },
        },
```

- [ ] **Step 4: Add `reject_key_material` and call it in `load_workflow_config`**

```python
_KEY_MATERIAL_NAMES = {"api_key", "apikey", "key", "token", "secret", "password",
                       "access_key", "auth", "authorization", "bearer"}


def _reject_key_material(node: Any, path: str = "") -> None:
    """Refuse any config key that looks like a credential. Keys live in env only
    (spec security gate) — never in workflow.toml, never in run journals."""
    if isinstance(node, dict):
        for k, v in node.items():
            if str(k).lower() in _KEY_MATERIAL_NAMES:
                raise ConfigError(
                    f"key material is not allowed in config ('{path}{k}') — "
                    "set the API key in the environment (e.g. ANTHROPIC_API_KEY), "
                    "never in workflow.toml"
                )
            _reject_key_material(v, f"{path}{k}.")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _reject_key_material(item, f"{path}{i}.")


def load_workflow_config(path: Path) -> dict[str, Any]:
    payload = _load_toml(path)
    _reject_key_material(payload)
    _validate(payload, WORKFLOW_SCHEMA, path)
    return payload
```

(`_reject_key_material` runs before schema validation so the credential error is the one surfaced.)

- [ ] **Step 5: Run** `uv run pytest tests/core/test_config.py -v` → PASS. Confirm the repo `workflow.toml` still loads via `uv run python -m omsorgsradar.pipeline analyses/omsorgsradar --validate-only`.

- [ ] **Step 6: Commit** — `git commit -m "G5: workflow schema hardening — no key material in TOML, strict endpoint blocks"`

---

### Task 3: Wire the report stage to execution modes

**Files:**
- Modify: `src/omsorgsradar/report.py`
- Modify: `src/omsorgsradar/stages.py`
- Test: `tests/test_report_modes.py`

- [ ] **Step 1: Write the failing tests** (`tests/test_report_modes.py`)

```python
import json
from pathlib import Path
import pytest
from omsorgsradar.report import run_report
from omsorgsradar.core.endpoint import LLMResponse


def _result():
    # Build a minimal AnalysisResult via the existing test helper/fixture.
    from omsorgsradar.analyze import run_analysis
    import pandas as pd
    # Reuse the offline fixture path used by tests/test_analyze.py; if a builder
    # helper exists there, import it. Otherwise construct a 1-2 kommune result.
    ...


class TestReportModes:
    def test_subscription_uses_template_no_calls(self, tmp_path, monkeypatch):
        # subscription -> engine never instantiates a client; cost_info renderer == template
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-ignored")
        wf = {"endpoint": {"mode": "subscription"}, "models": {"report": "claude-fable-5"}}
        path, cost = run_report(_result(), report_dir=tmp_path, workflow=wf)
        assert cost["renderer"] == "template"

    def test_local_mode_round_trip(self, tmp_path, monkeypatch):
        # local -> AnthropicClient built; monkeypatch its _sdk_create so no network.
        from omsorgsradar.core import endpoint as ep
        monkeypatch.setattr(
            ep.AnthropicClient, "_sdk_create",
            lambda self, **kw: type("M", (), {
                "content": [type("B", (), {"text": "LOKAL NARRASJON"})()],
                "usage": type("U", (), {"input_tokens": 10, "output_tokens": 5})()})(),
        )
        wf = {"endpoint": {"mode": "local", "local": {"base_url": "http://localhost:1234"}},
              "models": {"report": "local-model"}}
        path, cost = run_report(_result(), report_dir=tmp_path, workflow=wf)
        assert "LOKAL NARRASJON" in Path(path).read_text(encoding="utf-8")
        assert cost["renderer"] == "llm"
        assert cost["model"] == "local-model"

    def test_api_no_key_falls_back_to_template(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        wf = {"endpoint": {"mode": "api", "api": {"provider": "anthropic"}},
              "models": {"report": "claude-fable-5"}}
        path, cost = run_report(_result(), report_dir=tmp_path, workflow=wf)
        assert cost["renderer"] == "template"
```

(The implementer should reuse whatever `AnalysisResult` builder the existing `tests/test_report*`/`test_analyze.py` use; if none, build a minimal result inline. Keep it offline.)

- [ ] **Step 2: Run to confirm failure.**

- [ ] **Step 3: Refactor `render_llm`** to take an `LLMClient` + model instead of building its own client / reading env / hardcoding pricing:

```python
def render_llm(result, quality_report, verification, client, model, n_top=20):
    """Narrate findings using a resolved LLMClient (mode/provider-agnostic)."""
    from .analyze import result_to_dict
    from .core.endpoint import estimate_cost
    # ... build summary_payload + prompt exactly as today ...
    resp = client.complete(prompt, model=model, max_tokens=2000)
    llm_text = resp.text
    cost_info = {
        "model": model,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "estimated_cost_usd": estimate_cost(model, resp.input_tokens, resp.output_tokens),
    }
    # ... assemble report (LLM intro + table + figures) as today ...
    return report, cost_info
```

- [ ] **Step 4: Make `run_report` endpoint-aware** — accept `workflow: dict | None` and resolve the client via `build_client`; keep `use_llm` as an explicit override (False forces template — used by existing tests like `test_pipeline_gate.py` which pass `use_llm=False`):

```python
def run_report(result, quality_report=None, report_dir=REPORT_DIR,
               use_llm=None, workflow=None):
    # figures + verification unchanged ...
    from .core.endpoint import build_client
    cost_info = {"path": "key-free template renderer", "renderer": "template"}

    client, model = (None, None)
    if workflow is not None and use_llm is not False:
        client, model = build_client(workflow, role="report")

    if client is not None and model is not None:
        try:
            report_md, cost_info = render_llm(result, quality_report, verification,
                                              client=client, model=model)
            cost_info["renderer"] = "llm"
        except Exception as exc:
            logger.warning("LLM renderer failed (%s); falling back to template", exc)
            report_md = render_template(result, quality_report, verification)
            cost_info = {"renderer": "template_fallback", "error": str(exc)}
    else:
        report_md = render_template(result, quality_report, verification)
    report_path = report_dir / "omsorgsradar_rapport.md"
    report_path.write_text(report_md, encoding="utf-8")
    return report_path, cost_info
```

Keep backward behavior: when `workflow is None` (legacy callers) → template. When `use_llm=False` → template (test path). The old `ANTHROPIC_API_KEY`-autodetect is replaced by mode resolution.

- [ ] **Step 5: Thread workflow through `stage_report`** in `stages.py`:

```python
    report_path, cost_info = run_report(
        result=ctx.state["result"],
        quality_report=ctx.state["quality_report"],
        report_dir=ctx.reports_dir,
        use_llm=ctx.state.get("use_llm"),
        workflow=ctx.config.workflow,
    )
```

- [ ] **Step 6: Run** `uv run pytest tests/test_report_modes.py tests/test_pipeline_gate.py -v` → PASS (the gate test passes `use_llm=False` → template, must still be green). Then full suite.

- [ ] **Step 7: Commit** — `git commit -m "G5: report stage consumes execution-mode config (subscription/api/local)"`

---

### Task 4: Docs (Normen mapping) + workflow.toml example + repo docs

**Files:**
- Create: `docs/execution-modes.md`
- Modify: `workflow.toml`, `README.md`, `COSTS.md`, `DECISIONS.md`, `status.md`, `.claude/skills/pipeline-stages/SKILL.md`
- Modify: `docs/specs/2026-06-11-v2-generalization-design.md` (as-built note)

- [ ] **Step 1: `docs/execution-modes.md`** — cover:
  - The three modes and when each applies; how to select (`[endpoint].mode`).
  - Provider matrix: anthropic (Messages), openai/openrouter (Chat Completions), local (Anthropic- or OpenAI-compatible via `[endpoint.local].api`).
  - **Env vars per provider** (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY`) and the hard rule: **keys live in env, never in `workflow.toml`, never in run journals** (enforced by `reject_key_material`).
  - **Subscription = primary**: the engine makes no API calls; the agentic shell (Claude Code on Anthropic sub; Codex CLI parity via AGENTS.md) narrates from `findings.json`. Engine cost = $0.
  - **Normen privacy→placement mapping** (table): open data → cloud (any provider); pseudonymized → EU-hosted (AWS Bedrock `eu-central-1` / Google Vertex EU) — documented target, not yet an implemented provider; sensitive/identifiable → **local** (LM Studio / Ollama, no data leaves the machine). Reference the **Normen skytjeneste-veileder** and note omsorgsradar itself uses only open aggregate data, so cloud is appropriate here; the mapping is the reuse policy for the generalized workflow.
  - **LM Studio / Ollama recipe** for the local demo (start server, set `[endpoint] mode="local"`, `[endpoint.local] base_url=...`, `api="openai"` for LM Studio's OpenAI-compatible `/v1`, run the omsorgsradar pipeline; narration is produced locally).

- [ ] **Step 2: `workflow.toml`** — add commented examples for all three modes + `[endpoint.local].api`, and a one-line "keys go in env, never here" comment. Do not change the active `mode = "subscription"`.

- [ ] **Step 3: `COSTS.md`** — add an execution-modes section: subscription = $0 engine cost (shell narrates); api = per-model token cost (point at `MODEL_PRICING`); local = $0 marginal (local compute only). `README.md` — one paragraph + link to `docs/execution-modes.md`. `pipeline-stages` SKILL.md — note the report stage honors `[endpoint].mode`.

- [ ] **Step 4: `DECISIONS.md`** — confirm/extend the existing execution-mode + security bullets to match as-built (subscription primary; api anthropic/openai/openrouter; local Anthropic- or OpenAI-compatible; key material env-only, rejected from TOML by `reject_key_material`; Bedrock/Vertex EU are documented placement targets, not implemented providers). `docs/specs/...` — add an "as built (G5)" note. `status.md` — G5 entry.

- [ ] **Step 5: Run** the full suite + `--validate-only` on all three analyses. **Commit** — `git commit -m "G5: execution-modes docs (Normen privacy mapping) + workflow examples + repo docs"`

---

## Closing panel (after Task 4)

`blast-radius-mapper` context folded into 3 reviewers (per G4 precedent):
- **security (opus)**: key material truly cannot reach config/journal/logs (`reject_key_material` coverage + run journal snapshot review — `config_snapshot` includes `cfg.workflow`, confirm no key can be there); local/api base_url not an SSRF vector beyond the user's own config; no key echoed in `cost_info` or report.
- **correctness (opus)**: mode resolution matrix (subscription/api/local × anthropic/openai/openrouter) returns the right client; api-no-key → template fallback; response normalization (anthropic vs openai token fields); pricing lookup.
- **integration (sonnet)**: `openai` declared + lazy; `render_llm` signature change has no stale callers; `test_pipeline_gate` (use_llm=False) still green; `run_report(workflow=None)` legacy path intact; all three analyses `--validate-only` pass.

Any BLOCK → fix + re-review (cap 3). Then push to `main`.

## Self-review (writing-plans checklist)

- **Spec coverage:** subscription/api/local modes ✓ (Task 1 `build_client`) · anthropic/openai/openrouter ✓ (Task 1 clients) · working local demo of ≥1 stage ✓ (Task 3 `test_local_mode_round_trip` + Task 4 LM Studio recipe) · `additionalProperties:false` + reject key-material ✓ (Task 2) · Normen privacy→placement mapping + skytjeneste-veileder ref ✓ (Task 4) · keys in env never TOML/journal ✓ (Task 2 + security panel).
- **Placeholder scan:** the only `...` is in Task 3 Step 1's `_result()` builder, which explicitly delegates to the existing `test_analyze.py`/report-test result construction rather than reprinting it — resolved by the implementer reusing the in-repo helper.
- **Type consistency:** `build_client -> (LLMClient | None, str | None)` used identically in Task 1 tests, `report.run_report` (Task 3), and the panel. `LLMResponse(text, input_tokens, output_tokens, model)` fields match `render_llm`'s cost_info construction. `_sdk_create` is the single monkeypatch seam used by both Task 1 and Task 3 tests.
- **Bounded scope:** Bedrock/Vertex are documented placement targets, NOT implemented providers (omsorgsradar uses open data only) — stated in Task 4 + DECISIONS so it is not mistaken for a gap.
