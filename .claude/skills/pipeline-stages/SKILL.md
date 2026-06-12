---
name: pipeline-stages
description: How to run, extend, and debug the omsorgsradar analysis pipeline (ingest → profile → [anonymize] → analyze → verify → report → ml). Use when working on any pipeline stage, adding an analysis instance, or investigating a failed run.
---

# Pipeline stages

## Run
- Full run: `uv run python -m omsorgsradar.pipeline` (default analysis: omsorgsradar)
- Any instance: `uv run python -m omsorgsradar.pipeline analyses/<name>`
- Offline iteration: add `--skip-ingest` (reads DuckDB) and `--skip-ml`
- Validate a config without running: `uv run python -m omsorgsradar.pipeline analyses/<name> --validate-only`
- Owner-gate run (ingest+profile only): add `--until profile`
- Tests: `uv run pytest -x -q` — must be green before any commit

## Rules (DECISIONS.md, enforced)
- The LLM narrates and orchestrates; code computes. Never state a number that
  is not in `data/findings.json` / `data/ml_results.json`.
- `verify` always runs before `report` (engine-enforced; FAIL verdict aborts).
- Never Read `data/cache/**` or `*.duckdb` into context (hook-enforced).
  Inspect data via `data/quality_profile.json` or aggregate DuckDB queries.

## Extend
- New analysis: create `analyses/<name>/analysis.toml` (schema:
  `core/config.py`). Stage list + `[[sources]]` blocks; no code needed for
  existing adapters.
- Adapters: `pxweb | sotkanet | socialstyrelsen | kuhr | kolada | csv` — required fields per
  adapter in `docs/adapters.md`; validation runs at pipeline startup. New API shape →
  new module in `core/adapters/` + offline fixture + known-value test (never edit an
  existing adapter's behavior for a new dataset).
- Realness gates run in `profile` on every dataset (verdict in
  `data/quality_profile.json`); a FAIL verdict aborts before analyze. csv sources
  must declare `[sources.provenance]` institution + url.
- `anonymize` (optional core stage, runs after `profile`, before `analyze`): redacts PII
  (Presidio + Norwegian recognizers), k-anonymizes the quasi-identifiers, publishes a
  measured-residual-risk receipt (`data/identifiability.json`, WP216: singling-out/linkability/
  inference) and aborts on a FAIL verdict. Config in `[params.anonymize]`: `source`,
  `text_columns`, `quasi_identifiers`, `sensitive`, `k`, `generalize.<col>` (bins+labels or map),
  `thresholds` (l_min/inference/linkability), optional `spacy_model` (live NER). Sources holding
  microdata MUST set `row_level = true` — the engine refuses to run them without `anonymize` in the
  stage list, realness skips its shape-checks, and the raw path must live under `microdata/`
  (hook-blocked). See `docs/anonymize.md`. Example instance: `analyses/brfss-demo/`.
- Variant behavior: add `analyses/<name>/stages.py` with
  `register(registry)`; use `registry.register(name, fn, override=True)`.
  Core stages are never edited for a variant.
- Custom stages must write artifacts + manifests via
  `core.contracts.write_manifest` and validate known artifact types.

## Execution modes (report narration)
- The engine is LLM-free; the only optional LLM call is `report` narration, routed by
  `[endpoint].mode` in `workflow.toml` (`core/endpoint.py`): `subscription` (default — no
  engine calls, shell narrates, $0), `api` (anthropic/openai/openrouter), `local`
  (LM Studio/Ollama — Anthropic- or OpenAI-compatible). Model = `[models].report`.
- API keys come from the ENV only (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`OPENROUTER_API_KEY`);
  a credential-named key in `workflow.toml` is rejected at load. See `docs/execution-modes.md`.

## Debug a run
- Every run journals to `runs/<run-id>/run.json`: stage order, durations,
  artifact paths, status (`ok` | `gate_failed` | `error`).
- `gate_failed` → read `data/verification.json` for the failing claims.
