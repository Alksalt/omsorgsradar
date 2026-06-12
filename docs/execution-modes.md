# Execution modes — where the LLM runs

The omsorgsradar **engine computes nothing with an LLM** — every number is produced
by code and re-checked by the verifier. The *only* optional LLM touchpoint is the
report stage's narration of pre-computed findings. This doc explains how that one
call is routed across cloud, local, and subscription setups, and the privacy policy
that decides which to use.

Selected by `[endpoint].mode` in `workflow.toml`. Resolution lives in
`src/omsorgsradar/core/endpoint.py`.

## The three modes

| Mode | Engine behaviour | Who narrates | When |
|---|---|---|---|
| `subscription` *(default, primary)* | Engine makes **no API calls** — renders the deterministic template report ($0). | The agentic shell (Claude Code on your Anthropic sub; Codex CLI parity via `AGENTS.md`) narrates from `findings.json`. | Normal portfolio use. |
| `api` | Engine calls a cloud provider directly. | The engine, via `anthropic` / `openai` SDK. | Batch/headless runs where no interactive shell is present. |
| `local` | Engine calls a local inference server. | The engine, via a local Anthropic- or OpenAI-compatible endpoint. | **Sensitive/identifiable data** — nothing leaves the machine. |

A standalone Python process cannot borrow Claude Code's subscription OAuth token, so
"subscription" deliberately means *the engine defers narration to the shell* and stays
LLM-free. `api`/`local` are where the engine itself talks to a model.

## Providers (`api` mode)

`[endpoint.api].provider` ∈ `anthropic | openai | openrouter`:

- **anthropic** → Anthropic Messages API (`ANTHROPIC_API_KEY`).
- **openai** → OpenAI Chat Completions (`OPENAI_API_KEY`).
- **openrouter** → OpenAI-compatible at `https://openrouter.ai/api/v1` (`OPENROUTER_API_KEY`).

The model is `[models].report`. It must be valid for the selected provider (e.g.
`claude-fable-5` for anthropic, a `gpt-*` / routed id for openai/openrouter) — the
engine passes it through; a mismatch surfaces as the provider's own error.

## Keys live in the environment — never in config

API keys are read **only** from environment variables (`ANTHROPIC_API_KEY` etc.).
`workflow.toml` is scanned at load time (`core/config._reject_key_material`) and any
key that looks like a credential — `api_key`, `key`, `token`, `secret`, `password`,
`auth`, … — is **rejected with an error**. Keys never enter the config, never enter
the run journal (`runs/<id>/run.json` snapshots `workflow`, so a key there would be
persisted), never enter `cost_info` or the report. If `api` mode is selected with no
key in the environment, the engine falls back to the template renderer rather than
failing.

## Local inference (the privacy path)

`[endpoint].mode = "local"` with `[endpoint.local]`:

```toml
[endpoint]
mode = "local"
[endpoint.local]
base_url = "http://localhost:1234/v1"
api = "openai"        # "openai" for LM Studio/Ollama's OpenAI-compatible API;
                      # "anthropic" for an Anthropic-compatible local server
```

No API key is needed. Recipe (LM Studio):

1. Load a model in LM Studio (e.g. a Devstral-Small-2-class or Qwen-class instruct
   model) and start its local server (default `http://localhost:1234`, OpenAI-compatible
   `/v1`).
2. Set the `[endpoint]` block above; set `[models].report` to the model id LM Studio
   reports (or any string — LM Studio serves the loaded model).
3. Run `uv run python -m omsorgsradar.pipeline analyses/omsorgsradar`. The report
   narration is produced entirely on your machine. (Ollama works the same way via its
   OpenAI-compatible endpoint.)

The offline test `tests/test_report_modes.py::TestReportModes::test_local_mode_round_trip`
proves the local path end-to-end against a stubbed server.

## Normen privacy → placement mapping

Per the **Normen skytjeneste-veileder** (Norm for informasjonssikkerhet og personvern
i helse- og omsorgssektoren), the sensitivity of the data decides where compute may run:

| Data sensitivity | Placement | Mode | Notes |
|---|---|---|---|
| **Open / aggregate** (SSB, FHI, Sotkanet, Kolada, …) | Any cloud | `subscription` / `api` | What omsorgsradar itself uses — cloud is appropriate. |
| **Pseudonymised** | EU-hosted, data-processor agreement | *(documented target)* | AWS Bedrock `eu-central-1` or Google Vertex EU. **Not an implemented provider** — placement guidance for reuse of this workflow on pseudonymised data. |
| **Identifiable / sensitive** | On-premise / local only | `local` | No data leaves the machine; LM Studio / Ollama. |

**omsorgsradar uses only open aggregate statistics** (hard constraint, `DECISIONS.md`),
so cloud is correct here. The pseudonymised → EU-hosted and sensitive → local rows are
the placement policy the engine is *built to support* when the generalized workflow is
reused on regulated data (e.g. a future fhir-safety-harness deployment). Bedrock/Vertex
EU are named as the EU-residency targets but are not wired as providers in this repo —
adding them is a config + client extension, not an engine change.

## Summary

- Default is `subscription`: deterministic, $0, shell narrates.
- `api` adds anthropic/openai/openrouter; keys from env only.
- `local` keeps everything on-machine for sensitive data.
- Provider/model/placement are config — no code change to switch.
