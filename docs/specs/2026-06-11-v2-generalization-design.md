# omsorgsradar v2 — generalized agentic helsedata-analysis workflow (design)

Approved direction 2026-06-11 (brainstorm with owner). Supersedes the phase sketch in
`docs/PLAN-v2-generalization.md` where they differ. Research base: wiki
`tech/agentic-healthcare-analysis-workflow-2026` + `growth/agentic-helsedata-portfolio-2026`.

## Goal

Evolve the shipped omsorgsradar pipeline (P0–P5, 65 tests green) into a **reusable, config-driven
agentic data-analysis workflow** for healthcare data: point it at a dataset (`/magic-analyze <pointer>`),
it runs find → ingest → profile → clean → analyze → model → verify → report with bokmål output,
publishes an employer-clickable report site, and stays trustworthy (tool receipts, realness gates,
row-level data never in model context).

## Architecture: deterministic engine + agentic shell

Two layers with a hard boundary:

- **Engine (plain Python, `uv`)** — runs any `analysis.toml` reproducibly with zero LLM involvement
  in computation. Anyone can `uv run python -m omsorgsradar.pipeline analyses/nordisk-omsorg` and get
  identical numbers. All statistics are computed by code and re-verified by the verifier stage.
- **Agentic shell (Claude Code skills/hooks/subagents)** — `/magic-analyze` and `/add-dataset` do
  discovery, config authoring, and narration. The shell writes *config and prose*, never computations.
  Enforced by: verify-gate (code), data-read hook (harness), and stage contracts (schema validation).

Rejected alternatives: fully agentic orchestration (non-reproducible, breaks tool receipts);
agent-teams/Workflow orchestration (experimental, no benefit for a linear pipeline).

## Config system

Two files, JSON-schema-validated at load (fail fast on typos/unknown adapters), layered precedence
**analysis.toml > workflow.toml > code defaults**:

```toml
# workflow.toml (repo root) — HOW the workflow runs
[models]                       # per-stage model selection — the "modernise in 2027" knob
profile = "claude-sonnet-4-6"
report  = "claude-fable-5"
verify  = "none"               # verifier is pure code; "none" is explicit and validated

[endpoint]
mode = "subscription"          # subscription | api | local
# mode-specific blocks:
[endpoint.api]    provider = "anthropic"   # anthropic | openai | openrouter
[endpoint.local]  base_url = "http://localhost:1234"   # LM Studio Anthropic-compatible

[defaults]
language = "nb"
figure_style = "seaborn-v0_8-whitegrid"
runs_dir = "runs"
```

```toml
# analyses/<name>/analysis.toml — WHAT one analysis is
[analysis]
name = "nordisk-omsorg"
question = "Hvilke kommuner får den hardeste skvisen — og står Norge bedre enn Sverige/Finland?"
language = "nb"                # overrides workflow default

[stages]                       # pipeline shape per analysis
list = ["ingest", "profile", "analyze", "verify", "report", "ml"]

[[sources]]                    # dataset sources — new dataset = new block, not new code
adapter = "pxweb"              # pxweb | sotkanet | socialstyrelsen | kuhr | csv
base_url = "https://data.ssb.no/api/v0/no/table"
table = "12209"
[sources.var_map]
hjemmetjeneste_andel = "KOShjtj80aarover0001"

[params]                       # analysis-specific knobs
projection_year = 2035
```

Validation rules: unknown stage name, unknown adapter, or missing required source fields abort at
startup with the offending key in the error. `[models]`/`[endpoint]` feed the agentic shell and the
report stage's optional LLM renderer; the engine itself runs LLM-free.

## Engine: stage registry + instance extension point

- `core/registry.py` maps stage names → callables with a uniform signature:
  `stage(ctx: StageContext) -> list[ArtifactRef]` where `StageContext` carries config, artifact paths,
  journal handle.
- The pipeline executes `stages.list` in order. **Hard rule (not configurable):** if `report` is in the
  list, `verify` runs before it and a FAIL verdict aborts with `PipelineGateError`.
- **Instance extension point (owner requirement, 2026-06-11):** if `analyses/<name>/stages.py` exists,
  the pipeline imports it and calls `register(registry)` before resolution. Analysis-local
  registrations shadow core stages *for that analysis only*. Custom stages must emit schema-valid
  artifacts (same contracts) — a broken experiment fails inside its instance; core and sibling
  analyses are untouched. "Build me a variant" = new instance folder, purely additive on main.
