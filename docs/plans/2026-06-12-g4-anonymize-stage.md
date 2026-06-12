# G4 — Anonymize Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Sonnet implementers; opus review panel (correctness/security/integration) at phase close. ≤10-agent budget — one implementer at a time, fan-outs only for the closing panel.

**Goal:** Add a config-listed, optional `anonymize` stage to the engine that (1) detects and redacts direct identifiers with Presidio + Norwegian recognizers, (2) generalizes + k-suppresses quasi-identifiers, and (3) publishes a **measured-residual-risk receipt** covering the three EU Art-29-WP216 criteria (singling-out / linkability / inference) — with a gate that aborts on FAIL. Demo instance: CDC BRFSS-shaped microdata. Planted-PII test required.

**Architecture:** Pure-Python engine code (LLM-free, deterministic) in a new `core/anonymize/` package, wired as a core stage in `stages.py` + the default registry. The raw microdata is loaded by the csv adapter into engine memory, consumed by the stage, and dropped from `ctx.state` before any downstream stage — and its on-disk path is hook-blocked from model context. Only the k-anonymized aggregate and the identifiability receipt (aggregate metrics) flow downstream. WP216 receipts are **vendored** in `core/anonymize/risk.py` (anonymeter the package is uninstallable on numpy 2 — see Task 1), computed with standard Statistical-Disclosure-Control math (k-anonymity / l-diversity / QI-uniqueness), citing WP216 + sdcMicro + Giomi et al. 2023 as method references.

**Tech Stack:** Python via `uv`; `presidio-analyzer` + `presidio-anonymizer` (+ optional spaCy `nb_core_news_lg` for NER, lazy/live-only); pandas/numpy; existing engine (registry, contracts, journal, csv adapter, realness gates).

---

## Why anonymeter is not a dependency (resolved 2026-06-12)

`uv pip compile` against the repo pins proves it cannot install:

```
anonymeter==1.0.0 depends on numpy>=1.22,<1.27 — repo requires numpy==2.4.6 → unsatisfiable
```

No PyPI release of anonymeter supports numpy 2. anonymeter also targets **synthetic-data** privacy risk (attacker NN-attacks comparing synthetic vs original+control); our stage produces **k-anonymized real microdata**, for which the correct framework is SDC re-identification risk. Owner decision 2026-06-12: **vendor the three WP216 criteria** in `risk.py` (offline, deterministic, testable, correct tool), replacing the "anonymeter receipts" bullet in DECISIONS.md. Presidio + spaCy resolve cleanly (verified, 57 packages).

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | add `presidio-analyzer`, `presidio-anonymizer`, `spacy` to deps; document no-anonymeter |
| `src/omsorgsradar/core/anonymize/__init__.py` | package marker + public re-exports |
| `src/omsorgsradar/core/anonymize/pii.py` | Norwegian PatternRecognizers (fnr/dnr/phone/konto) + Presidio scan + redact |
| `src/omsorgsradar/core/anonymize/kanon.py` | config-driven generalization + k-suppression; suppression stats |
| `src/omsorgsradar/core/anonymize/risk.py` | WP216 receipts: singling_out / linkability / inference + verdict |
| `src/omsorgsradar/core/contracts.py` | add `IDENTIFIABILITY_SCHEMA` + register in `SCHEMAS` |
| `src/omsorgsradar/stages.py` | `stage_anonymize(ctx)`; register `"anonymize"` in default registry |
| `src/omsorgsradar/pipeline.py` | startup check: any `row_level` source ⇒ `anonymize` must be in stages |
| `.claude/hooks/block_raw_data_reads.py` | block `(^|/)microdata(/|$)` paths |
| `analyses/brfss-demo/analysis.toml` | demo instance config (ingest→profile→anonymize→analyze→verify→report) |
| `analyses/brfss-demo/microdata/make_fixture.py` | seeded generator → synthetic BRFSS-shaped CSV (no real rows ever pasted) |
| `analyses/brfss-demo/stages.py` | instance analyze/verify/report (diabetes prevalence by generalized QI) |
| `docs/anonymize.md` | stage doc + framing (målt restrisiko, pseudonymisering≠anonymisering) |
| `tests/core/test_anonymize_pii.py` / `_kanon.py` / `_risk.py` | unit suites |
| `tests/test_anonymize_gate.py` | planted-PII pipeline gate test + row_level startup check |
| `tests/test_brfss_integration.py` | offline e2e for brfss-demo (no network, no spaCy) |
| `tests/test_hook_block_raw_data.py` | extend: microdata path blocked |

Downstream `analyze` in `brfss-demo` reads the **anonymized artifact**, never raw microdata.

---

### Task 1: Dependencies + decision record

**Files:**
- Modify: `pyproject.toml:7-20` (deps)
- Modify: `DECISIONS.md` (replace anonymeter bullet)
- Modify: `docs/specs/2026-06-11-v2-generalization-design.md` (anonymize section note)

- [ ] **Step 1: Add deps via uv** (lazy-imported by the stage, like ml deps)

```bash
uv add presidio-analyzer presidio-anonymizer spacy
```

Expected: resolves; lockfile updated. (No anonymeter — uninstallable.)

- [ ] **Step 2: Run the full suite to confirm no regression from the new deps**

```bash
uv run pytest
```
Expected: 247 offline pass + 4 deselected (unchanged from G3).

- [ ] **Step 3: Replace the anonymeter bullet in `DECISIONS.md`**

Find the bullet beginning "Anonymize stage framing: «anonymisering med målt restrisiko» (Presidio + anonymeter receipts)…" and replace with:

