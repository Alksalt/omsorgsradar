---
name: magic-analyze
description: Analyser et hvilket som helst datasett-pekepunkt (URL, lokal fil, eller fritekst-spørsmål) gjennom omsorgsradar-pipelinen — klassifiser, skriv analyses/<slug>/analysis.toml, kjør ingest+profile-gaten, presenter realness-verdikten for eieren, og kjør resten på grønt. Use when the owner says "/magic-analyze <pointer>" or "analyser <datasett/spørsmål>".
---

# /magic-analyze <url | path | question>

## Hard rules (DECISIONS.md — not negotiable)

- You write **config and prose only**. Never computation code. A custom
  `analyses/<slug>/stages.py` is allowed only if the owner explicitly asks.
- Never state a number that is not in an artifact
  (`findings*.json` / `quality_profile.json` / `verification.json`).
- The profile gate verdict goes to the OWNER before analyze/report runs. Stop
  and present it — do not proceed on your own.
- Never bypass the host allowlist. Unknown host → ask the owner to add it to
  `workflow.toml [security].extra_allowed_hosts` (their call, not yours).

## Flow

1. **Classify the pointer:**
   `uv run python -c "from omsorgsradar.core.discovery import classify_pointer; print(classify_pointer('<pointer>'))"`
   - `url` + adapter → write the `[[sources]]` block directly
     (required fields per adapter: `docs/adapters.md`).
   - `url` + no adapter → switch to `/add-dataset` first.
   - `file` → csv adapter. Copy/download the file INTO `analyses/<slug>/`
     (path containment is engine-enforced); `[sources.provenance]`
     institution + url are mandatory for csv.
   - `question` → pick candidates from `docs/dataset-registry.md` (Tier 1
     first). If several fit, propose 1–3 to the owner before drafting.
2. **Draft** `analyses/<slug>/analysis.toml` (slug `^[a-z0-9-]+$`; ids
   `^[a-z0-9_]+$`). Stage list `["ingest", "profile"]` unless the analysis
   semantics are already defined — the default analyze stage is
   omsorgsradar-specific, and a new question usually needs an owner decision
   about metrics before any analyze stage exists.
3. **Validate:**
   `uv run python -m omsorgsradar.pipeline analyses/<slug> --validate-only`
   Fix exactly what the error names. Repeat until `OK:`.
4. **Gate run:**
   `uv run python -m omsorgsradar.pipeline analyses/<slug> --data-dir data/<slug> --reports-dir reports/<slug> --until profile`
   Read `data/<slug>/quality_profile.json`. Present per-dataset realness
   verdicts + row counts to the owner. **STOP.** (FAIL aborts the pipeline by
   itself; WARN/PASS is the owner's call.)
5. **On owner green:** rerun without `--until`. Link the report, figures and
   `runs/<run-id>/run.json`. Narrate findings from the artifacts only.

## Debugging

A failed run names its stage in `runs/<run-id>/run.json`; from there use the
`pipeline-stages` skill.
