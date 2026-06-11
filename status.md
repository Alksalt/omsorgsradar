# status — omsorgsradar

- **2026-06-11** — Project scaffolded (concept stage only, no code). Concept A chosen from 3 researched
  options (see `docs/CONCEPT.md`); research banked in wiki `growth/agentic-helsedata-portfolio-2026`.
  Purpose: public evidence for the outreach-CV claim «dataanalyse i Python/Pandas» + agentic-workflow
  showpiece for e-helse employers.
- **2026-06-11** — **P0–P5 built and shipped.** Full pipeline runs end-to-end on live SSB data.
  - P0: Ingest (SSB KOSTRA 12209 + population 07459 + projection 12880) + DuckDB + quality profile ✓
  - P1: Press-index analysis, 908 kommuner ranked, findings.json ✓
  - P2: Verifier («tool receipts»), 5/5 claims pass, planted-hallucination test green ✓
  - P3: Bokmål markdown report + 3 matplotlib figures ✓
  - P4: XGBoost walk-forward CV (3 folds) + SHAP. XGB MAE=2.08pp vs naive 2.28pp. TabPFN skipped (license). ✓
  - P5: README (EN + bokmål summary + Mermaid diagram), LIMITATIONS.md, COSTS.md ✓
  - Tests: 65/65 pass offline (`uv run pytest`)
  - Git: initialized, committed per phase
  - FHI NOKKEL: 404 on discovery endpoint — gracefully skipped, documented in `docs/api_drift.md`
- **Next:** Owner reviews → push to GitHub `Alksalt` + link from CV/profile README.
