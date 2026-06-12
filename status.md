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
- **2026-06-12** — **G2 Tasks 5–8 shipped.** `analyses/nordisk-omsorg/stages.py` complete:
  `squeeze_table` (within-country z-normalize + rank), `findings_from_tables` (nordic_findings schema),
  country table builders for NO/SE/FI (`_no_table` filters pre-merger NaN rows, `_se_table` merges
  SCB population with Kolada hemtjanst, `_fi_table` reconstructs 75+ elderly from sotkanet share×pop),
  `kuhr_context` (KUHR sidecar for verify), `stage_analyze_nordisk` (artifacts + manifests),
  `stage_verify_nordisk` (independent inline recompute — does NOT call `findings_from_tables`; planted-
  hallucination test green: coverage_median+7.7 AND geo_id spoof both caught in one run),
  `stage_report_nordisk` (bokmål markdown + 3 matplotlib figures; refuses without green verification),
  `register()` (shadows analyze/verify/report). Tests: 197 → **208 green**. Commit: 0459b02.
  **Next: G2 mid-review (opus panel, Task 11) + G2 Phase 4 (Tasks 9–10: offline e2e + live run + docs).**
- **2026-06-12** — **G2 (nordisk-omsorg) shipped.** First cross-country instance:
  `analyses/nordisk-omsorg/` (NO/SE/FI aldring vs. hjemmetjenestedekning per kommune,
  within-country z-skvis; verify = 168 uavhengige kontroller, planted-hallucination-test
  grønn). Core gains: pxweb `use_codes`/`label_columns`, kolada-adapter (SE — sdb-API-et
  mangler äldreomsorg), `contracts.register_schema`, pipeline `--data-dir`/`--reports-dir`.
  **Kritisk funn fra review-panelet: håndskrevet kommune-merger-tabell hadde 1504→1506-feil
  (gamle Ålesund → Molde) som blåste opp NO-vekst til 246 % — tabellen er regenerert fra
  SSB KLASS (358 entries, splitter ekskludert), maks 80+-vekst nå 43,5 % (Bykle).** Bokmål
  rapport + 3 figurer publisert fra live-kjøring (`reports/nordisk-omsorg/`). Tests: 184 → 218
  offline + 3 live. **Next: G3 — /magic-analyze + /add-dataset skills (security gate:
  base_url-allowlist + csv-path-containment er harde forutsetninger — se spec).**
- **2026-06-12** — **G2 panel close-out.** Correctness/security/integration: 3× PASS.
  Fixes landet: kolada `next_url` host-pinnet (+ cross-host-test, paritet med G1-standarden),
  `repr()`-quoting i regen-skriptet, v1-manifestenes absolutte stier skrubbet (var allerede
  offentlige — lav sensitivitet), ærlig `n_dropped`-formulering i rapporten (historiske
  kommunenummer ≠ manglende data) + v1-forbehold i LIMITATIONS.md. Live-rapport regenerert
  (168/168 kontroller). Tester: 219 offline + 4 live.
- **2026-06-12** — **G3 (agentic shell) shipped.** `/magic-analyze` (klassifiser →
  utkast analysis.toml → `--validate-only` → `--until profile`-gate → eier-verdikt →
  full kjøring) + `/add-dataset` (én prøvespørring → sources-blokk eller ny adapter
  etter G1-mønsteret) som tynne skills over testbare motor-kommandoer. Motor:
  `ALLOWED_BASE_URL_HOSTS`-allowlist håndhevet ved oppstart (+ workflow.toml
  `[security].extra_allowed_hosts`), csv-path-containment, `--validate-only`/`--until`,
  `core/discovery.py` pointer-klassifisering. `docs/dataset-registry.md` (Tier 1
  verifisert / Tier 2 kandidater). Tests: 219 → 247 offline + 4 live. **Next: G4 — anonymize
  stage (Presidio nb + anonymeter) + BRFSS-demo + planted-PII-test.**
- **2026-06-12** — **G3 panel close-out.** Correctness/security/integration: 3× PASS
  (security-vektet — gaten er hele poenget). Bypass-forsøk alle blokkert: host-lookalikes,
  userinfo/port-smugling, localhost-SSRF, paginerings-omdirigering, csv-symlink/`../`-escape,
  extra_allowed_hosts kan ikke smugles via analysis.toml. Defense-in-depth-fikser landet:
  host-sjekk foldet inn i `make_adapter` (ikke bare run_pipeline), `CsvAdapter` krever nå
  base_dir, port strippet via hostname. Tester: 247 offline + 4 live.
