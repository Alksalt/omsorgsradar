# CLAUDE.md — omsorgsradar (Kommunal Omsorgsradar)

**Agentic data-analysis workflow over Norwegian open health data.** Premise: in 2026 you don't hand-write
analysis notebooks — you build an agentic pipeline (ingest → profile → analyze → **verify** → report) that
orchestrates pandas/numpy/matplotlib, with an optional honest ML layer. Subject: demografisk aldring vs
kommunal omsorgskapasitet mot 2035, per kommune.

**Why this project exists (distinct from the others here):** it is the public **evidence for the CV claim
«dataanalyse i Python/Pandas (datarensing, analyse, visualisering)»** (outreach CVs link GitHub; today no
pandas work is publicly visible) and the most *legible* artifact for a non-technical Norwegian e-helse
employer — every kommunehelsesjef recognizes the elder-care capacity question. Secondary: showcases the
agentic-workflow craft (verification/"tool receipts") that distinguishes 2026 portfolios from notebook-era
ones.

- Concept + datasets + ML spec: `docs/CONCEPT.md` (incl. rejected alternatives B/C)
- Hard constraints: `DECISIONS.md` · Live state: `status.md` · Build phases: `AGENTS.md`
- Research base: wiki `growth/agentic-helsedata-portfolio-2026` (sources for every design rule)
- Workspace rules apply (`../CLAUDE.md`): markdown scaffold until build explicitly started; `uv` only;
  owner is «utdannet lege (master i medisin)», never bare «lege»; no real patient data (this project uses
  only open aggregate statistics — SSB/FHI).

Status: **v1 built + shipped (P0–P5, 2026-06-11) · v2 G0 (engine + config) shipped 2026-06-11 ·
G1 (Nordic adapters + realness gates) shipped 2026-06-12 · G2 (nordisk-omsorg, first cross-country
instance) shipped 2026-06-12 · next: G3 (/magic-analyze + /add-dataset skills) per
`docs/specs/2026-06-11-v2-generalization-design.md`.**

## v2 engine (G0+)
Config: `workflow.toml` (models/endpoint/defaults) + `analyses/<name>/analysis.toml`
(stages/sources/params); precedence analysis > workflow > code. Engine:
`src/omsorgsradar/core/` (config, contracts, journal, registry, adapters) +
`src/omsorgsradar/stages.py` (default stages). Adapters: pxweb, sotkanet (FI),
socialstyrelsen (SE), kolada/RKA (SE elder-care — sdb has no äldreomsorg topic), kuhr (NO), csv —
`docs/adapters.md`; realness gates mandatory in profile. Variants = new instance
folder, never core edits. Run/extend/debug: see skill `pipeline-stages`.
Spec: `docs/specs/2026-06-11-v2-generalization-design.md`.