- Artifacts: every stage writes its outputs + a `*.manifest.json` (sha256, schema version, producer,
  upstream inputs). Stage boundaries validate payloads against JSON schemas in `core/contracts.py`.
- Run journal: `runs/<run-id>/run.json` — stages, artifact paths+hashes, durations, costs, verifier
  verdict, config snapshot. File-based memory only (no vector DB — research verdict).

## Adapters

`core/adapters/` — `DatasetAdapter` protocol: `source_id`, `fetch(source_cfg) -> pd.DataFrame`, plus
shared caching (raw JSON to `data/cache/`). v2 ships: `pxweb` (extracted from existing ingest, also
covers FOHM/DST later), `sotkanet`, `socialstyrelsen`, `kuhr`, `csv` (local files/Kaggle downloads).
Each adapter: offline fixture + known-value test. Profile stage gains **realness gates** (provenance,
duplicate rate >1%, missingness plausibility, distribution sanity, named institution) — mandatory
before analysis, verdict published in the quality profile.

## Agentic shell

### `/magic-analyze <url | path | question>`
1. **Classify pointer**: known-adapter URL → map directly; CSV/local path → csv adapter; free-text
   question → dataset discovery against the research-ranked source registry (Sotkanet,
   Socialstyrelsen, SSB, KUHR, NHS EPD, BRFSS…, in `docs/dataset-registry.md`).
2. **Draft** `analyses/<slug>/analysis.toml` (and nothing else — no code).
3. **Gate**: run ingest+profile, present the realness/quality verdict to the owner.
4. **Run** the remaining stages on green; link report, figures, run journal; narrate findings from
   `findings.json` only (numbers come from artifacts, never from model memory).

Security gate (review flag 2026-06-11, extended by G1 panel 2026-06-12): before any
machine-authored analysis.toml is executed, tighten core/config.py — `base_url`
pattern-locked to the known data hosts. Landed in G1 already: cache keys sanitized
(`core/adapters/cache.py`, rejects `/`, `..`, newlines), source ids locked to
`^[a-z0-9_]+$`, socialstyrelsen `nasta_sida` pagination host-pinned. Still G3-blocking:
csv adapter must resolve `path` and reject anything outside the analysis dir
(absolute/`../` paths are owner-trust-only in G1 — `csvfile.py` docstring).

### `/add-dataset <api-url>`
1. Inspect the API (one sample call, schema sniff: JSON-stat2? PxWeb? CKAN? plain JSON/CSV?).
2. Closest existing adapter → emit a `[[sources]]` block. New shape → write `core/adapters/<new>.py`
   + offline fixture + known-value test, run it.
3. Output: commit-ready diff. Never edits existing adapters' behavior.

### Hooks (harness gates)
- `block_raw_data_reads` (PreToolUse on Read/Grep): denies model-context access to `data/cache/**`,
  `*.duckdb`, and any path tagged row-level in config — aggregates/artifacts only.
- Verify-gate lives in engine code (above); the hook layer is for context hygiene, not math.

## Report site (GitHub Pages)

Report stage additionally renders `site/` (static HTML from bokmål markdown + figures + quality
profile + run metadata; Jinja2 template, no JS framework). GitHub Action deploys `site/` to Pages on
push to the default branch. One link for employers; updated by every published run.

## Anonymize stage (optional, config-listed)

Presidio (Norwegian: spaCy `nb_core_news_lg` + custom recognizers for fødselsnummer etc.) +
k-threshold aggregation + **anonymeter** receipts (singling out / linkability / inference) + an
identifiability-assessment artifact. Framing everywhere: «anonymisering med målt restrisiko», never
"fully anonymous". Demo analysis: CDC BRFSS microdata. Planted-PII test required.

