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
- Execution modes (as built, G5): selected by `[endpoint].mode`; resolved in `core/endpoint.py` to a
  provider-agnostic LLM client. `subscription` ⇒ engine makes NO API calls (shell narrates, $0);
  `api` ⇒ anthropic (Messages) / openai+openrouter (Chat Completions); `local` ⇒ Anthropic- or
  OpenAI-compatible server. **API keys live in the environment ONLY — never in `workflow.toml` (rejected
  by `_reject_key_material`), never in run journals.** Bedrock `eu-central-1` / Vertex EU are documented
  placement targets for pseudonymised data (Normen mapping), NOT implemented providers — omsorgsradar
  uses open data only. See `docs/execution-modes.md`.
- Row-level data never enters model context: the LLM orchestrates code; only schemas/profiles/aggregates
  return. Enforced by hook, not instruction.
- Anonymize stage framing: «anonymisering med målt restrisiko» — never claim "fully anonymous";
  pseudonymisering ≠ anonymisering (EDPB 01/2025, Datatilsynet). Residual-risk receipts cover the three
  EU Art-29-WP216 criteria (singling-out / linkability / inference), computed by vendored SDC math in
  `core/anonymize/risk.py` (k-anonymity / l-diversity / QI-uniqueness; refs WP216 + sdcMicro + Giomi 2023).
  The `anonymeter` package is NOT used — it pins numpy<1.27 (uninstallable on this stack) and targets
  synthetic data, not k-anonymized real microdata. Row-level sources carry `row_level = true`: the engine
  refuses to run them without `anonymize` in the stage list, the realness gate skips its shape-dependent
  checks for them, and their raw path is hook-blocked from model context (`microdata/`).
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
- Machine-authored analysis.toml executes only behind the startup security gate: base_url host-allowlist (`ALLOWED_BASE_URL_HOSTS`; owner extends via workflow.toml `[security].extra_allowed_hosts`) + csv path containment. Skills (`/magic-analyze`, `/add-dataset`) never bypass it.
- `/magic-analyze` presents the ingest+profile realness verdict to the owner and stops; analyze/report run only on the owner's green.
