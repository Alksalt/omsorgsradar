# Decisions — omsorgsradar

Hard constraints. Workspace-wide rules in `../CLAUDE.md` apply on top.

- Open aggregate data only (SSB PxWebAPI v2, FHI OpenAPI `NOKKEL`) — never application-/REK-gated sources.
- The LLM narrates, never calculates: every number is computed by code; a verifier agent recomputes every
  claimed statistic ("tool receipts") before a report ships; keep a test where the verifier catches a
  deliberately planted false statistic.
- Use `NOKKEL` (folkehelsestatistikk) naming — never the defunct Kommunehelsa/Norgeshelsa names.
- Kommune-merger lookup is mandatory in ingest; publish the data-quality profile in the README.
- ML: XGBoost + walk-forward CV + SHAP + naive-baseline comparison; TabPFN-2.5 as no-training baseline;
  no deep learning on this tabular data; framing is «planning support», never clinical decision support.
- Reports in bokmål; README in English with a bokmål summary section.
- Ship `LIMITATIONS.md` («deskriptivt, ikke kausalt») and `COSTS.md` (cost per full run) from v0.1.
- Python via `uv` only. Markdown scaffold until Oleksandr explicitly starts the build.
- v2 generalization lives in THIS repo (core engine + `analyses/` instances) — no separate framework repo.
- v2 first proof dataset: Nordic comparison — Sotkanet (FI), Kolada/RKA (SE; Socialstyrelsen-data — sdb-API-et mangler äldreomsorg, verifisert 2026-06-12) + SCB, SSB/KUHR (NO). Not NHS EPD/BRFSS first.
- Cross-country comparisons are within-country-normalized patterns only; never compare indicator levels across countries (different age cuts/definitions).
- Kommune-merger lookup is generated from SSB KLASS (classification 131), never hand-written; splits excluded and documented.
- Primary execution mode = subscription OAuth harnesses (Claude Code on Anthropic sub; Codex CLI on OpenAI sub).
  API-key (Anthropic/OpenAI/OpenRouter) and fully-local (LM Studio/Ollama via `ANTHROPIC_BASE_URL`) are
  config-swappable alternates; v1 ships a working local demo of ≥1 stage.
- Row-level data never enters model context: the LLM orchestrates code; only schemas/profiles/aggregates
  return. Enforced by hook, not instruction.
- Anonymize stage framing: «anonymisering med målt restrisiko» (Presidio + anonymeter receipts) — never
  claim "fully anonymous"; pseudonymisering ≠ anonymisering (EDPB 01/2025, Datatilsynet).
- Dataset realness gates (provenance/DOI, duplicate rate, missingness plausibility, distribution sanity,
  named institution) are mandatory in the profile stage before any analysis runs.
- Deterministic engine + agentic shell: skills (`/magic-analyze`, `/add-dataset`) write config and prose
  only — never computations. Engine runs LLM-free and reproducible.
- `/magic-analyze` accepts any dataset pointer (URL / path / free-text question), not only configured analyses.
- Config-swappable without code: per-stage models+endpoints, dataset sources, pipeline shape (stage list),
  report language/style. Precedence: analysis.toml > workflow.toml > code defaults; schema-validated at load.
- Pipeline variants are instances: `analyses/<name>/` (config + optional local `stages.py` shadowing core
  for that analysis only). Core is never edited for a variant; contracts + verify-gate still apply.
- v2 includes GitHub Pages report site + `/add-dataset` skill. Parked: planted-fault suite beyond the three
  gate tests, API drift watchdog.
