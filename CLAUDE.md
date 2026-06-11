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

Status: **scaffold only (2026-06-11). Do not start the build without Oleksandr's explicit go.**