**As built (G4, 2026-06-12):** anonymeter the *package* is uninstallable on this stack (pins
numpy<1.27; repo is numpy 2.4) and targets synthetic data, not k-anonymized real microdata — so the
three WP216 criteria it measures are **vendored** with standard SDC math in `core/anonymize/risk.py`
(singling-out ← k-anonymity / prosecutor risk; linkability ← QI-uniqueness; inference ← l-diversity +
attacker advantage). Identifiability receipt → `data/identifiability.json` (schema-validated, gate
aborts on FAIL after the verdict is on disk). spaCy NER is optional/live-only; the offline path uses
`spacy.blank("nb")` (no 568 MB download). Row-level sources are tagged `row_level = true` (startup
check forces `anonymize`; realness skips shape-checks; `microdata/` is hook-blocked). See
`docs/anonymize.md`. Demo: `analyses/brfss-demo/` (synthetic BRFSS-shaped fixture, real fetch documented).

## Execution modes

The shell inherits harness auth: **subscription OAuth primary** (Claude Code on Anthropic sub;
Codex CLI parity via AGENTS.md), API-key (anthropic/openai/openrouter), local (LM Studio
`ANTHROPIC_BASE_URL`, Devstral-Small-2-class model) — selected by `[endpoint].mode`. v2 ships a
working local demo of ≥1 stage. Privacy mapping (open→cloud, pseudonymized→EU-hosted Bedrock
eu-central-1/Vertex EU, sensitive→local) + Normen skytjeneste-veileder reference in docs.

Security gate (review flag 2026-06-11): when [endpoint.api] gains fields, set
additionalProperties: false in WORKFLOW_SCHEMA and reject key-material field names
(api_key/key/token/secret) — keys live in env, never in TOML, never in run journals.

**As built (G5, 2026-06-12):** `[endpoint].mode` resolves in `core/endpoint.py` to a provider-agnostic
`LLMClient` (or `None` for subscription, where the engine makes no calls and the shell narrates). Providers:
anthropic (Messages), openai + openrouter (Chat Completions), local (Anthropic- or OpenAI-compatible via
`[endpoint.local].api`). Security gate landed: `additionalProperties:false` on the endpoint blocks +
`_reject_key_material` (recursive) refuses any credential-named key in workflow.toml. The only LLM
touchpoint is `report.render_llm`; the engine remains LLM-free. Bedrock/Vertex EU = documented placement
targets, not implemented providers. Local demo verified offline (`tests/test_report_modes.py`).
See `docs/execution-modes.md`.

## Testing strategy

- Core suite (65 existing tests stay green through G0 refactor) + contract tests per schema.
- Per-adapter: offline fixture + known-value test; live tests marked `live`.
- Gate tests: planted hallucinated statistic (exists) caught at pipeline level; realness gates catch
  a synthetic fabricated dataset; planted-PII caught by anonymize (G4).
- Integration: fixture-driven full pipeline run per analysis (no network, `use_llm=False`).
- Skills are tested by their underlying engine commands; skill markdown stays thin.

## Phases (re-cut 2026-06-11)

| Phase | Scope | ~Est |
|---|---|---|
| G0 | Engine + config: core/ extraction, workflow.toml + analysis.toml + schema validation, stage registry + extension point, manifests, journal, verify-gate in pipeline, data-read hook, stage skills scaffold | 1.5d |
| G1 | Adapters: sotkanet, socialstyrelsen, kuhr, csv (+pxweb extracted in G0); realness gates in profile; geo harmonization NO/SE/FI | 1–1.5d |
| G2 | `analyses/nordisk-omsorg` end-to-end + bokmål report + planted-hallucination test for new analysis | 1d |
| G3 | `/magic-analyze` + `/add-dataset` skills + dataset registry doc | 1–1.5d |
| G4 | Anonymize stage (Presidio nb + anonymeter) + BRFSS demo + planted-PII test | 1d |
| G5 | Execution modes (subscription/api/local) + local demo + Normen mapping | 0.5–1d |
| G6 | marimo artifacts + GitHub Pages site + README/LIMITATIONS/COSTS + push | 1d |

Total ~7–8 agent-days. Each phase: implement → blast-radius → correctness/security/integration
review → commit on green (`uv run pytest`). Fan-outs ≤10 agents.

## Out of scope v2

NHS EPD / CMS Part D analyses (adapter-ready, not built) · MIMIC-IV (path documented only) ·
planted-fault suite beyond the three gate tests · API drift watchdog · agent teams · deep learning ·
EHDS (secondary use starts 2029).