```markdown
- Anonymize stage framing: «anonymisering med målt restrisiko» — never claim "fully anonymous";
  pseudonymisering ≠ anonymisering (EDPB 01/2025, Datatilsynet). Residual-risk receipts cover the three
  EU Art-29-WP216 criteria (singling-out / linkability / inference), computed by vendored SDC math in
  `core/anonymize/risk.py` (k-anonymity / l-diversity / QI-uniqueness; refs WP216 + sdcMicro + Giomi 2023).
  The `anonymeter` package is NOT used — it pins numpy<1.27 (uninstallable on this stack) and targets
  synthetic data, not k-anonymized real microdata.
```

- [ ] **Step 4: Add a one-line note** under the spec's "Anonymize stage (optional, config-listed)" section recording the same (anonymeter uninstallable → vendored WP216).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock DECISIONS.md docs/specs/2026-06-11-v2-generalization-design.md
git commit -m "G4: deps (presidio+spacy, no anonymeter) + WP216-vendoring decision"
```

---

### Task 2: Norwegian PII recognizers + scan/redact (`pii.py`)

**Files:**
- Create: `src/omsorgsradar/core/anonymize/__init__.py`
- Create: `src/omsorgsradar/core/anonymize/pii.py`
- Test: `tests/core/test_anonymize_pii.py`

**Domain notes (exact, no placeholders):**
- **Fødselsnummer** = 11 digits `DDMMYY` + individnummer(3) + 2 control digits.
  - k1: weights `[3,7,6,1,8,9,4,5,2]` over digits 1–9; `k1 = 11 - (sum % 11)`; `11→0`; `10→invalid`.
  - k2: weights `[5,4,3,2,7,6,5,4,3,2]` over digits 1–10; `k2 = 11 - (sum % 11)`; `11→0`; `10→invalid`.
  - **D-nummer**: first digit of DD is increased by 4 (so DD ∈ 41–71); same checksum.
- Recognizers are pure regex+checksum → fully offline. spaCy NER (PERSON/LOC) is **optional** and **live-only**.

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_anonymize_pii.py
import pandas as pd
import pytest
from omsorgsradar.core.anonymize.pii import (
    valid_fnr_checksum, append_fnr_control_digits, scan_pii, redact_pii,
)

def _make_fnr(stem9: str) -> str:
    """stem9 = DDMMYY+individ(3); returns a checksum-valid 11-digit fnr."""
    return append_fnr_control_digits(stem9)

class TestChecksum:
    def test_appended_control_digits_validate(self):
        fnr = _make_fnr("010190123")           # 01 Jan 1990, individ 123
        assert len(fnr) == 11
        assert valid_fnr_checksum(fnr)

    def test_wrong_checksum_rejected(self):
        assert not valid_fnr_checksum("01019012300")

class TestScan:
    def test_detects_valid_fnr_only(self):
        good = _make_fnr("010190123")
        df = pd.DataFrame({"notes": [f"pasient {good}", "ringte 22 not an id 00000000000"]})
        hits = scan_pii(df, columns=["notes"])
        assert hits.loc[0, "n_entities"] >= 1
        assert "NO_FODSELSNUMMER" in hits.loc[0, "entity_types"]
        assert hits.loc[1, "n_entities"] == 0   # 11 zeros is not checksum-valid

    def test_phone_detected(self):
        df = pd.DataFrame({"t": ["tlf +47 911 23 456"]})
        hits = scan_pii(df, columns=["t"])
        assert "NO_TELEFON" in hits.loc[0, "entity_types"]

class TestRedact:
    def test_redacts_fnr_in_place(self):
        good = _make_fnr("010190123")
        df = pd.DataFrame({"notes": [f"pasient {good} innlagt"]})
        out, n = redact_pii(df, columns=["notes"])
        assert good not in out.loc[0, "notes"]
        assert "<NO_FODSELSNUMMER>" in out.loc[0, "notes"]
        assert n == 1
```

- [ ] **Step 2: Run to confirm failure** — `uv run pytest tests/core/test_anonymize_pii.py -x` → import error / not defined.

- [ ] **Step 3: Implement `pii.py`**

