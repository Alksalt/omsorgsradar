# AGENTS.md — omsorgsradar build phases

Same brief as CLAUDE.md for codex. Phases run only after explicit go. Sonnet implements, Opus reviews
(workspace model policy).

- **P0 — Ingest + profile.** `uv` project; SSB PxWebAPI v2 (tabell 12209, `pleie`, befolkning +
  framskrivinger) + FHI `NOKKEL` clients; kommune-merger lookup; DuckDB persistence; data-quality
  profile (JSON + README section). Tests on the lookup + a known-value fetch.
- **P1 — Analysis.** Elderly-share projections 2025–2035, coverage rates, pressure index; all findings to
  structured JSON.
- **P2 — Verifier.** Recompute-every-claim layer ("tool receipts"); planted-hallucination test green.
- **P3 — Report.** Bokmål markdown + matplotlib figures + kommune map; «deskriptivt, ikke kausalt» block.
- **P4 — ML (optional).** XGBoost walk-forward (3 windows) + SHAP + naive baseline + TabPFN-2.5 baseline.
- **P5 — Package + publish.** README (Mermaid, bokmål summary), LIMITATIONS.md, COSTS.md, public repo
  under `Alksalt`, link from CV/profile README.

## v2 — generalization (designed 2026-06-11, awaiting explicit go)

Canonical design: `docs/specs/2026-06-11-v2-generalization-design.md` (supersedes the sketch in
`docs/PLAN-v2-generalization.md`). Research: wiki `tech/agentic-healthcare-analysis-workflow-2026`.
Architecture: deterministic engine (config-driven, LLM-free computation) + agentic shell (skills/hooks).

- **G0 — Engine + config.** `core/` extraction; workflow.toml + analysis.toml + schema validation; stage
  registry + instance extension point (`analyses/<name>/stages.py`); manifests; run journal; verify-gate
  wired into pipeline; data-read hook; stage skills scaffold. 65 tests stay green.
- **G1 — Adapters.** sotkanet + socialstyrelsen + kuhr + csv (pxweb extracted in G0); realness gates in
  profile; NO/SE/FI geo harmonization.
- **G2 — Nordic analysis.** `analyses/nordisk-omsorg/` end-to-end, bokmål report, planted-hallucination test.
- **G3 — Agentic shell.** `/magic-analyze` (any dataset pointer) + `/add-dataset` skills + dataset registry.
- **G4 — Anonymize stage.** Presidio (nb) + vendored WP216 SDC math (anonymeter rejected: pins
  numpy<1.27, uninstallable on this stack; targets synthetic data, not k-anonymized microdata)
  + identifiability artifact; BRFSS demo; planted-PII test.
- **G5 — Execution modes.** Subscription OAuth primary, API-key, local (LM Studio via
  `[endpoint.local].base_url` in workflow.toml) + working local demo; Normen mapping.
- **G6 — marimo + Pages + package.** marimo artifacts, GitHub Pages report site, README/LIMITATIONS/COSTS, push.
