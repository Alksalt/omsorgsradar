# COSTS.md — Kommunal Omsorgsradar

## LLM narration cost (optional path)

The full pipeline has two rendering paths. The key-free template path has zero LLM cost.

### Key-free template path (default)
- **Cost: $0.00 per run**
- Produces the same structured report from the same findings JSON using a deterministic template renderer.
- All analysis, press index, figures, and verifier are unaffected.

### LLM narration path (optional; `api`/`local` mode)

Since G5 the model is **config-driven** (`[models].report`, default `claude-fable-5`) and the cost is
estimated from `core/endpoint.MODEL_PRICING`. Measured token estimate for a typical report narration call:

| Item | Tokens | Price (claude-fable-5: $1 in / $5 out per MTok) |
|------|--------|--------------------------------------------------|
| System + findings JSON prompt | ~2,500 input | $0.0025 |
| Bokmål narrative output | ~800 output | $0.004 |
| **Total per run** | ~3,300 | **~$0.007** |

Heavier models cost more in proportion (e.g. `claude-sonnet-4-6` ≈ $0.02/run; `claude-opus-4-8` ≈ $0.10/run).
`local` mode is $0 marginal. Pricing in `MODEL_PRICING` is dated 2026-06; refine as rates change.

**Estimated cost per full run with cloud narration: under ~$0.02 USD on the default model.** Negligible.

### TabPFN-2.5

TabPFN-2.5 was not run in v0.1 because it requires an interactive license acceptance via [priorlabs.ai](https://ux.priorlabs.ai). Once a `TABPFN_TOKEN` is set, TabPFN inference is free for research use (as of 2026). Local inference cost is compute only (CPU, ~30 seconds on ~3,000 rows).

### SSB / FHI API calls

Both SSB PxWebAPI v2 and FHI NOKKEL are **free, no authentication required** (CC BY 4.0 / open government data). The pipeline caches responses to `data/cache/` after the first run — subsequent runs cost zero API calls for ingest.

### Execution modes (report narration)

The report narration is routed by `[endpoint].mode` (see `docs/execution-modes.md`):

- **subscription** (default): engine makes **no API calls** → **$0**; the agentic shell narrates.
- **api**: per-model token cost (anthropic/openai/openrouter). Estimated from `core/endpoint.MODEL_PRICING`; a typical narration is ~3,300 tokens ≈ **$0.01–0.02** depending on the model.
- **local**: **$0 marginal** (local compute only; LM Studio/Ollama).

Keys are read from the environment only — never stored, never journaled.

### Anonymize stage (LLM-free)

The `anonymize` stage runs entirely in engine code (Presidio pattern recognizers + pandas
k-anonymity + vendored SDC risk math) — **$0.00 marginal cost per run, no API calls**. The offline
path uses `spacy.blank("nb")` (tokenizer only, bundled with spaCy). The optional Norwegian NER model
`nb_core_news_lg` is a **one-time ~568 MB download** (`uv run python -m spacy download nb_core_news_lg`)
and then runs locally on CPU — only needed for free-text name/location detection in live runs.

## Compute

Full pipeline run time (MacBook, cached ingest): ~45 seconds.
Full pipeline run time (first run, live API fetch): ~2 minutes.
XGBoost training (3 walk-forward folds): ~15 seconds.