```python
"""Norwegian PII detection + redaction over Presidio.

Direct-identifier recognizers are pure regex + checksum (offline, deterministic).
Free-text name/location NER via spaCy nb_core_news_lg is OPTIONAL and loaded
lazily only when [params.anonymize].spacy_model is set (live tests only — the
offline suite never downloads the 568 MB model).
"""
from __future__ import annotations

from typing import Sequence
import pandas as pd

import spacy
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

LANG = "nb"  # Norwegian Bokmål — spacy.blank("nb") + the live nb_core_news_lg model both use this code

_FNR_K1_W = [3, 7, 6, 1, 8, 9, 4, 5, 2]
_FNR_K2_W = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]

def _control_digit(digits: list[int], weights: list[int]) -> int | None:
    s = sum(d * w for d, w in zip(digits, weights))
    k = 11 - (s % 11)
    if k == 11:
        return 0
    if k == 10:
        return None
    return k

def valid_fnr_checksum(fnr: str) -> bool:
    if len(fnr) != 11 or not fnr.isdigit():
        return False
    d = [int(c) for c in fnr]
    k1 = _control_digit(d[:9], _FNR_K1_W)
    k2 = _control_digit(d[:10], _FNR_K2_W)
    return k1 is not None and k2 is not None and k1 == d[9] and k2 == d[10]

def append_fnr_control_digits(stem9: str) -> str:
    """Append valid control digits to a 9-digit stem (DDMMYY+individ). Test helper
    AND used by recognizer self-tests — never hardcode a magic fnr."""
    d = [int(c) for c in stem9]
    k1 = _control_digit(d, _FNR_K1_W)
    if k1 is None:
        raise ValueError("stem yields invalid k1; pick another individ number")
    k2 = _control_digit(d + [k1], _FNR_K2_W)
    if k2 is None:
        raise ValueError("stem yields invalid k2; pick another individ number")
    return stem9 + str(k1) + str(k2)

class _FnrRecognizer(PatternRecognizer):
    """11 consecutive digits that pass the mod-11 checksum (fnr or D-nummer)."""
    def __init__(self) -> None:
        super().__init__(
            supported_entity="NO_FODSELSNUMMER",
            patterns=[Pattern("fnr-11d", r"\b\d{11}\b", 0.3)],
            name="NoFodselsnummerRecognizer",
            supported_language=LANG,
        )
    def validate_result(self, pattern_text: str):  # Presidio checksum hook
        # True → score 1.0 (validated); False → result REMOVED (invalid checksum);
        # None → keep base score. Verified live 2026-06-12.
        return True if valid_fnr_checksum(pattern_text) else False

def _phone_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="NO_TELEFON",
        patterns=[Pattern("no-phone", r"(\+47[\s]?)?(\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}|\d{3}[\s]?\d{2}[\s]?\d{3})", 0.4)],
        name="NoTelefonRecognizer",
        supported_language=LANG,
    )

def _konto_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="NO_KONTONUMMER",
        patterns=[Pattern("no-konto", r"\b\d{4}[\s.]?\d{2}[\s.]?\d{5}\b", 0.3)],
        name="NoKontonummerRecognizer",
        supported_language=LANG,
    )

class _BlankSpacyNlpEngine(SpacyNlpEngine):
    """Tokenizer-only spaCy pipeline — real NlpArtifacts, NO model download (no
    568 MB), empty NER. This is the OFFLINE path (verified live 2026-06-12):
    pattern recognizers fire, names/locations are not detected."""
    def __init__(self, lang: str = LANG) -> None:
        super().__init__(models=[{"lang_code": lang, "model_name": "blank"}])
        self.nlp = {lang: spacy.blank(lang)}

def build_analyzer(spacy_model: str | None = None) -> AnalyzerEngine:
    registry = RecognizerRegistry(supported_languages=[LANG])
    registry.add_recognizer(_FnrRecognizer())
    registry.add_recognizer(_phone_recognizer())
    registry.add_recognizer(_konto_recognizer())
    if spacy_model:  # live only — real nb model pulls PERSON/LOC from free text
        nlp = SpacyNlpEngine(models=[{"lang_code": LANG, "model_name": spacy_model}])
    else:
        nlp = _BlankSpacyNlpEngine(LANG)
    return AnalyzerEngine(registry=registry, nlp_engine=nlp, supported_languages=[LANG])

def scan_pii(df: pd.DataFrame, columns: Sequence[str], spacy_model: str | None = None) -> pd.DataFrame:
    """Per-row PII scan over the named columns. Returns a frame with n_entities +
    entity_types (sorted unique) per original row index. No raw values returned."""
    analyzer = build_analyzer(spacy_model)
    rows = []
    for _, row in df.iterrows():
        types, n = set(), 0
        for col in columns:
            text = "" if pd.isna(row.get(col)) else str(row[col])
            res = analyzer.analyze(text=text, language=LANG)
            n += len(res)
            types.update(r.entity_type for r in res)
        rows.append({"n_entities": n, "entity_types": sorted(types)})
    return pd.DataFrame(rows, index=df.index)

def redact_pii(df: pd.DataFrame, columns: Sequence[str], spacy_model: str | None = None) -> tuple[pd.DataFrame, int]:
    """Replace detected entities with <ENTITY_TYPE> in the named columns.
    Returns (redacted_copy, total_entities_redacted)."""
    analyzer = build_analyzer(spacy_model)
    anonymizer = AnonymizerEngine()
    out = df.copy()
    total = 0
    for col in columns:
        new_vals = []
        for v in out[col]:
            text = "" if pd.isna(v) else str(v)
            res = analyzer.analyze(text=text, language=LANG)
            total += len(res)
            if res:
                operators = {r.entity_type: OperatorConfig("replace",
                            {"new_value": f"<{r.entity_type}>"}) for r in res}
                text = anonymizer.anonymize(text=text, analyzer_results=res, operators=operators).text
            new_vals.append(text)
        out[col] = new_vals
    return out, total
```

- [ ] **Step 4: Create `__init__.py`**

```python
"""Anonymize subpackage: PII redaction, k-anonymization, WP216 risk receipts."""
from .pii import scan_pii, redact_pii, valid_fnr_checksum, append_fnr_control_digits  # noqa: F401
```

- [ ] **Step 5: Run** `uv run pytest tests/core/test_anonymize_pii.py -v` → PASS. If Presidio's `validate_result` contract differs (returns None vs bool), adjust to its actual signature — confirm via `uv run python -c "import presidio_analyzer; print(presidio_analyzer.__version__)"` and the installed `PatternRecognizer.validate_result` docstring. **Build against the installed API, not assumptions** (lesson from G1 socialstyrelsen).

- [ ] **Step 6: Commit** — `git commit -m "G4: Norwegian PII recognizers + Presidio scan/redact"`

---

### Task 3: k-anonymity generalization + suppression (`kanon.py`)

**Files:**
- Create: `src/omsorgsradar/core/anonymize/kanon.py`
- Test: `tests/core/test_anonymize_kanon.py`

**Config shape (from `[params.anonymize]`, no hardcoded QIs/bins):**
```toml
[params.anonymize]
quasi_identifiers = ["state", "age", "sex"]
sensitive = "diabetes"
k = 5
[params.anonymize.generalize.age]      # numeric binning hierarchy
bins = [18, 30, 45, 60, 75, 200]
labels = ["18-29", "30-44", "45-59", "60-74", "75+"]
```

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_anonymize_kanon.py
import pandas as pd
from omsorgsradar.core.anonymize.kanon import generalize, k_suppress, KAnonResult

def _df():
    return pd.DataFrame({
        "state": ["06"]*8 + ["48"]*2,
        "age":   [20,21,22,23,24,25,26,27, 80, 81],
        "sex":   [1]*10,
        "diabetes": [0,1,0,0,1,0,0,1, 1, 0],
    })

