# Kommunal Omsorgsradar

**Live report site:** https://alksalt.github.io/omsorgsradar/

**Agentic data-analysis pipeline over Norwegian open health data.**

Computes a per-municipality *press index* combining projected 80+ population growth to 2035 (per-municipality trend extrapolation with robustness guards — see LIMITATIONS) with current elder-care service coverage — ranking Norwegian municipalities by the likely severity of the demographic care squeeze. All analysis is deterministic, reproducible, and fully offline-runnable. An optional LLM narration step (Anthropic API) requires a key; the full pipeline runs without one.

---

## Bokmål sammendrag

Dette prosjektet beregner en **demografisk press-indeks** per norsk kommune for perioden frem mot 2035. Indeksen kombinerer forventet vekst i befolkningen 80 år og over med dagens dekning av kommunale hjemmetjenester (KOSTRA-data, SSB). Kommuner med rask demografisk vekst og lav tjenestedekning i dag rangeres høyt — det er disse som trenger tidligst planleggingsoppmerksomhet.

Data: SSB PxWebAPI v2 (KOSTRA tabell 12209 + befolkning tabell 07459). FHI NOKKEL var planlagt, men API-endepunktet er utilgjengelig (sist sjekket 2026-06-12). Alle data er åpne og krever ingen søknadsprosess. Rapporten er på bokmål. Kildekode og pipeline er på engelsk.

**Analysen er deskriptiv, ikke kausal.** Se [`LIMITATIONS.md`](LIMITATIONS.md).

---

## Live report site

Det offentlige nettstedet på https://alksalt.github.io/omsorgsradar/ publiserer bokmål-rapporter, figurer og et interaktivt marimo-utforskningsverktøy for alle analysene i repoet. Nettstedet er bygd av GitHub Actions fra committede artefakter — ingen rådata, ingen LLM-kall i CI.

The public site at https://alksalt.github.io/omsorgsradar/ publishes the bokmål reports, figures, and an interactive [marimo](https://marimo.io/) exploration (runs in-browser via WASM — no server, aggregate data inlined). Built by GitHub Actions from committed artifacts; no row-level or individual data.

See [`docs/site.md`](docs/site.md) for how to publish updated analyses.

---

## Architecture

The v2 engine is **config-driven and multi-analysis**: each analysis lives in `analyses/<name>/`
with its own `analysis.toml` (stages, sources, params). Config precedence:
`analysis.toml` > `workflow.toml` > code defaults.

```mermaid
flowchart TD
    CFG[workflow.toml\n+ analyses/<name>/analysis.toml] --> ENG
    A[SSB PxWebAPI v2\nKOSTRA / befolkning] --> ENG[Engine\ncore/config · registry\ncore/journal · adapters]
    B[Nordic adapters\nsotkanet · socialstyrelsen\nkolada · kuhr · csv] --> ENG
    ENG --> D[(DuckDB per analysis)]
    D --> E[profile\nData quality audit]
    D --> F[analyze\nPress index · findings JSON]
    F --> G[verify\nTool receipts — recomputes every claim]
    G --> H[report\nBokmål markdown + matplotlib figures]
    F --> I[ml\nXGBoost walk-forward CV\nSHAP importance · naive baseline]
    F --> AN[anonymize (opt.)\nk-anonymity + measured residual-risk receipt]
    H --> J[reports/<name>_rapport.md\n+ figures/]
    I --> J
    J --> SITE[omsorgsradar.site\nGitHub Pages]
```

**Key design choice:** the LLM *narrates*, never *calculates*. Every statistic is computed by deterministic Python code; the verifier module recomputes every claim in the narrative from the structured findings JSON. This "tool receipts" pattern is the portfolio differentiator.

---

## Pipeline phases

| Phase | Module | What it does |
|-------|--------|-------------|
| P0 Ingest | `ingest.py` | SSB + FHI fetch, kommune merger normalization, DuckDB persistence |
| P0 Profile | `profile.py` | Data quality audit → `data/quality_profile.json` |
| P1 Analysis | `analyze.py` | 80+ projections, coverage rates, press index → `data/findings.json` |
| P2 Verify | `verify.py` | Recomputes every claimed statistic ("tool receipts") |
| P3 Report | `report.py` + `maps.py` | Bokmål markdown + matplotlib figures + press-index choropleth (committed Kartverket-derived boundaries, no GIS deps) |
| P4 ML | `ml.py` | XGBoost walk-forward CV + SHAP + naive baseline |
| Anonymize (opt.) | `core/anonymize/` | Microdata → PII-redaction + k-anonymity + **measured residual-risk receipt** (EU WP216: singling-out / linkability / inference) |

The optional `anonymize` stage turns row-level microdata into a k-anonymized aggregate plus a
*measured-residual-risk* receipt — **anonymisering med målt restrisiko**, never "fully anonymous"
(pseudonymisering ≠ anonymisering; EDPB 01/2025). It is LLM-free engine code; row-level data never
enters model context. Demo: `analyses/brfss-demo/` (diabetes prevalence by stratum). See
[`docs/anonymize.md`](docs/anonymize.md).

**Execution modes.** The engine is LLM-free; the only optional LLM use (report narration) is routed by
`[endpoint].mode` — `subscription` (default, $0, the agentic shell narrates), `api`
(anthropic/openai/openrouter, keys from env only), or `local` (LM Studio/Ollama, nothing leaves the
machine — the privacy path for sensitive data). Provider, model, and placement are config, not code.
See [`docs/execution-modes.md`](docs/execution-modes.md) for the Normen privacy→placement mapping.

---

## Quick start

