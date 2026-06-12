# COSTS.md — Kommunal Omsorgsradar

## LLM narration cost (optional path)

The full pipeline has two rendering paths. The key-free template path has zero LLM cost.

### Key-free template path (default)
- **Cost: $0.00 per run**
- Produces the same structured report from the same findings JSON using a deterministic template renderer.
- All analysis, press index, figures, and verifier are unaffected.

### LLM narration path (optional, requires `ANTHROPIC_API_KEY`)

Measured token estimate for a typical report narration call:

| Item | Tokens | Price (claude-sonnet-4-5) |
|------|--------|--------------------------|
| System + findings JSON prompt | ~2,500 input | $0.0075 |
| Bokmål narrative output | ~800 output | $0.012 |
| **Total per run** | ~3,300 | **~$0.02** |

Pricing based on claude-sonnet-4-5: $3.00 / MTok input, $15.00 / MTok output (as of 2026-06-11).

**Estimated cost per full pipeline run with LLM narration: ~$0.02 USD.**

If run daily for one year: ~$7/year. Negligible.

### TabPFN-2.5

TabPFN-2.5 was not run in v0.1 because it requires an interactive license acceptance via [priorlabs.ai](https://ux.priorlabs.ai). Once a `TABPFN_TOKEN` is set, TabPFN inference is free for research use (as of 2026). Local inference cost is compute only (CPU, ~30 seconds on ~3,000 rows).

### SSB / FHI API calls

Both SSB PxWebAPI v2 and FHI NOKKEL are **free, no authentication required** (CC BY 4.0 / open government data). The pipeline caches responses to `data/cache/` after the first run — subsequent runs cost zero API calls for ingest.

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
