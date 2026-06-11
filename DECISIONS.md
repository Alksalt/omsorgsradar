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
