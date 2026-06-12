# Anonymize stage — anonymisering med målt restrisiko

The `anonymize` stage takes row-level microdata and releases a **k-anonymized
aggregate together with a measured residual-risk receipt**. It is engine code
(LLM-free, deterministic) and sits after `profile`, before `analyze`. Framing
everywhere: *anonymisering med målt restrisiko* — never "fully anonymous";
**pseudonymisering ≠ anonymisering** (EDPB 01/2025, Datatilsynet). Residual risk
is *målt, ikke eliminert*.

## What it does

1. **PII redaction** (`core/anonymize/pii.py`) — Microsoft Presidio with custom
   Norwegian recognizers: fødselsnummer / D-nummer (11-digit mod-11 checksum),
   telefonnummer, kontonummer. Detected spans are replaced with
   `<ENTITY_TYPE>`. Free-text name/location NER (spaCy `nb_core_news_lg`) is
   **optional and live-only** — the offline path uses `spacy.blank("nb")`
   (tokenizer only, no 568 MB model download), so the test suite stays fast and
   network-free.
2. **k-anonymity** (`core/anonymize/kanon.py`) — config-driven generalization of
   the quasi-identifiers (numeric → labelled bands, categorical → coarser map; no
   hardcoded hierarchies) + suppression of every equivalence class smaller than
   `k`. The released frame guarantees `min_class_size ≥ k`.
3. **Residual-risk receipt** (`core/anonymize/risk.py`) → `data/identifiability.json`.

## The receipt: the three EU Art-29-WP216 criteria

WP216 (Article 29 WP, Opinion 05/2014) names three risks effective
anonymisation must control. We measure each with standard Statistical Disclosure
Control quantities (refs: WP216 · sdcMicro, Templ et al. · Giomi et al. 2023):

| WP216 criterion | SDC measure | Receipt fields | FAIL when |
|---|---|---|---|
| **Singling out** | k-anonymity / prosecutor risk | `min_class_size`, `prosecutor_risk`, `share_below_k` | `min_class_size < k` |
| **Linkability** | QI-uniqueness (pre-suppression) | `unique_qi_share_pre_suppression` | share `> threshold + 0.05` |
| **Inference** | l-diversity + attacker advantage | `min_l_diversity`, `max_attacker_adv`, `mean_attacker_adv` | `l < l_min` (no advantage) or `adv > threshold + 0.15` |

Attacker advantage for an equivalence class `G` on sensitive attribute `S`:
`adv(G) = P(S=s*|G) − P(S=s*)` where `s* = argmax P(S=s|G)` — the knowledge gain
over a population-marginal guess. Overall verdict = worst of the three
(`FAIL > WARN > PASS`). The gate writes the verdict to disk **before** a FAIL
aborts the pipeline, so the receipt is always inspectable.

### Why not the `anonymeter` package?

`anonymeter` pins `numpy>=1.22,<1.27`; this repo runs numpy 2.4 → it cannot be
installed (`uv pip compile` proves it unsatisfiable). It also targets *synthetic*
data (attacker NN-attacks comparing synthetic vs original+control), whereas this
stage releases *k-anonymized real microdata*, for which SDC re-identification
risk is the correct framework. We therefore vendor the three criteria it measures
rather than depend on an abandoned, mis-fit package. Same receipts, reproducible,
correct tool.

## Config (`[params.anonymize]`)

```toml
[params.anonymize]
source = "brfss"                         # source id holding the microdata
text_columns = ["notes"]                 # columns scanned for PII redaction
quasi_identifiers = ["state", "age", "sex"]
sensitive = "diabetes"
k = 10
# spacy_model = "nb_core_news_lg"        # optional: live NER over text_columns
[params.anonymize.generalize.age]
bins = [18, 30, 45, 60, 75, 200]
labels = ["18-29", "30-44", "45-59", "60-74", "75+"]
[params.anonymize.thresholds]
l_min = 2
inference = 0.5
linkability = 0.5
```

## Row-level data handling (enforced three ways)

A source holding microdata MUST declare `row_level = true`. Then:

- **Startup check** (`pipeline.py`): the engine refuses to run a `row_level`
  source unless `anonymize` is in `stages.list` (`PipelineGateError`).
- **Realness gate** (`realness.py`): the shape-dependent checks (duplicate rate /
  missingness / distribution) are SKIPPED for `row_level` sources — identical
  rows are *expected* in microdata and are not a fabrication signal. Provenance +
  named institution are still enforced.
- **Context hook** (`.claude/hooks/block_raw_data_reads.py`): any path under
  `microdata/` is blocked from model-context Read/Grep. Raw rows reach engine
  code only; the stage drops the raw frame from `ctx.state` after anonymizing.

## Demo: `analyses/brfss-demo/`

Diabetes prevalence by demographic stratum from CDC BRFSS-shaped microdata.
The committed fixture is **synthetic**, produced deterministically by
`microdata/make_fixture.py` (seeded; two rows carry a checksum-valid planted
fødselsnummer to exercise the PII gate — no real people, safe to commit). The
real BRFSS file is large public microdata; fetch it from
<https://www.cdc.gov/brfss/annual_data/annual_data.htm> into `microdata/`
(gitignored `*.xpt`) and point `path` at it for a live run.

Run:

```bash
uv run python analyses/brfss-demo/microdata/make_fixture.py   # regenerate fixture
uv run python -m omsorgsradar.pipeline analyses/brfss-demo
```

The bokmål report (`reports/brfss-demo_rapport.md`) leads with the residual-risk
framing, prints the three WP216 verdicts + k / l-diversity / suppression numbers
from the receipt, and tabulates prevalence only for strata with `n ≥
min_class_for_report`. Every number comes from `brfss_findings.json` /
`identifiability.json` and is independently recomputed by the verify stage.

## Enabling Norwegian NER (live)

```bash
uv run python -m spacy download nb_core_news_lg     # ~568 MB, one time
```

Then set `spacy_model = "nb_core_news_lg"` under `[params.anonymize]`. Names and
locations in free-text columns are then detected (`PERSON` / `LOC`) in addition
to the always-on checksum recognizers. Covered by the `live`-marked
`tests/test_anonymize_live.py`.