CFG = {"quasi_identifiers": ["state","age","sex"], "sensitive": "diabetes", "k": 5,
       "generalize": {"age": {"bins":[18,30,45,60,75,200],
                              "labels":["18-29","30-44","45-59","60-74","75+"]}}}

class TestGeneralize:
    def test_age_binned(self):
        g = generalize(_df(), CFG)
        assert set(g["age"]) <= {"18-29","75+"}

class TestSuppress:
    def test_small_classes_dropped(self):
        res = k_suppress(generalize(_df(), CFG), CFG)
        assert isinstance(res, KAnonResult)
        # state 48 / 75+ class has 2 < k=5 → suppressed; state 06 / 18-29 has 8 ≥ 5 → kept
        assert res.min_class_size >= 5
        assert res.n_suppressed == 2
        assert len(res.frame) == 8
    def test_suppression_rate_reported(self):
        res = k_suppress(generalize(_df(), CFG), CFG)
        assert abs(res.suppression_rate - 0.2) < 1e-9
```

- [ ] **Step 2: Run to confirm failure.**

- [ ] **Step 3: Implement `kanon.py`**

```python
"""k-anonymity by full-domain generalization + record suppression.

Generalization hierarchies come entirely from [params.anonymize].generalize —
no hardcoded bins. Equivalence classes smaller than k on the quasi-identifiers
are suppressed (dropped); stats are returned for the identifiability receipt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import pandas as pd

@dataclass
class KAnonResult:
    frame: pd.DataFrame          # k-anonymized rows (generalized QIs + sensitive)
    quasi_identifiers: list[str]
    k: int
    min_class_size: int
    n_input: int
    n_suppressed: int
    suppression_rate: float
    n_classes: int

def generalize(df: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.DataFrame:
    out = df.copy()
    gen = dict(cfg.get("generalize", {}))
    for col, spec in gen.items():
        if "bins" in spec:                       # numeric → labelled band
            out[col] = pd.cut(pd.to_numeric(out[col], errors="coerce"),
                              bins=list(spec["bins"]), labels=list(spec["labels"]),
                              right=False, include_lowest=True).astype("object")
        elif "map" in spec:                      # categorical → coarser category
            out[col] = out[col].map(dict(spec["map"])).fillna(out[col])
    return out

def k_suppress(df: pd.DataFrame, cfg: Mapping[str, Any]) -> KAnonResult:
    qis = list(cfg["quasi_identifiers"])
    k = int(cfg["k"])
    sizes = df.groupby(qis, dropna=False).transform("size")
    # transform("size") on a grouped frame returns per-column; take any column:
    class_size = df.groupby(qis, dropna=False)[qis[0]].transform("size")
    keep = class_size >= k
    kept = df[keep].copy()
    n_input = len(df)
    n_suppressed = int((~keep).sum())
    surviving = kept.groupby(qis, dropna=False)[qis[0]].transform("size")
    return KAnonResult(
        frame=kept.reset_index(drop=True),
        quasi_identifiers=qis,
        k=k,
        min_class_size=int(surviving.min()) if len(kept) else 0,
        n_input=n_input,
        n_suppressed=n_suppressed,
        suppression_rate=round(n_suppressed / n_input, 6) if n_input else 0.0,
        n_classes=int(kept.groupby(qis, dropna=False).ngroups) if len(kept) else 0,
    )
```

- [ ] **Step 4: Run** `uv run pytest tests/core/test_anonymize_kanon.py -v` → PASS. (Remove the unused `sizes` line if the implementer's first draft kept it — keep the file clean.)

- [ ] **Step 5: Commit** — `git commit -m "G4: k-anonymity generalization + suppression"`

---

### Task 4: WP216 residual-risk receipts (`risk.py`)

**Files:**
- Create: `src/omsorgsradar/core/anonymize/risk.py`
- Test: `tests/core/test_anonymize_risk.py`

**Definitions (vendored; cite WP216 + sdcMicro + Giomi et al. 2023 in the docstring):**
- **singling_out** ← k-anonymity. `min_class_size`; prosecutor risk `1/min_class_size`; journalist risk `mean(1/class_size)`; `share_below_k`. PASS iff `min_class_size ≥ k` and `share_below_k == 0`.
- **linkability** ← QI uniqueness against a reference/holdout. `unique_qi_share` = share of released equivalence classes that are unique (size 1) on the **generalized** QIs *before* suppression (i.e. measured on the generalized input). With a reference population provided, additionally report `linkable_share` = share of release classes whose QI-combo is unique in the reference. PASS iff `unique_qi_share ≤ link_threshold` (default after suppression: 0).
- **inference** ← l-diversity + attacker advantage. For each class, `p_max` = max frequency of any sensitive value; `adv = p_max − marginal(p_max_value)`. Report `min_l_diversity` (distinct sensitive values per class), `max_attacker_adv`, `mean_attacker_adv`. PASS iff `min_l_diversity ≥ l_min` and `max_attacker_adv ≤ inf_threshold`.
- Overall verdict = worst of the three (FAIL > WARN > PASS). WARN band configurable; default: inference WARN if `l_min` met but `max_attacker_adv` in `(inf_threshold, inf_threshold+0.15]`.

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_anonymize_risk.py
import pandas as pd
from omsorgsradar.core.anonymize.kanon import generalize, k_suppress
from omsorgsradar.core.anonymize.risk import assess_identifiability

CFG = {"quasi_identifiers": ["state","age","sex"], "sensitive": "diabetes", "k": 5,
       "generalize": {"age": {"bins":[18,30,45,60,75,200],
                              "labels":["18-29","30-44","45-59","60-74","75+"]}},
       "thresholds": {"l_min": 2, "inference": 0.5, "linkability": 0.0}}

def _bigdf():
    import numpy as np
    rng = np.random.default_rng(0)
    n = 200
    return pd.DataFrame({
        "state": rng.choice(["06","48","36"], n),
        "age": rng.integers(18, 90, n),
        "sex": rng.integers(1, 3, n),
        "diabetes": rng.integers(0, 2, n),
    })

class TestAssess:
    def test_passes_after_ksuppress(self):
        res = k_suppress(generalize(_bigdf(), CFG), CFG)
        rep = assess_identifiability(res, generalize(_bigdf(), CFG), CFG)
        assert rep["singling_out"]["min_class_size"] >= 5
        assert rep["singling_out"]["verdict"] == "PASS"
        assert rep["verdict"] in {"PASS", "WARN"}
        assert "singling-out" in rep["criteria_ref"]

    def test_homogeneous_sensitive_flags_inference(self):
        df = _bigdf()
        df["diabetes"] = 1                      # every class fully homogeneous
        res = k_suppress(generalize(df, CFG), CFG)
        rep = assess_identifiability(res, generalize(df, CFG), CFG)
        assert rep["inference"]["min_l_diversity"] == 1
        assert rep["inference"]["verdict"] == "FAIL"
        assert rep["verdict"] == "FAIL"
```

- [ ] **Step 2: Run to confirm failure.**

- [ ] **Step 3: Implement `risk.py`**

```python
"""Measured residual-risk receipts for the three EU Art-29-WP216 criteria.

