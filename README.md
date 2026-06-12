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
    F --> G[verify\nTool receipts — narration fidelity\n+ independent DuckDB recompute]
    G --> H[report\nBokmål markdown + matplotlib figures]
    F --> I[ml\nXGBoost walk-forward CV\nSHAP importance · naive baseline]
    F --> AN[anonymize (opt.)\nk-anonymity + measured residual-risk receipt]
    H --> J[reports/<name>_rapport.md\n+ figures/]
    I --> J
    J --> SITE[omsorgsradar.site\nGitHub Pages]
```

**Key design choice:** the LLM *narrates*, never *calculates*. Every statistic is computed by deterministic Python code; the verifier runs two layers of checks. **(1) Narration-fidelity:** each numeric claim in the narrative is recomputed from the structured findings JSON, so a hallucinated number in the report is caught. **(2) Independent DB receipts:** the verifier reloads `findings.json` *from disk* and recomputes its key numbers *straight from the DuckDB `befolkning` table* — the national 80+ living-set total and a deterministic sample of per-municipality growth rates (top-10 ranked + every 25th) — with no call to the analysis code. A corrupted `findings.json` therefore fails verification and aborts the pipeline before any report is written. This "tool receipts" pattern is the portfolio differentiator.

---

## Pipeline phases

| Phase | Module | What it does |
|-------|--------|-------------|
| P0 Ingest | `ingest.py` | SSB + FHI fetch, kommune merger normalization, DuckDB persistence |
| P0 Profile | `profile.py` | Data quality audit → `data/quality_profile.json` |
| P1 Analysis | `analyze.py` | 80+ projections, coverage rates, press index → `data/findings.json` |
| P2 Verify | `verify.py` | Narration-fidelity recompute (claims vs findings) + independent DuckDB receipts (national 80+ total, sampled per-municipality growth, ranked⊆living) — corrupted `findings.json` aborts the run |
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

# Run a specific named analysis (config in analyses/<name>/analysis.toml)
uv run python -m omsorgsradar.pipeline analyses/nordisk-omsorg \
    --data-dir data/nordisk-omsorg --reports-dir reports/nordisk-omsorg

# Run tests (fully offline, no API key needed)
uv run pytest

# Build the report site locally (from committed artifacts)
# Note: --marimo produces the interactive explore page (same as CI)
uv run python -m omsorgsradar.site --reports-dir reports --out site \
    --marimo notebooks/explore_nordisk.py

# Optional: LLM narration (requires Anthropic API key; default mode is key-free)
ANTHROPIC_API_KEY=sk-... uv run python -m omsorgsradar.pipeline
```

**Note:** the default `uv run python -m omsorgsradar.pipeline` run re-fetches live SSB data and
regenerates the committed `data/*.json` artifacts. Commit them to update the site.

Output files (per named analysis):
- `reports/<name>/<name>_rapport.md` — bokmål report
- `reports/<name>/figures/` — matplotlib figures
- `data/<name>/findings.json` — structured analysis findings (under `--data-dir`)
- `data/<name>/quality_profile.json` — data quality profile (under `--data-dir`)

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
- Municipalities: 483 code rows (357 current kommuner + historical codes; historical codes are
  kept for provenance but never ranked, and 3 current kommuner without computable KOSTRA coverage
  are also unranked → **354 ranked**)
- Year range: 2017–2026
- Age groups: 80–104 år (1-year classes)

### Kommune merger handling
Mergers AND renumberings are handled via `kommune_mergers.py` — **regenerated from SSB KLASS
(klassifikasjon 131), never hand-written**: 468 one-to-one mappings covering the 2020 merger wave
and the 2024 county-reshuffle renumberings (e.g. Viken 30xx → 31xx/32xx/33xx), resolved
**transitively to terminal codes** (old Hvaler 0111 → 3011 → maps directly to 3110, so each
municipality has one contiguous time series). Genuine splits are excluded by design (1507 Ålesund
→ 1508 + 1580, 1850 Tysfjord, 5012 Snillfjord) — their pre-split history cannot be attributed
unambiguously. Only municipalities alive in the latest data year **and with a computable press
index** are ranked; independent DuckDB checks in the verifier (ranked⊆living, recomputed national
80+ total, sampled per-municipality growth) enforce this on every run.

---

## Key findings (real data, regenerated 2026-06-12)

Based on KOSTRA 2025 + SSB population 2026, with the KLASS-corrected merger table and
per-municipality growth rates (earlier published numbers used a flawed hand-written merger
table and a uniform national growth rate — superseded by this run):

- **354 municipalities** ranked by press index (historical code rows AND living municipalities
  without computable KOSTRA coverage excluded from ranking — only municipalities with a real
  press index are ranked)
- **National 80+ population**: ~285,000 today → ~373,000 in 2035 (**+31.1%**) if each
  municipality's 2017–2026 trend continues. This is a trend extrapolation, not an official SSB
  projection — **SSB's main alternative (table 13599, alternative MMM) implies ~46% growth for
  80+ over 2026→2035**, materially faster, as the post-war cohorts age in. The trend method is a
  lower planning bound; both numbers are reported (see LIMITATIONS)
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
  with robustness guards; SSB's **national main-alternative projection (table 13599, age 80+ ×
  MMM)** provides the fallback rate and the cited SSB-projection comparison (table 12880 was
  previously — wrongly — configured here; it is the macroeconomic-accounts table with no age
  dimension. Fixed 2026-06-12, see `docs/api_drift.md`)
- FHI NOKKEL indicator endpoint returns 404 (re-checked 2026-06-12; no working replacement
  found — `statistikk.fhi.no` is a frontend without a public REST API). FHI data is excluded
- KOSTRA 12209 region variable code is `KOKkommuneregion0000` (not `Region`) — discovered at runtime

---

## Creating a new analysis

Each analysis is a folder under `analyses/<name>/` containing at minimum an `analysis.toml`:

```toml
[analysis]
name = "my-analysis"
question = "Hvilken kommune…?"

[stages]
list = ["ingest", "profile", "analyze", "verify", "report"]

[[sources]]
id = "my_source"
adapter = "pxweb"
base_url = "https://data.ssb.no/api/v0/no/table"
table = "12209"
required = true

[params]
base_year = 2019
latest_year = 2023
top_n = 10
```

Add a `stages.py` in the same folder to override or extend core stages (see
`analyses/nordisk-omsorg/stages.py` for the pattern). For available adapters and required fields per
source type, see [`docs/adapters.md`](docs/adapters.md). To wire up a dataset interactively, use the
[`/add-dataset`](.claude/skills/add-dataset.md) skill.

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