```bash
# Clone and install
git clone https://github.com/Alksalt/omsorgsradar
cd omsorgsradar
uv sync

# Run the default (omsorgsradar) analysis — fetches live SSB data, cached after first run
uv run python -m omsorgsradar.pipeline

# Run a specific analysis by name (config in analyses/<name>/analysis.toml)
uv run python -m omsorgsradar.pipeline analyses/nordisk-omsorg

# Run tests (fully offline, no API key needed)
uv run pytest

# Build the report site locally (from committed artifacts)
uv run python -m omsorgsradar.site --reports-dir reports --out site

# Optional: LLM narration (requires Anthropic API key; default mode is key-free)
ANTHROPIC_API_KEY=sk-... uv run python -m omsorgsradar.pipeline
```

Output files (per analysis, under `reports/<name>/`):
- `*_rapport.md` — bokmål report
- `figures/` — matplotlib figures
- `data/findings.json` — structured analysis findings (under `--data-dir`, default `data/`)
- `data/quality_profile.json` — data quality profile (under `--data-dir`, default `data/`)

---

## Data quality profile

Generated automatically by `profile.py` on the live SSB data.

### kostra_pleie
- Source: SSB KOSTRA table 12209
- Rows: 39,204
- Municipalities: 423 terminal kommune codes (after KLASS normalization)
- Year range: 2015–2025
- Variables: % of 80+ using home services, % with institutional care, cost per resident, FTE per user

### befolkning (population 80+)
- Source: SSB table 07459 — folkemengde etter alder
- Rows: 237,750
- Municipalities: 483 code rows (357 current kommuner + historical codes, kept but never ranked)
- Year range: 2017–2026
- Age groups: 80–104 år (1-year classes)

### Kommune merger handling
Mergers AND renumberings are handled via `kommune_mergers.py` — **regenerated from SSB KLASS
(klassifikasjon 131), never hand-written**: 468 one-to-one mappings covering the 2020 merger wave
and the 2024 county-reshuffle renumberings (e.g. Viken 30xx → 31xx/32xx/33xx), resolved
**transitively to terminal codes** (old Hvaler 0111 → 3011 → maps directly to 3110, so each
municipality has one contiguous time series). Genuine splits are excluded by design (1507 Ålesund
→ 1508 + 1580, 1850 Tysfjord, 5012 Snillfjord) — their pre-split history cannot be attributed
unambiguously. Only municipalities alive in the latest data year are ranked; an independent
structural check in the verifier enforces this on every run.

---

## Key findings (real data, regenerated 2026-06-12)

Based on KOSTRA 2025 + SSB population 2026, with the KLASS-corrected merger table and
per-municipality growth rates (earlier published numbers used a flawed hand-written merger
table and a uniform national growth rate — superseded by this run):

- **357 municipalities** ranked by press index (historical code rows excluded from ranking)
- **National 80+ population**: ~285,000 today → ~373,000 in 2035 (**+30.9%**) if each
  municipality's 2017–2026 trend continues. This is a trend extrapolation, not an official SSB
  projection — SSB's main alternative implies faster 80+ growth as the post-war cohorts age in
  (see LIMITATIONS)
- **Highest press**: Frogn, Vestby, Lørenskog, Hvaler — the Oslo-belt commuter municipalities,
  where the 80+ population is growing fastest (+68–117% by 2035 on current trends) while
  home-care coverage is among the lowest (~17–22% of 80+ receiving services). The squeeze is
  suburban, not (only) rural — a materially different planning picture than the uniform-growth
  v1 analysis suggested
- **ML**: XGBoost walk-forward CV MAE = **2.05 percentage points** vs naive persistence baseline
  2.27 pp — both barely beat carrying last year's value forward; prior-year coverage
  (`coverage_rate_lag1`) dominates SHAP importance. Municipal coverage is strongly
  autoregressive; the model's value is flagging deviations, not point prediction

---

## ML results summary

XGBoost walk-forward CV (3 expanding windows) predicting % of 80+ using home services (Y+1):

| Fold | Test year | XGB MAE | Naive MAE |
|------|-----------|---------|-----------|
| 1 | 2023 | 2.15 pp | 2.27 pp |
| 2 | 2024 | 2.00 pp | 2.24 pp |
| 3 | 2025 | 2.00 pp | 2.30 pp |
| **Mean** | — | **2.05 pp** | **2.27 pp** |

SHAP top feature: `coverage_rate_lag1` (prior-year rate dominates — kommunal dekning er sterkt autoregressiv). TabPFN-2.5 kan nå kjøres: registrer deg på [priorlabs.ai](https://ux.priorlabs.ai), sett `TABPFN_TOKEN=<din nøkkel>`, og kjør ml-steget på nytt.

**Framing: planning support tool, not clinical decision support.**

---

## API discovery notes

Documented in [`docs/api_drift.md`](docs/api_drift.md). Key findings:
- SSB table 13873 (municipality projections) is **not accessible to anonymous API callers**
  (confirmed 2026-06-12 against both PxWeb v0 and v2; a nonexistent table gives the same error
  class). Per-municipality growth therefore uses historical trend extrapolation from table 07459
  with robustness guards; national projections (table 12880) provide the fallback rate
- FHI NOKKEL indicator endpoint returns 404 (re-checked 2026-06-12; no working replacement
  found — `statistikk.fhi.no` is a frontend without a public REST API). FHI data is excluded
- KOSTRA 12209 region variable code is `KOKkommuneregion0000` (not `Region`) — discovered at runtime

---

## Limitations

See [`LIMITATIONS.md`](LIMITATIONS.md).

---

## Costs

See [`COSTS.md`](COSTS.md).

---

## Author

Oleksandr Altukhov — utdannet lege (master i medisin), agentic-AI engineer.
Built with [Claude Code](https://claude.ai/code) + Claude Agent SDK.