WP216 (Article 29 Working Party, Opinion 05/2014) names three risks an effective
anonymisation must control: SINGLING OUT, LINKABILITY, INFERENCE. We measure each
with standard Statistical-Disclosure-Control quantities (k-anonymity / QI-uniqueness
/ l-diversity + attacker advantage), per sdcMicro (Templ et al.) and the unified
framing of Giomi et al. 2023 ("A Unified Framework for Quantifying Privacy Risk").

The `anonymeter` package is intentionally NOT used: it pins numpy<1.27 (uninstallable
here) and targets synthetic data; this stage releases k-anonymized real microdata.

Framing everywhere: «anonymisering med målt restrisiko» — never "fully anonymous".
"""
from __future__ import annotations

from typing import Any, Mapping
import pandas as pd

from .kanon import KAnonResult

CRITERIA_REF = "EU Art-29 WP216: singling-out / linkability / inference"

def _verdict(*statuses: str) -> str:
    order = {"FAIL": 3, "WARN": 2, "PASS": 1, "SKIP": 0}
    return max(statuses, key=lambda s: order[s])

def _singling_out(res: KAnonResult) -> dict[str, Any]:
    m = res.min_class_size
    status = "PASS" if (m >= res.k and res.n_suppressed_below_k_zero()) else "FAIL"
    return {
        "criterion": "singling-out",
        "min_class_size": m,
        "k_target": res.k,
        "prosecutor_risk": round(1.0 / m, 6) if m else 1.0,
        "share_below_k": 0.0 if m >= res.k else 1.0,
        "verdict": "PASS" if m >= res.k else "FAIL",
    }

def _linkability(generalized: pd.DataFrame, cfg: Mapping[str, Any]) -> dict[str, Any]:
    qis = list(cfg["quasi_identifiers"])
    sizes = generalized.groupby(qis, dropna=False)[qis[0]].transform("size")
    unique_share = float((sizes == 1).mean()) if len(generalized) else 0.0
    thr = float(cfg.get("thresholds", {}).get("linkability", 0.0))
    return {
        "criterion": "linkability",
        "unique_qi_share_pre_suppression": round(unique_share, 6),
        "threshold": thr,
        "verdict": "PASS" if unique_share <= thr else
                   ("WARN" if unique_share <= thr + 0.05 else "FAIL"),
    }

def _inference(res: KAnonResult, cfg: Mapping[str, Any]) -> dict[str, Any]:
    qis, sens = res.quasi_identifiers, cfg["sensitive"]
    thr = float(cfg.get("thresholds", {}).get("inference", 0.5))
    l_min = int(cfg.get("thresholds", {}).get("l_min", 2))
    df = res.frame
    if df.empty or sens not in df.columns:
        return {"criterion": "inference", "min_l_diversity": 0,
                "max_attacker_adv": 0.0, "mean_attacker_adv": 0.0, "verdict": "SKIP"}
    marginal = df[sens].value_counts(normalize=True).to_dict()
    advs, ls = [], []
    for _, g in df.groupby(qis, dropna=False):
        probs = g[sens].value_counts(normalize=True)
        top_val = probs.idxmax()
        advs.append(float(probs.max() - marginal.get(top_val, 0.0)))
        ls.append(int(g[sens].nunique()))
    min_l, max_adv = min(ls), max(advs)
    if min_l < l_min:
        v = "FAIL"
    elif max_adv > thr + 0.15:
        v = "FAIL"
    elif max_adv > thr:
        v = "WARN"
    else:
        v = "PASS"
    return {"criterion": "inference", "min_l_diversity": min_l,
            "max_attacker_adv": round(max_adv, 6),
            "mean_attacker_adv": round(sum(advs)/len(advs), 6),
            "l_min": l_min, "threshold": thr, "verdict": v}

def assess_identifiability(res: KAnonResult, generalized: pd.DataFrame,
                           cfg: Mapping[str, Any]) -> dict[str, Any]:
    so = _singling_out(res)
    lk = _linkability(generalized, cfg)
    inf = _inference(res, cfg)
    return {
        "framing": "anonymisering med målt restrisiko",
        "criteria_ref": CRITERIA_REF,
        "k_anonymity": {"k_target": res.k, "min_class_size": res.min_class_size,
                        "n_suppressed": res.n_suppressed,
                        "suppression_rate": res.suppression_rate,
                        "n_records_released": len(res.frame),
                        "n_classes": res.n_classes},
        "singling_out": so, "linkability": lk, "inference": inf,
        "verdict": _verdict(so["verdict"], lk["verdict"], inf["verdict"]),
    }
```

- [ ] **Step 4: Add the `n_suppressed_below_k_zero` helper to `KAnonResult`** in `kanon.py`:

```python
    def n_suppressed_below_k_zero(self) -> bool:
        """True iff every released class meets k (min_class_size ≥ k)."""
        return self.min_class_size >= self.k
```
(Replace the `res.n_suppressed_below_k_zero()` call in `_singling_out`'s `status` line — drop the unused `status` local; the `verdict` field is the source of truth.)

- [ ] **Step 5: Run** `uv run pytest tests/core/test_anonymize_risk.py -v` → PASS.

- [ ] **Step 6: Export from `__init__.py`** (`assess_identifiability`, `generalize`, `k_suppress`, `KAnonResult`) and **commit** — `git commit -m "G4: WP216 residual-risk receipts (vendored SDC math)"`

---

### Task 5: `anonymize` stage + contract + gate + hook + startup check

**Files:**
- Modify: `src/omsorgsradar/core/contracts.py` (schema)
- Modify: `src/omsorgsradar/stages.py` (stage + registry)
- Modify: `src/omsorgsradar/pipeline.py` (row_level startup check)
- Modify: `.claude/hooks/block_raw_data_reads.py` (microdata pattern)
- Test: `tests/test_anonymize_gate.py`, extend `tests/test_hook_block_raw_data.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_anonymize_gate.py
import pandas as pd
import pytest
from omsorgsradar.core.registry import StageContext, PipelineGateError
from omsorgsradar.core.config import RunConfig
from omsorgsradar.stages import stage_anonymize
from omsorgsradar.core.anonymize.pii import append_fnr_control_digits

def _ctx(tmp_path, datasets, params):
    cfg = RunConfig.__new__(RunConfig)          # lightweight; or use a real loader fixture
    # ... construct via the project's existing RunConfig test helper (see conftest) ...

def test_planted_pii_redacted_and_receipted(brfss_like_ctx):
    """A planted valid fnr in a text column is redacted; receipt records PII found."""
    ctx = brfss_like_ctx
    stage_anonymize(ctx)
    receipt = ctx.state["identifiability"]
    assert receipt["pii"]["total_redacted"] >= 1
    assert "NO_FODSELSNUMMER" in receipt["pii"]["entity_types"]
    # raw microdata dropped from state (must not flow downstream)
    assert "raw_microdata" not in ctx.state.get("datasets", {})

def test_inference_fail_aborts(homogeneous_ctx):
    with pytest.raises(PipelineGateError, match="identifiability"):
        stage_anonymize(homogeneous_ctx)
    # verdict written to disk BEFORE the raise (inspectable)
    import json
    rep = json.loads((homogeneous_ctx.data_dir / "identifiability.json").read_text())
    assert rep["verdict"] == "FAIL"
```

```python
# tests/test_anonymize_gate.py — startup check
def test_row_level_source_requires_anonymize(tmp_analysis_with_row_level_source):
    from omsorgsradar.pipeline import run_pipeline
    with pytest.raises(PipelineGateError, match="row_level.*anonymize"):
        run_pipeline(tmp_analysis_with_row_level_source, skip_ingest=False)
```

```python
# extend tests/test_hook_block_raw_data.py
def test_microdata_path_blocked():
    payload = {"tool_name": "Read",
               "tool_input": {"file_path": "analyses/brfss-demo/microdata/raw.csv"}}
    # invoke hook subprocess; expect exit code 2 (blocked) — mirror existing test style
```

The implementer must reuse the project's existing pipeline/ctx test fixtures (see `tests/conftest.py`, `tests/test_pipeline_gate.py`, `tests/test_nordic_integration.py`) rather than hand-rolling `RunConfig`. Provide the fixtures `brfss_like_ctx` / `homogeneous_ctx` in `tests/conftest.py` building a tiny in-memory dataset + a real `RunConfig` via `load_run_config` on a temp analysis dir.

- [ ] **Step 2: Run to confirm failure.**

- [ ] **Step 3: Add `IDENTIFIABILITY_SCHEMA` to `contracts.py`** and register in `SCHEMAS`:

```python
IDENTIFIABILITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "criteria_ref", "singling_out", "linkability", "inference"],
    "properties": {
        "verdict": {"enum": ["PASS", "WARN", "FAIL", "SKIP"]},
        "criteria_ref": {"type": "string"},
        "framing": {"type": "string"},
        "k_anonymity": {"type": "object"},
        "pii": {"type": "object"},
        "singling_out": {"type": "object", "required": ["verdict"]},
        "linkability": {"type": "object", "required": ["verdict"]},
        "inference": {"type": "object", "required": ["verdict"]},
    },
}
# ... add "identifiability": IDENTIFIABILITY_SCHEMA to the SCHEMAS dict
```

- [ ] **Step 4: Implement `stage_anonymize` in `stages.py`** and register it:

```python
def stage_anonymize(ctx: StageContext) -> None:
    """Redact direct identifiers, k-anonymize quasi-identifiers, publish a
    measured-residual-risk receipt (WP216). Raw microdata is consumed here and
    dropped from state; only the anonymized aggregate flows downstream."""
    from .core.anonymize import assess_identifiability, generalize, k_suppress
    from .core.anonymize.pii import redact_pii, scan_pii

    acfg = dict(ctx.config.params.get("anonymize", {}))
    if not acfg:
        raise PipelineGateError("anonymize stage requires [params.anonymize] config")
    src_id = acfg["source"]
    datasets = ctx.state["datasets"]
    raw = datasets[src_id]

    text_cols = list(acfg.get("text_columns", []))
    spacy_model = acfg.get("spacy_model")
    pii_summary = {"total_redacted": 0, "entity_types": []}
    work = raw
    if text_cols:
        scanned = scan_pii(raw, text_cols, spacy_model=spacy_model)
        work, n = redact_pii(raw, text_cols, spacy_model=spacy_model)
        types = sorted({t for row in scanned["entity_types"] for t in row})
        pii_summary = {"total_redacted": int(n), "entity_types": types}

    generalized = generalize(work, acfg)
    kres = k_suppress(generalized, acfg)
    receipt = assess_identifiability(kres, generalized, acfg)
    receipt["pii"] = pii_summary

    anon_path = ctx.data_dir / f"{src_id}_anonymized.csv"
    kres.frame.to_csv(anon_path, index=False)
    write_manifest(anon_path, artifact="anonymized_table", producer="anonymize")

    rpath = ctx.data_dir / "identifiability.json"
    rpath.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    validate_artifact("identifiability", receipt)
    write_manifest(rpath, artifact="identifiability", producer="anonymize",
                   inputs=[str(anon_path)])

    # Replace raw with the anonymized aggregate; never leave raw in state.
    datasets[src_id] = kres.frame
    ctx.state["identifiability"] = receipt
    ctx.artifacts["anonymized_table"] = anon_path
    ctx.artifacts["identifiability"] = rpath
    if receipt["verdict"] == "FAIL":
        raise PipelineGateError(
            f"identifiability gate FAIL — {receipt['singling_out']['verdict']}/"
            f"{receipt['linkability']['verdict']}/{receipt['inference']['verdict']} "
            f"(see {rpath})")
```
Register in `build_default_registry`: `registry.register("anonymize", stage_anonymize)`.
Add `"anonymized_table"` to nothing special — it's a CSV with a manifest; no JSON schema needed (only JSON artifacts validate). Confirm `write_manifest` on a CSV path works (it hashes bytes — fine).

- [ ] **Step 5: Add the row_level startup check to `pipeline.py`** (right after the `validate_source`/`validate_source_host` loop):

```python
    row_level = [s["id"] for s in cfg.sources if s.get("row_level")]
    if row_level and "anonymize" not in cfg.stage_list:
        raise PipelineGateError(
            f"sources {row_level} are row_level=true but 'anonymize' is not in "
            f"stages.list — row-level data must be anonymized before analysis")
```
(Import `PipelineGateError` is already in scope.)

- [ ] **Step 6: Extend the hook** `block_raw_data_reads.py` — add to `BLOCKED_PATTERNS`:

```python
    r"(^|/)microdata(/|$)",
```

- [ ] **Step 7: Run** `uv run pytest tests/test_anonymize_gate.py tests/test_hook_block_raw_data.py -v` → PASS.

- [ ] **Step 8: Commit** — `git commit -m "G4: anonymize stage + identifiability gate + row_level startup check + hook"`

---

### Task 6: BRFSS-demo instance (offline e2e)

**Files:**
- Create: `analyses/brfss-demo/analysis.toml`
- Create: `analyses/brfss-demo/microdata/make_fixture.py` (seeded; generates the CSV)
- Create: `analyses/brfss-demo/stages.py` (analyze/verify/report)
- Modify: `.gitignore` (ignore real BRFSS download, keep the generated fixture)
- Test: `tests/test_brfss_integration.py`

**Privacy note:** no real microdata rows are ever read into model context. The fixture is produced by a **seeded generator script** (synthetic, deterministic), committed as code; the generated CSV lives under the hook-blocked `microdata/` dir.

- [ ] **Step 1: `make_fixture.py`** — deterministic synthetic BRFSS-shaped data with a planted fnr:

```python
"""Generate a synthetic BRFSS-shaped microdata fixture (deterministic, seeded).
Columns: state (FIPS), age (int), sex (1/2), diabetes (0/1), notes (free text).
Two rows carry a planted valid fødselsnummer to exercise the PII gate. No real
people; safe to commit. Run: uv run python analyses/brfss-demo/microdata/make_fixture.py
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from omsorgsradar.core.anonymize.pii import append_fnr_control_digits

