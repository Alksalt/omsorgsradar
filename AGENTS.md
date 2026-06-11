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
