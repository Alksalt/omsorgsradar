# PLAN v2 — generalize omsorgsradar into an agentic helsedata-analysis workflow

> **Superseded 2026-06-11 (same day):** after owner brainstorm, the canonical design is
> `docs/specs/2026-06-11-v2-generalization-design.md` (adds: config system with per-stage
> models/endpoints, `/magic-analyze` with any-pointer input, `/add-dataset`, instance extension point,
> GitHub Pages site; phases re-cut G0–G6, ~7–8d). This file is kept as the research-to-decision record.

Decided 2026-06-11 (owner choices: Nordic comparison first · evolve this repo · subscription-OAuth
primary execution + local demo). Research base: wiki `tech/agentic-healthcare-analysis-workflow-2026`
(18 adversarially verified claims + 3 gap-fill agents) on top of `growth/agentic-helsedata-portfolio-2026`.
Build starts only on explicit go. Estimated ~5.5–6.5 agent-days.

## Target architecture

```
omsorgsradar/
├── core/                      # the reusable engine
│   ├── stages/                # ingest → profile → clean → analyze → model → verify → report
│   ├── adapters/              # PxWebV2 (SSB/FOHM/DST) · Sotkanet REST · Socialstyrelsen REST ·
│   │                          # KUHR helserefusjon · CSV/XPT · (CKAN-SQL stub for NHS EPD later)
│   ├── contracts/             # JSON-schema per stage boundary (artifact manifests)
│   └── journal.py             # runs/<ts>/run.json — data versions, costs, verifier verdicts
├── analyses/
│   ├── omsorgsradar/          # existing P0–P5 pipeline, re-expressed as the first analysis config
│   └── nordisk-omsorg/        # v2 proof: NO vs SE vs FI elder-care pressure
├── .claude/
│   ├── skills/                # per-stage playbooks (ingest, profile, analyze, verify, report, anonymize)
│   ├── hooks/                 # verify-gate · data-never-in-context guard
│   └── agents/                # stage subagents (profiler, verifier, reporter)
└── runs/                      # journaled executions (gitignored except samples)
```

Architectural rules (from DECISIONS.md):
- **LLM narrates and orchestrates; code computes; row-level data never enters model context.** Stages
  exchange artifacts (parquet/JSON/DuckDB) by path — artifacts-plus-references, no payloads through
  the orchestrator. Subagents return ≤2K-token summaries.
- **Hooks are the gates** (CLAUDE.md is context, not enforcement): report stage is blocked until the
  verifier artifact is green; raw-data reads into context are blocked above a snippet threshold.
- Memory: CLAUDE.md (facts) + status.md/DECISIONS.md (committed state) + run journal. No vector DB.

## Phases

### G0 — Engine extraction (~1d)
Refactor existing src into `core/` + `analyses/omsorgsradar/` with zero behavior change: stage
contracts (JSON-schema manifests), run journal, adapter interface (PxWebV2 adapter extracted from
existing SSB client). Hooks: verify-gate (Stop/PreToolUse) + data-in-context guard. Skills scaffolded
per stage. Gate: all 65 existing tests green + contract tests + planted-hallucination test still caught.

### G1 — Nordic adapters + ingest (~1–1.5d)
New adapters: Sotkanet REST (kunta-level, JSON-stat/CSV, CC BY 4.0) · Socialstyrelsen statistikdatabas
REST (äldreomsorg + kommunal hälso- och sjukvård 2007–2025) · KUHR/helserefusjon open API (NO kommune
primary-care activity, 2015–). Kommune/kommun/kunta geo-harmonization table (incl. SE/FI municipality
reforms — same trap as norske sammenslåinger). Profile stage gains **realness gates** (duplicate rate,
missingness plausibility, provenance, distribution sanity, named institution) emitted in the quality
profile. Gate: known-value fetch tests per adapter, offline fixtures.

### G2 — Nordic analysis + report (~1d)
`analyses/nordisk-omsorg/`: elder-share projection vs care-capacity coverage, comparable pressure
metric across NO/SE/FI where definitions allow (definition drift documented per country — this is the
honest-limitations showpiece). Bokmål report + figures; verifier recomputes every claimed statistic
(tool receipts) + a new planted-hallucination test for this analysis. Gate: verifier 100% green.

### G3 — Anonymize stage (~1d)
`core/stages/anonymize`: Presidio analyzer/anonymizer with Norwegian config (spaCy `nb_core_news_lg`
+ custom recognizers: fødselsnummer, norske navn/adresser) + k-threshold aggregation + **anonymeter**
receipts (singling out / linkability / inference — the Datatilsynet/WP29 triple) + an
identifiability-assessment artifact (CJEU C-413/23 P documentation requirement). Demo on CDC BRFSS
microdata (real, open, person-level). LIMITATIONS.md: «anonymisering med målt restrisiko», never
"fully anonymous"; Presidio's own no-guarantee disclaimer quoted. Gate: planted-PII test (anonymize
stage catches a deliberately injected fødselsnummer + quasi-identifier combo).

### G4 — Execution modes (~0.5–1d)
The workflow is Claude Code project config (skills/hooks/subagents over plain `uv` Python), so it
inherits whatever auth the harness session has:
1. **Subscription OAuth (primary)** — Claude Code on Anthropic sub (interactive + headless `claude -p`);
   Codex CLI on OpenAI sub via AGENTS.md parity. $0 marginal token cost.
2. **API-key** — Anthropic/OpenAI/OpenRouter for unattended/CI runs.
3. **Local** — LM Studio Anthropic-compatible endpoint + `ANTHROPIC_BASE_URL` (or Ollama + router),
   Devstral Small 2 / Qwen3-Coder-class model; working demo of ≥1 stage fully offline.
Docs: 3-mode privacy table (open → cloud; pseudonymized → EU-hosted Bedrock eu-central-1/Vertex EU;
sensitive → local) + Normen skytjeneste-veileder mapping. COSTS.md gains a per-mode table. Gate: each
mode executes the profile stage on a fixture.

### G5 — marimo + ML generalization + package (~1d)
marimo notebook artifact per analysis (pure .py, deterministic DAG — replaces "static notebook" with
agent-authored, re-runnable artifact). ML layer becomes a configurable stage (XGBoost walk-forward +
SHAP + naive baseline, reused by both analyses). README rewrite: framework + flagship analysis story,
Mermaid, bokmål summary; LIMITATIONS/COSTS updated; push to `Alksalt`.

## Out of scope v2 (parked)
NHS EPD + CMS Part D tracks (adapter stub only) · MIMIC-IV (credentialing path documented, not built) ·
agent teams (experimental) · DL (never on this data) · EHDS (secondary use starts 2029).

## Review protocol
Workspace policy: sonnet implements, opus reviews. Per phase: implement → blast-radius → correctness +
security + integration reviewers → commit on green (`uv run pytest` gate). Fan-outs stay small
(owner budget rule: ≤10 agents unless explicitly raised).