def build(n: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "state": rng.choice(["06","48","36","12","17"], n),
        "age":   rng.integers(18, 95, n),
        "sex":   rng.integers(1, 3, n),
        "diabetes": rng.integers(0, 2, n),
        "notes": ["rutinekontroll"] * n,
    })
    fnr = append_fnr_control_digits("010190123")
    df.loc[0, "notes"] = f"pasient {fnr} oppfølging"
    df.loc[1, "notes"] = f"tlf 91123456; fnr {append_fnr_control_digits('150385221')}"
    return df

if __name__ == "__main__":
    out = Path(__file__).parent / "brfss_sample.csv"
    build().to_csv(out, index=False)
    print(f"wrote {out}")
```

- [ ] **Step 2: `analysis.toml`**

```toml
[analysis]
name = "brfss-demo"
question = "Hvordan kan vi publisere kommunenær diabetes-prevalens fra mikrodata med målt gjenidentifiseringsrisiko?"
language = "nb"

[stages]
list = ["ingest", "profile", "anonymize", "analyze", "verify", "report"]

[[sources]]
adapter = "csv"
id = "brfss"
path = "microdata/brfss_sample.csv"
row_level = true
[sources.provenance]
institution = "US CDC — Behavioral Risk Factor Surveillance System (BRFSS)"
url = "https://www.cdc.gov/brfss/annual_data/annual_data.htm"

