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
- **2026-06-11** — **v2 generalization researched + planned.** Deep research (6 questions: private-data
  architecture, 2026 stack, anonymization, big-real datasets, session memory, shared agent context) banked
  in wiki `tech/agentic-healthcare-analysis-workflow-2026`. Owner decisions: Nordic comparison first
  (Sotkanet+Socialstyrelsen+KUHR) · evolve this repo · subscription-OAuth primary execution + local demo.
  Plan: `docs/PLAN-v2-generalization.md` (G0–G5, ~5.5–6.5d). DECISIONS.md updated (7 new constraints).
  **Build awaits explicit go.**
- **2026-06-11** — **G0 (engine + config) shipped** on owner's go, subagent-driven (9 sonnet implementers,
  opus review panel). Engine extracted: `core/` (validated TOML config w/ precedence, artifact
  contracts+manifests, crash-safe run journal, stage registry + instance extension point, PxWeb adapter),
  registry-driven pipeline with hard verify-gate, data-read PreToolUse hook, `pipeline-stages` skill.
  Canonical configs: `workflow.toml` + `analyses/omsorgsradar/analysis.toml` (zero hardcoded source
  constants left in code). Review panel: correctness PASS, security PASS, integration BLOCK → 7 fixes
  applied (journal run-id precision, offline ingest dispatch coverage, gitignore `runs/`, doc/constant
  dedupe, security flags carried into spec for G3/G5). Tests: 65 → **114 green**. Smoke run: full
  pipeline on cached SSB data, verify 5/5 PASS, findings byte-identical to v1 — behavior preserved.
  **Next: G1 — Nordic adapters (sotkanet, socialstyrelsen, kuhr, csv) + realness gates; plan to be
  written on go.**
- **2026-06-11** — **v2 design finalized after owner brainstorm.** Additions: config system (per-stage
  models/endpoints, sources, stage list, language — analysis.toml > workflow.toml > defaults),
  `/magic-analyze <url|path|question>` (any dataset pointer), `/add-dataset` (agentic adapter authoring),
  instance extension point (`analyses/<name>/stages.py`, core never edited for variants), GitHub Pages
  report site. Canonical spec: `docs/specs/2026-06-11-v2-generalization-design.md` (G0–G6, ~7–8d).
  Parked: planted-fault suite beyond gate tests, API drift watchdog. **Spec awaits owner review →
  then detailed G0 implementation plan → build on explicit go.**
- **2026-06-12** — **G1 (Nordic adapters + realness gates) shipped.** Adapters:
  sotkanet (THL FI; API needs User-Agent), socialstyrelsen (SE statistikdatabas —
  live API deviates from its docs: no server-side filtering, string regionId,
  period-string ar, Swedish decimal commas; adapter built against reality), kuhr
  (helserefusjon NO, merger-normalized, known values live-verified), csv (local open
  data) — each with offline fixture + known-value test from captured API responses;
  shared sanitized JSON cache; NO/SE/FI geo harmonization (`core/geo.py`,
  `NO-1505`-style ids); adapter registry + startup source validation (id
  pattern-locked). Realness gates (5 Kaggle-triage checks) mandatory in profile —
  verdict published, FAIL aborts (fabricated-dataset gate test green at unit AND
  pipeline level). ⚠ Socialstyrelsen API has no äldreomsorg topic (verified live) —
  G2 Swedish elder-care via open-data CSV. Review panel (correctness/security/
  integration): 3× PASS → fixes applied (\Z cache-key anchor, nasta_sida host
  pinning + cross-host test, sotkanet full-year cache keys, csv-path containment
  carried into spec G3 gate). Tests: 114 → 184 (offline) + 3 live.
  **Next: G2 — `analyses/nordisk-omsorg` end-to-end.**