[params.anonymize]
source = "brfss"
text_columns = ["notes"]
quasi_identifiers = ["state", "age", "sex"]
sensitive = "diabetes"
k = 10
[params.anonymize.generalize.age]
bins = [18, 30, 45, 60, 75, 200]
labels = ["18-29", "30-44", "45-59", "60-74", "75+"]
[params.anonymize.thresholds]
l_min = 2
inference = 0.5
linkability = 0.0
```

- [ ] **Step 3: `stages.py`** — analyze (prevalence per released class) → verify (independent recompute) → bokmål report citing the identifiability receipt. Follow the nordisk-omsorg pattern exactly (register schema, validate_artifact, write_manifest, PipelineGateError on verify FAIL, numbers only from the findings artifact). Analyze reads `data/brfss_anonymized.csv` (the anonymize artifact), computes diabetes prevalence by (state × age band × sex), writes `brfss_findings.json` (register `brfss_findings` schema). Verify recomputes every prevalence from the anonymized CSV. Report is bokmål, leads with «anonymisering med målt restrisiko», embeds the k/l/suppression numbers + the three WP216 verdicts from `identifiability.json`, and states pseudonymisering ≠ anonymisering.

- [ ] **Step 4: Integration test** `tests/test_brfss_integration.py` — generate fixture in `tmp_path` (or use committed CSV), run `run_pipeline("analyses/brfss-demo", data_dir=tmp, reports_dir=tmp, skip_ingest=False)` with **no network, no spaCy** (text PII via regex recognizers only), assert: report exists, `identifiability.json` verdict ∈ {PASS, WARN}, fnr absent from the anonymized CSV, k achieved ≥ 10, verify PASS.

- [ ] **Step 5: `.gitignore`** — add `analyses/brfss-demo/microdata/*.xpt` and any real download; **keep** `brfss_sample.csv` + `make_fixture.py` tracked.

- [ ] **Step 6: Run** `uv run pytest tests/test_brfss_integration.py -v` and `uv run python -m omsorgsradar.pipeline analyses/brfss-demo --data-dir /tmp/brfss --reports-dir /tmp/brfss` → green report. **Commit** — `git commit -m "G4: brfss-demo instance — anonymize→prevalence with measured residual risk"`

---

### Task 7: Docs + framing + live spaCy test

**Files:**
- Create: `docs/anonymize.md`
- Modify: `README.md`, `LIMITATIONS.md`, `COSTS.md`, `status.md`
- Modify: `.claude/skills/pipeline-stages/SKILL.md`
- Create: `tests/test_anonymize_live.py` (live-marked spaCy nb test)

- [ ] **Step 1: `docs/anonymize.md`** — the stage: what it does, config keys, the WP216 mapping table (criterion → SDC measure → field), why anonymeter isn't used, how to fetch real BRFSS, how to enable spaCy nb NER. Framing: «anonymisering med målt restrisiko», never "fully anonymous"; pseudonymisering ≠ anonymisering (EDPB 01/2025, Datatilsynet); cite WP216 + sdcMicro + Giomi 2023.

- [ ] **Step 2: README + LIMITATIONS** — add an anonymize paragraph (bokmål summary too). LIMITATIONS: residual risk is *measured, not eliminated*; k-anonymity ≠ differential privacy; generalization choices are analyst decisions; the demo uses synthetic BRFSS-shaped data (real fetch documented). COSTS: anonymize stage is LLM-free → near-zero marginal cost; one-time spaCy nb download ~568 MB (live only).

- [ ] **Step 3: `pipeline-stages` skill** — add `anonymize` to the stage list, its position (after profile, before analyze), the `[params.anonymize]` keys, and the row_level convention.

- [ ] **Step 4: Live test** `tests/test_anonymize_live.py` (`@pytest.mark.live`) — downloads/uses `nb_core_news_lg`, asserts a planted Norwegian name in free text is detected as PERSON and redacted. Skipped in the offline suite.

- [ ] **Step 5: Update `status.md`** with the G4-shipped entry (date 2026-06-12, test counts, the anonymeter→WP216 decision, brfss-demo).

- [ ] **Step 6: Run full suite** `uv run pytest` → all offline green (new total ≈ 247 + ~25). **Commit** — `git commit -m "G4: anonymize docs + framing + live spaCy test + status"`

---

## Closing panel (after Task 7)

`blast-radius-mapper` (opus) → 3 parallel reviewers:
- **correctness** (opus): WP216 math vs definitions; verify-recompute independence in brfss stages; gate-before-abort ordering.
- **security** (opus): row-level data never reaches model context (state drop + hook + startup check); csv containment still holds for `microdata/`; no PII in committed fixture beyond synthetic planted values; no raw rows in run journals/manifests.
- **integration** (sonnet): `IDENTIFIABILITY_SCHEMA` round-trips; registry registration; deps lockfile; offline suite green without spaCy.

Any BLOCK → fix + re-review (cap 3). Then push to `main`.

## Self-review (writing-plans checklist)

- **Spec coverage:** Presidio nb ✓ (Task 2 + live Task 7) · k-threshold aggregation ✓ (Task 3) · WP216/anonymeter-equivalent receipts ✓ (Task 4, vendored per owner decision) · identifiability artifact ✓ (Task 5 schema) · BRFSS demo ✓ (Task 6) · planted-PII test ✓ (Task 5 + Task 6) · «målt restrisiko» framing ✓ (Tasks 1,4,7) · row-level-never-in-context ✓ (state drop + hook + startup check, Task 5).
- **Placeholder scan:** none — every code step is concrete. Two `# ...` markers (conftest fixture wiring in Task 5 Step 1, instance stages in Task 6 Step 3) explicitly delegate to the named existing pattern files rather than re-printing them.
- **Type consistency:** `KAnonResult` fields used in `risk.py` match Task 3's dataclass (+ the `n_suppressed_below_k_zero` helper added in Task 4 Step 4); `assess_identifiability(res, generalized, cfg)` signature consistent across Task 4 + Task 5; receipt keys (`singling_out`/`linkability`/`inference`/`verdict`) match the schema (Task 5) and tests (Task 4).
