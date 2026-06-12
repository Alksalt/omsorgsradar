# G2 — analyses/nordisk-omsorg End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first cross-country analysis instance — `analyses/nordisk-omsorg/` (NO/SE/FI
ageing vs home-care capacity per municipality) — end-to-end with a bokmål report, full tool
receipts, and a planted-hallucination test, per spec G2.

**Architecture:** Everything analysis-specific lives in the instance folder
(`analysis.toml` + `stages.py` shadowing `analyze`/`verify`/`report` via the G0 extension
point) — core is touched only for three small generic mechanisms: pxweb `use_codes` +
`label_columns` options, a `kolada` adapter (SE elder-care; the sdb API has no äldreomsorg
topic — verified 2026-06-12), and `contracts.register_schema` so instances can register
their own artifact schemas. The squeeze metric is computed **within country** (z-scores)
and only *patterns* are compared across countries — age cuts and definitions differ
(NO/SE 80+, FI 75+), and the report says so explicitly.

**Tech Stack:** Existing stack only (pandas, requests, matplotlib, jsonschema, duckdb,
pytest via `uv`). No new dependencies.

**Dataset ground truth (all verified live 2026-06-12):**

| Country | Metric | Source | Verified detail |
|---|---|---|---|
| NO coverage | andel 80+ med hjemmetjeneste | SSB KOSTRA 12209, var `KOShjtj80aarover0001`, via **generic pxweb source** (explicit query, no metadata discovery → fully cacheable/offline) | v1 already uses this table |
| NO ageing | 80+ population growth 2019→2023 | SSB 07459, 1-year ages 80+, generic pxweb | v1 table |
| NO context | legekonsultasjoner (takst 2ad) growth | KUHR `fagomraade=LE`, 2019→2023 | G1 adapter, values verified |
| SE coverage | Invånare 80+ med hemtjänst i ordinärt boende, andel (%) | **Kolada KPI `N21704`**, `GET https://api.kolada.se/v3/data/kpi/N21704/year/2023` → `{"values":[{"municipality":"0180","period":2023,"values":[{"gender":"T","value":16.8,…}]}]}`; municipality list at `/v3/municipality` (`type` `"K"`=kommun, `"L"`=region/riket, riket=`"0000"`), paginated via `next_url` | data probe returned Stockholm m.fl. |
| SE ageing | 80+ population growth | SCB PxWeb `POST https://api.scb.se/OV0104/v1/doris/sv/ssd/START/BE/BE0101/BE0101A/BefolkningNy` json-stat2; ages are 1-year codes `"80"…"99","100+"`; `ContentsCode=BE0101N1`; Region filter `all`/`*` returns riket+län+kommun → filter 4-digit client-side | live query returned json-stat2 |
| FI coverage | Säännöllisen kotihoidon 75+ asiakkaat, % vastaavan ikäisestä väestöstä | Sotkanet indicator **5513** (456/457 rows for 2019/2023; **3216 is dead — 0 rows**) | G1 adapter |
| FI ageing | 75+ count growth = share(**171**) × population(**127**) / 100 | Sotkanet 171 = "75 vuotta täyttäneet, % väestöstä", 127 = "Väestö 31.12." | both verified |

Kolada data origin: Socialstyrelsen/SCB statistics republished per kommun by RKA (Rådet för
främjande av kommunala analyser) — this satisfies the DECISIONS "Socialstyrelsen SE" intent;
the sdb REST API itself carries no äldreomsorg topic (G1 finding).

**Squeeze metric (exact):** per country `c`, per municipality:
`growth_pct = (elderly_latest − elderly_base) / elderly_base × 100`;
`z(x) = (x − mean_c(x)) / std_c(x)` with `ddof=0`, `z = 0` if `std == 0`;
`squeeze = z(growth_pct) − z(coverage)`; rank descending within country.
`high_squeeze_share` = share of municipalities with `growth_pct > median_c` AND
`coverage < median_c`. Municipalities missing either metric are dropped and counted in
`n_dropped` (published — honesty). Cross-country claim is ONLY about `high_squeeze_share`
and medians, with the comparability caveat.

**Conventions for the implementer:**
- `uv run` only; full suite green (`uv run pytest -q`, currently 184 passed + 3 deselected) before every commit; commits prefixed `G2:`, ending with:

```
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

- Capture scripts print literals → paste exactly what they print; never invent numbers.
- DECISIONS.md applies: every number in the report must be recomputed by the verify stage;
  bokmål report; «deskriptivt, ikke kausalt»; no first-mover claims.
- Engine rule: core gains only the three generic mechanisms named above. All
  nordisk-specific logic lives in `analyses/nordisk-omsorg/stages.py`.

**Execution notes (workspace policy):** sonnet implementers, opus reviewers, ≤10 agents.
Suggested grouping: Tasks 1+2+3 (core mechanisms, one agent) → Task 4 (capture+config) →
Tasks 5–8 (instance, one agent, sequential) → Task 9 (e2e) → review → Task 10 (live
publish + docs) → closing panel.

---

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `src/omsorgsradar/core/adapters/pxweb.py` | modify | `use_codes` + `label_columns` source options in `fetch`/`jsonstat2_to_df` |
| `src/omsorgsradar/pipeline.py` | modify | `--data-dir` / `--reports-dir` CLI flags (per-analysis output dirs) |
| `src/omsorgsradar/core/adapters/kolada.py` | create | SE municipal KPI adapter (Kolada v3) |
| `src/omsorgsradar/core/adapters/__init__.py` | modify | register kolada |
| `src/omsorgsradar/realness.py` | modify | Kolada host + adapter provenance |
| `src/omsorgsradar/core/contracts.py` | modify | `register_schema` (idempotent-if-identical) |
| `analyses/nordisk-omsorg/analysis.toml` | create | sources + stages + params |
| `analyses/nordisk-omsorg/stages.py` | create | nordisk analyze/verify/report + findings schema |
| `tests/core/test_kolada_adapter.py`, additions to `tests/core/test_pxweb_adapter.py`, `tests/core/test_contracts.py` | create/modify | core mechanism tests |
| `tests/test_nordisk_omsorg.py` | create | compute units, planted-hallucination, offline e2e |
| `tests/fixtures/kolada_*.json`, `tests/fixtures/scb_befolkning_fixture.json`, `tests/fixtures/sotkanet_{5513,171,127}_fixture.json`, `tests/fixtures/ssb_{12209,07459}_g2_fixture.json`, `tests/fixtures/kuhr_le_2ad_g2_fixture.json` | create | captured live payloads, trimmed |
| `docs/adapters.md`, `status.md`, `DECISIONS.md`, `CLAUDE.md` | modify | docs current |

---

### Task 1: pxweb `use_codes`/`label_columns` + pipeline output-dir flags

**Files:**
- Modify: `src/omsorgsradar/core/adapters/pxweb.py`
- Modify: `src/omsorgsradar/pipeline.py` (argparse only)
- Test: `tests/core/test_pxweb_adapter.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/core/test_pxweb_adapter.py`:

```python
class TestFetchOptions:
    def _payload(self) -> dict:
        return {
            "dimension": {
                "Region": {"category": {
                    "index": {"0301": 0, "1505": 1},
                    "label": {"0301": "Oslo", "1505": "Kristiansund"},
                }},
            },
            "id": ["Region"],
            "size": [2],
            "value": [10.0, 20.0],
        }

    def test_use_codes_and_labels(self, tmp_path: Path) -> None:
        (tmp_path / "t1.json").write_text(json.dumps(self._payload()), encoding="utf-8")
        adapter = PxWebAdapter(base_url="http://127.0.0.1:9/x", cache_dir=tmp_path)
        source = {"table": "ignored", "cache_key": "t1",
                  "use_codes": True, "label_columns": True}
        df = adapter.fetch(source)
        assert df["Region"].tolist() == ["0301", "1505"]
        assert df["Region_label"].tolist() == ["Oslo", "Kristiansund"]

    def test_default_fetch_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "t2.json").write_text(json.dumps(self._payload()), encoding="utf-8")
        adapter = PxWebAdapter(base_url="http://127.0.0.1:9/x", cache_dir=tmp_path)
        df = adapter.fetch({"table": "ignored", "cache_key": "t2"})
        assert df["Region"].tolist() == ["Oslo", "Kristiansund"]  # v1 label behavior
        assert "Region_label" not in df.columns
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/core/test_pxweb_adapter.py -q`
Expected: FAIL (`label_columns` unknown → no `Region_label` column / codes not returned).

- [ ] **Step 3: Implement.** In `jsonstat2_to_df`, add a `label_columns: bool = False`
parameter. Build, per dimension, BOTH ordered code list and ordered label list; emit the
main column per `use_codes`, and when `label_columns=True` also emit `f"{dim_id}_label"`:

```python
def jsonstat2_to_df(
    payload: dict[str, Any],
    use_codes: bool = False,
    label_columns: bool = False,
) -> pd.DataFrame:
    # ... (docstring: add the two args; keep existing text)
    dims = payload["dimension"]
    dim_ids: list[str] = payload["id"]
    dim_sizes: list[int] = payload["size"]
    values: list[float | None] = payload["value"]

    import itertools

    code_lists: list[list[str]] = []
    label_lists: list[list[str]] = []
    for dim_id, size in zip(dim_ids, dim_sizes):
        cats = dims[dim_id]["category"]
        label_map = cats.get("label", {})
        index_map = cats.get("index", {})
        if isinstance(index_map, dict):
            ordered = sorted(index_map.items(), key=lambda x: x[1])
            ordered_ids = [k for k, _ in ordered]
        else:
            ordered_ids = list(index_map)
        code_lists.append(ordered_ids)
        label_lists.append([label_map.get(k, k) for k in ordered_ids])

    main_lists = code_lists if use_codes else label_lists
    rows = list(itertools.product(*main_lists))
    df = pd.DataFrame(rows, columns=dim_ids)
    if label_columns:
        label_rows = list(itertools.product(*label_lists))
        for i, dim_id in enumerate(dim_ids):
            df[f"{dim_id}_label"] = [r[i] for r in label_rows]
    df["value"] = values
    return df
```

In `PxWebAdapter.fetch`, replace the final line:

```python
        return jsonstat2_to_df(
            payload,
            use_codes=bool(source.get("use_codes", False)),
            label_columns=bool(source.get("label_columns", False)),
        )
```

- [ ] **Step 4: pipeline CLI flags.** In `pipeline.py` `main()`, add:

```python
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                        help="artifact dir for this analysis (default: data/)")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR),
                        help="report dir for this analysis (default: reports/)")
```
and pass them through:
```python
    run_pipeline(
        args.analysis_dir,
        data_dir=args.data_dir,
        reports_dir=args.reports_dir,
        skip_ingest=args.skip_ingest,
        skip_ml=args.skip_ml,
    )
```
(Needed so the nordisk live run does not overwrite v1's `data/quality_profile.json` /
`reports/` artifacts.)

- [ ] **Step 5:** `uv run pytest -q` → all green (186 expected). **Commit:**
```bash
git add src/omsorgsradar/core/adapters/pxweb.py src/omsorgsradar/pipeline.py tests/core/test_pxweb_adapter.py
git commit -m "G2: pxweb use_codes/label_columns options + per-analysis output-dir CLI flags"
```

---

### Task 2: Kolada adapter (SE)

**Files:**
- Create: `src/omsorgsradar/core/adapters/kolada.py`
- Modify: `src/omsorgsradar/core/adapters/__init__.py`, `src/omsorgsradar/realness.py`
- Create: `tests/fixtures/kolada_municipalities_fixture.json`, `tests/fixtures/kolada_n21704_fixture.json`
- Test: `tests/core/test_kolada_adapter.py`

- [ ] **Step 1: Capture fixtures (live)**

```bash
uv run python - <<'EOF'
import json, requests
BASE = "https://api.kolada.se/v3"
KEEP = {"0180", "1480", "1280", "0580", "2480"}  # Sthlm, Gbg, Malmö, Linköping, Umeå
muni, url = [], f"{BASE}/municipality?per_page=500"
while url:
    page = requests.get(url, headers={"Accept": "application/json"}, timeout=60).json()
    muni.extend(page["values"])
    url = page.get("next_url")
trimmed = ([m for m in muni if m["id"] in KEEP]
           + [m for m in muni if m["type"] == "L"][:2])  # L-entries prove filtering
json.dump(trimmed, open("tests/fixtures/kolada_municipalities_fixture.json", "w"),
          ensure_ascii=False, indent=1)
data = requests.get(f"{BASE}/data/kpi/N21704/year/2023",
                    headers={"Accept": "application/json"}, timeout=60).json()
rows = [v for v in data["values"] if v["municipality"] in KEEP]
json.dump(rows, open("tests/fixtures/kolada_n21704_fixture.json", "w"), indent=1)
sthlm = next(v for v in rows if v["municipality"] == "0180")
tot = next(x["value"] for x in sthlm["values"] if x["gender"] == "T")
print("PASTE INTO TEST — Stockholm N21704 2023 (gender T):", tot)
EOF
```
Expected: two fixtures; one `PASTE INTO TEST` line (probe on 2026-06-12 showed riket=16.8;
Stockholm will differ — paste what prints).

- [ ] **Step 2: Failing tests** — `tests/core/test_kolada_adapter.py`:

```python
"""Kolada (SE municipal KPI) adapter — offline via pre-seeded cache."""

import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.kolada import KoladaAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Paste literal printed by the capture script (Task 2 / Step 1):
STHLM_N21704_2023 = 0.0  # <- replace


def seeded_adapter(tmp_path: Path) -> KoladaAdapter:
    shutil.copy(FIXTURE_DIR / "kolada_municipalities_fixture.json",
                tmp_path / "kolada_municipalities.json")
    shutil.copy(FIXTURE_DIR / "kolada_n21704_fixture.json",
                tmp_path / "kolada_N21704_2023.json")
    return KoladaAdapter(base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path)


class TestMunicipalities:
    def test_kommun_type_only(self, tmp_path: Path) -> None:
        kommun = seeded_adapter(tmp_path).municipalities()
        assert len(kommun) == 5            # the two type-L entries are excluded
        assert kommun["0180"] == "Stockholm"


class TestFetch:
    SOURCE = {"adapter": "kolada", "id": "se_hemtjanst",
              "kpi": "N21704", "years": [2023]}

    def test_tidy_known_value(self, tmp_path: Path) -> None:
        df = seeded_adapter(tmp_path).fetch(self.SOURCE)
        assert list(df.columns) == ["country", "geo_code", "geo_id", "geo_name",
                                    "aar", "indicator", "gender", "value"]
        assert set(df["country"]) == {"SE"}
        assert set(df["gender"]) == {"T"}
        assert set(df["indicator"]) == {"kolada_N21704"}
        sthlm = df[df["geo_id"] == "SE-0180"]
        assert len(sthlm) == 1
        assert sthlm.iloc[0]["geo_name"] == "Stockholm"
        assert sthlm.iloc[0]["aar"] == 2023
        assert sthlm.iloc[0]["value"] == STHLM_N21704_2023

    def test_missing_year_gives_empty_tidy_df(self, tmp_path: Path) -> None:
        ad = seeded_adapter(tmp_path)
        (tmp_path / "kolada_N21704_1999.json").write_text('{"values": []}')
        df = ad.fetch({"adapter": "kolada", "id": "x", "kpi": "N21704", "years": [1999]})
        assert df.empty and "geo_id" in df.columns


class TestRegistry:
    def test_kolada_registered_with_required_fields(self, tmp_path: Path) -> None:
        from omsorgsradar.core.adapters import (
            REQUIRED_SOURCE_FIELDS, make_adapter, validate_source,
        )
        from omsorgsradar.core.config import ConfigError

        assert REQUIRED_SOURCE_FIELDS["kolada"] == ("kpi", "years")
        with pytest.raises(ConfigError, match="missing required"):
            validate_source({"id": "x", "adapter": "kolada"})
        ad = make_adapter({"id": "x", "adapter": "kolada",
                           "kpi": "N21704", "years": [2023]}, cache_dir=tmp_path)
        assert ad.source_id == "kolada"

    def test_kolada_provenance_resolves(self) -> None:
        from omsorgsradar.realness import resolve_provenance
        prov = resolve_provenance({"id": "x", "adapter": "kolada"})
        assert prov is not None and "Kolada" in prov["institution"]


@pytest.mark.live
class TestLive:
    def test_live_n21704_has_many_kommuner(self) -> None:
        df = KoladaAdapter().fetch({"adapter": "kolada", "id": "live",
                                    "kpi": "N21704", "years": [2023]})
        assert df["geo_id"].nunique() > 250   # 290 Swedish kommuner
```

Run: `uv run pytest tests/core/test_kolada_adapter.py -q` → ModuleNotFoundError.

- [ ] **Step 3: Implement** `src/omsorgsradar/core/adapters/kolada.py`:

```python
"""Kolada (RKA, Sweden) municipal-KPI adapter — v3 REST API.

API verified live 2026-06-12:
- data: GET {base}/data/kpi/{kpi}/year/{year} ->
  {"values":[{"kpi":"N21704","period":2023,"municipality":"0180",
    "values":[{"gender":"T","value":16.8,"count":1,"status":"",…},
              {"gender":"M",…},{"gender":"K",…}]}, …]}
  municipality "0000" = riket; type "L" entries are regions.
- municipalities: GET {base}/municipality?per_page=500 (paginated via next_url) ->
  {"values":[{"id":"0180","title":"Stockholm","type":"K"}, …]}

Data origin: Socialstyrelsen/SCB official statistics republished per kommun by
RKA (Rådet för främjande av kommunala analyser) — open data, no auth. Used for
SE elder-care coverage because the Socialstyrelsen sdb API has no äldreomsorg
topic (verified 2026-06-12, see socialstyrelsen adapter docstring).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests

from ..geo import make_geo_id
from .cache import DEFAULT_TIMEOUT, JsonCache

logger = logging.getLogger(__name__)

TIDY_COLUMNS = ["country", "geo_code", "geo_id", "geo_name",
                "aar", "indicator", "gender", "value"]
MAX_MUNI_PAGES = 10


class KoladaAdapter:
    source_id = "kolada"
    DEFAULT_BASE_URL = "https://api.kolada.se/v3"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout

    def _get_json(self, url: str, cache_key: str | None) -> Any:
        if cache_key is not None:
            cached = self.cache.load(cache_key)
            if cached is not None:
                return cached
        logger.info("GET %s", url)
        resp = requests.get(url, headers={"Accept": "application/json"},
                            timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if cache_key is not None:
            self.cache.save(cache_key, data)
        return data

    def municipalities(self) -> dict[str, str]:
        """kommun code ('0180') -> name; type 'L' (regions/riket) excluded."""
        entries = self.cache.load("kolada_municipalities")
        if entries is None:
            entries = []
            url: str | None = f"{self.base_url}/municipality?per_page=500"
            for _ in range(MAX_MUNI_PAGES):
                if url is None:
                    break
                page = self._get_json(url, cache_key=None)
                entries.extend(page.get("values", []))
                url = page.get("next_url")
            self.cache.save("kolada_municipalities", entries)
        return {m["id"]: m["title"] for m in entries if m.get("type") == "K"}

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        kpi = str(source["kpi"])
        gender = str(source.get("gender", "T"))
        kommun = self.municipalities()
        rows: list[dict[str, Any]] = []
        for year in source["years"]:
            year = int(year)
            payload = self._get_json(
                f"{self.base_url}/data/kpi/{kpi}/year/{year}",
                cache_key=f"kolada_{kpi}_{year}",
            )
            for m in payload.get("values", []):
                code = str(m.get("municipality", ""))
                if code not in kommun:
                    continue  # riket "0000" + type-L regions
                for v in m.get("values", []):
                    if v.get("gender") == gender and v.get("value") is not None:
                        rows.append({
                            "geo_code": code,
                            "geo_name": kommun[code],
                            "aar": int(m["period"]),
                            "value": float(v["value"]),
                        })
        if not rows:
            return pd.DataFrame(columns=TIDY_COLUMNS)
        df = pd.DataFrame(rows)
        df["country"] = "SE"
        df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("SE", c))
        df["indicator"] = f"kolada_{kpi}"
        df["gender"] = gender
        logger.info("Kolada %s: %d rows, %d kommuner, years %s",
                    kpi, len(df), df["geo_id"].nunique(),
                    sorted(df["aar"].unique().tolist()))
        return df[TIDY_COLUMNS]
```

- [ ] **Step 4: Register.** In `core/adapters/__init__.py`: add
`from .kolada import KoladaAdapter` beside the other imports; add
`"kolada": ("kpi", "years"),` to `REQUIRED_SOURCE_FIELDS`; add the factory

```python
def _make_kolada(source, *, cache_dir=None, base_dir=None) -> "KoladaAdapter":
    return KoladaAdapter(
        base_url=source.get("base_url", KoladaAdapter.DEFAULT_BASE_URL),
        cache_dir=cache_dir,
    )
```
and `"kolada": _make_kolada,` in `ADAPTER_FACTORIES`.

In `realness.py`: add to `KNOWN_HOSTS` (BOTH lines — `api.scb.se` is required because the
`se_befolkning` source sets that `base_url` explicitly, and an unknown host with explicit
`base_url` FAILs provenance → the realness gate would abort the whole nordisk pipeline):
```python
    "api.kolada.se": "Kolada / RKA (Socialstyrelsen- og SCB-data per kommun)",
    "api.scb.se": "Statistiska centralbyrån (SCB)",
```
Add a matching unit test beside `test_kolada_provenance_resolves`:
```python
    def test_scb_host_provenance_resolves(self) -> None:
        from omsorgsradar.realness import resolve_provenance
        prov = resolve_provenance({
            "id": "x", "adapter": "pxweb",
            "base_url": "https://api.scb.se/OV0104/v1/doris/sv/ssd/START/BE/BE0101/BE0101A",
        })
        assert prov is not None and "SCB" in prov["institution"]
```
and to `ADAPTER_PROVENANCE`:
```python
    "kolada": {"institution": "Kolada / RKA (Socialstyrelsen- og SCB-data per kommun)",
               "url": "https://api.kolada.se/v3"},
```

- [ ] **Step 5:** `uv run pytest -q` green; `uv run pytest tests/core/test_kolada_adapter.py -m live -q` → 1 passed. **Commit:**
```bash
git add src/omsorgsradar/core/adapters/kolada.py src/omsorgsradar/core/adapters/__init__.py src/omsorgsradar/realness.py tests/core/test_kolada_adapter.py tests/fixtures/kolada_municipalities_fixture.json tests/fixtures/kolada_n21704_fixture.json
git commit -m "G2: Kolada (SE) adapter — kommun KPIs, type-K filter, known-value test"
```

---

### Task 3: `contracts.register_schema` (instance schema extension)

**Files:**
- Modify: `src/omsorgsradar/core/contracts.py`
- Test: `tests/core/test_contracts.py` (append)

- [ ] **Step 1: Failing tests** — append to `tests/core/test_contracts.py`:

```python
class TestRegisterSchema:
    DUMMY = {"type": "object", "required": ["x"],
             "properties": {"x": {"type": "integer"}}}

    def test_register_validate_roundtrip(self) -> None:
        from omsorgsradar.core.contracts import (
            ArtifactValidationError, SCHEMAS, register_schema, validate_artifact,
        )
        try:
            register_schema("g2_dummy", self.DUMMY)
            validate_artifact("g2_dummy", {"x": 1})
            with pytest.raises(ArtifactValidationError):
                validate_artifact("g2_dummy", {"x": "nope"})
        finally:
            SCHEMAS.pop("g2_dummy", None)

    def test_identical_reregistration_is_idempotent(self) -> None:
        from omsorgsradar.core.contracts import SCHEMAS, register_schema
        try:
            register_schema("g2_dummy", self.DUMMY)
            register_schema("g2_dummy", self.DUMMY)  # extension reload — no raise
        finally:
            SCHEMAS.pop("g2_dummy", None)

    def test_conflicting_reregistration_raises(self) -> None:
        from omsorgsradar.core.contracts import SCHEMAS, register_schema
        try:
            register_schema("g2_dummy", self.DUMMY)
            with pytest.raises(ValueError, match="already registered"):
                register_schema("g2_dummy", {"type": "object"})
        finally:
            SCHEMAS.pop("g2_dummy", None)

    def test_core_schema_protected(self) -> None:
        from omsorgsradar.core.contracts import register_schema
        with pytest.raises(ValueError, match="already registered"):
            register_schema("findings", {"type": "object"})
```

- [ ] **Step 2:** run → ImportError on `register_schema`.

- [ ] **Step 3: Implement** — add to `contracts.py` after the `SCHEMAS` dict:

```python
def register_schema(name: str, schema: dict[str, Any]) -> None:
    """Register an artifact schema (instance extension point).

    ``analyses/<name>/stages.py`` registers schemas for its custom artifacts so
    they flow through the same ``validate_artifact`` path as core artifacts.
    Re-registering the identical schema is a no-op (extension modules are
    re-imported on every pipeline run); a conflicting redefinition raises.
    """
    if name in SCHEMAS:
        if SCHEMAS[name] == schema:
            return
        raise ValueError(f"artifact schema '{name}' already registered with a different definition")
    SCHEMAS[name] = schema
```

- [ ] **Step 4:** `uv run pytest tests/core/test_contracts.py -q` green; full suite green. **Commit:**
```bash
git add src/omsorgsradar/core/contracts.py tests/core/test_contracts.py
git commit -m "G2: contracts.register_schema — instances register their artifact schemas"
```

---

### Task 4: Fixture capture + `analyses/nordisk-omsorg/analysis.toml`

**Files:**
- Create: `analyses/nordisk-omsorg/analysis.toml`
- Create: `tests/fixtures/ssb_12209_g2_fixture.json`, `tests/fixtures/ssb_07459_g2_fixture.json`, `tests/fixtures/scb_befolkning_fixture.json`, `tests/fixtures/sotkanet_5513_fixture.json`, `tests/fixtures/sotkanet_171_fixture.json`, `tests/fixtures/sotkanet_127_g2_fixture.json`, `tests/fixtures/kuhr_le_2ad_g2_fixture.json`

- [ ] **Step 1: Pin SSB variable codes (live metadata, one call each)**

```bash
uv run python - <<'EOF'
import requests
for tid in ("12209", "07459"):
    meta = requests.get(f"https://data.ssb.no/api/v0/no/table/{tid}", timeout=60).json()
    print(f"== {tid}:", [v["code"] for v in meta["variables"]])
    for v in meta["variables"]:
        if v["code"] in ("Alder", "alder"):
            ages = [a for a in v["values"] if a.isdigit() and int(a) >= 80]
            print("PASTE — 07459 80+ age codes:", ages)
        if v["code"] in ("Tid",):
            print(f"   {tid} years tail:", v["values"][-6:])
EOF
```
Expected: variable code lists (12209 region code is `KOKkommuneregion0000`; verify) and the
explicit 80+ age-code list for 07459 (historically `"080"… "105"` — paste what prints).

- [ ] **Step 2: Write `analyses/nordisk-omsorg/analysis.toml`** (paste the printed age
codes into `no_befolkning`'s Alder values; adjust region/time codes ONLY if Step 1 printed
different ones):

```toml
[analysis]
name = "nordisk-omsorg"
question = "Hvilke kommuner får den hardeste skvisen mellom aldring og hjemmetjenestekapasitet — og ser mønsteret bedre ut i Norge enn i Sverige og Finland?"
language = "nb"

[stages]
list = ["ingest", "profile", "analyze", "verify", "report"]

[params]
base_year = 2019
latest_year = 2023
top_n = 10

# ── Norge: dekning (KOSTRA 12209) ────────────────────────────────────────────
[[sources]]
adapter = "pxweb"
id = "no_kostra"
base_url = "https://data.ssb.no/api/v0/no/table"
table = "12209"
cache_key = "nordisk_no_kostra_12209"
use_codes = true
label_columns = true

[sources.query]
response = { format = "json-stat2" }

[[sources.query.query]]
code = "KOKkommuneregion0000"
selection = { filter = "all", values = ["*"] }

[[sources.query.query]]
code = "ContentsCode"
selection = { filter = "item", values = ["KOShjtj80aarover0001"] }

[[sources.query.query]]
code = "Tid"
selection = { filter = "item", values = ["2019", "2023"] }

# ── Norge: 80+ befolkning (07459) ────────────────────────────────────────────
[[sources]]
adapter = "pxweb"
id = "no_befolkning"
base_url = "https://data.ssb.no/api/v0/no/table"
table = "07459"
cache_key = "nordisk_no_befolkning_07459"
use_codes = true
label_columns = true

[sources.query]
response = { format = "json-stat2" }

[[sources.query.query]]
code = "Region"
selection = { filter = "all", values = ["*"] }

[[sources.query.query]]
code = "Alder"
selection = { filter = "item", values = [] }   # <- paste printed 80+ age codes

[[sources.query.query]]
code = "Tid"
selection = { filter = "item", values = ["2019", "2023"] }

# ── Norge: kontekst — legekonsultasjoner (KUHR) ──────────────────────────────
[[sources]]
adapter = "kuhr"
id = "no_kuhr"
fagomraade = "LE"
fomar = 2019
tomar = 2023
takstkoder = ["2ad"]

# ── Sverige: hemtjänst-dekning 80+ (Kolada N21704) ───────────────────────────
[[sources]]
adapter = "kolada"
id = "se_hemtjanst"
kpi = "N21704"
years = [2023]

# ── Sverige: 80+ befolkning (SCB BefolkningNy) ───────────────────────────────
[[sources]]
adapter = "pxweb"
id = "se_befolkning"
base_url = "https://api.scb.se/OV0104/v1/doris/sv/ssd/START/BE/BE0101/BE0101A"
table = "BefolkningNy"
cache_key = "nordisk_se_befolkning"
use_codes = true
label_columns = true

[sources.query]
response = { format = "json-stat2" }

[[sources.query.query]]
code = "Region"
selection = { filter = "all", values = ["*"] }

[[sources.query.query]]
code = "Alder"
selection = { filter = "item", values = [
  "80", "81", "82", "83", "84", "85", "86", "87", "88", "89",
  "90", "91", "92", "93", "94", "95", "96", "97", "98", "99", "100+",
] }

[[sources.query.query]]
code = "ContentsCode"
selection = { filter = "item", values = ["BE0101N1"] }

[[sources.query.query]]
code = "Tid"
selection = { filter = "item", values = ["2019", "2023"] }

# ── Finland: kotihoito-dekning 75+ (Sotkanet 5513; 3216 er død) ──────────────
[[sources]]
adapter = "sotkanet"
id = "fi_homecare"
indicators = [5513]
years = [2023]

# ── Finland: 75+-andel og total befolkning (Sotkanet 171 + 127) ──────────────
[[sources]]
adapter = "sotkanet"
id = "fi_elderly_share"
indicators = [171]
years = [2019, 2023]

[[sources]]
adapter = "sotkanet"
id = "fi_population"
indicators = [127]
years = [2019, 2023]
```

- [ ] **Step 3: Validate config loads**

Run: `uv run python -c "from omsorgsradar.core.config import load_run_config; c = load_run_config('analyses/nordisk-omsorg', 'workflow.toml'); print(c.name, [s['id'] for s in c.sources])"`
Expected: `nordisk-omsorg ['no_kostra', 'no_befolkning', 'no_kuhr', 'se_hemtjanst', 'se_befolkning', 'fi_homecare', 'fi_elderly_share', 'fi_population']`

- [ ] **Step 4: Capture all pipeline fixtures (live, then trim)** — this script fetches
through the REAL adapters (so cache keys are computed by the same code the pipeline uses),
then trims the cached payloads to a small municipality subset for the committed fixtures:

```bash
uv run python - <<'EOF'
import json, shutil
from pathlib import Path
from omsorgsradar.core.config import load_run_config
from omsorgsradar.core.adapters import make_adapter

CACHE = Path("data/nordisk-omsorg/cache")
FIX = Path("tests/fixtures")
cfg = load_run_config("analyses/nordisk-omsorg", "workflow.toml")
for src in cfg.sources:
    ad = make_adapter(src, cache_dir=CACHE, base_dir=cfg.analysis_dir)
    df = ad.fetch(src)
    print(f"{src['id']}: {len(df)} rows, cols={list(df.columns)[:6]}")

# Trim cached payloads -> committed fixtures.
NO_KEEP = {"0301", "1103", "1505", "3025", "5001"}   # Oslo, Stavanger, Kristiansund, Asker, Trondheim
SE_KEEP = {"0180", "1480", "1280", "0580", "2480"}
FI_KEEP_CODES = {"091", "049", "837", "853", "564"}

def trim_jsonstat(key, regiondim, keep, out):
    p = json.loads((CACHE / f"{key}.json").read_text(encoding="utf-8"))
    # json-stat2 trimming is fiddly; commit the FULL payload if < 2 MB instead:
    size = (CACHE / f"{key}.json").stat().st_size
    print(f"{key}: {size/1e6:.2f} MB -> committing full payload" if size < 2e6
          else f"{key}: {size/1e6:.2f} MB TOO BIG — STOP and report")
    shutil.copy(CACHE / f"{key}.json", out)

trim_jsonstat("nordisk_no_kostra_12209", "KOKkommuneregion0000", NO_KEEP,
              FIX / "ssb_12209_g2_fixture.json")
trim_jsonstat("nordisk_no_befolkning_07459", "Region", NO_KEEP,
              FIX / "ssb_07459_g2_fixture.json")
trim_jsonstat("nordisk_se_befolkning", "Region", SE_KEEP,
              FIX / "scb_befolkning_fixture.json")

regions = json.loads((CACHE / "sotkanet_regions.json").read_text(encoding="utf-8"))
fi_ids = {r["id"] for r in regions if r.get("category") == "KUNTA"
          and r["code"] in FI_KEEP_CODES}
for ind, key in ((5513, "sotkanet_5513_2023_total"),
                 (171, "sotkanet_171_2019-2023_total"),
                 (127, "sotkanet_127_2019-2023_total")):
    rows = json.loads((CACHE / f"{key}.json").read_text(encoding="utf-8"))
    json.dump([r for r in rows if r["region"] in fi_ids],
              open(FIX / f"sotkanet_{ind}{'_g2' if ind == 127 else ''}_fixture.json", "w"),
              indent=1)

kuhr = json.loads((CACHE / "kuhr_LE_2019_2023_t2ad.json").read_text(encoding="utf-8"))
kuhr["takstbruk"] = [t for t in kuhr["takstbruk"]
                     if t["behandler_kommunenr"] in NO_KEEP]
json.dump(kuhr, open(FIX / "kuhr_le_2ad_g2_fixture.json", "w"), indent=1)
print("fixtures written; check sizes with: ls -la tests/fixtures/")
EOF
```
Notes for the engineer:
- The json-stat2 payloads (`ssb_*`, `scb_*`) are committed **in full** when under 2 MB
  (trimming a cartesian json-stat2 payload correctly is error-prone; full payloads keep
  fixtures byte-true). If one exceeds 2 MB, STOP and report DONE_WITH_CONCERNS with sizes.
- Sotkanet fixture names: `sotkanet_5513_fixture.json`, `sotkanet_171_fixture.json`,
  `sotkanet_127_g2_fixture.json` (the G1 `sotkanet_127_fixture.json` for 2023-only stays).
- KUHR cache key for this source (no `kommuner` filter) is `kuhr_LE_2019_2023_t2ad` —
  verify with `ls data/nordisk-omsorg/cache/`.
- Add `data/nordisk-omsorg/` cache to nothing — it is already ignored via `data/cache/`?
  It is NOT (path differs): add `data/*/cache/` and `data/*/*.duckdb` to `.gitignore`.

- [ ] **Step 5: Commit**
```bash
git add analyses/nordisk-omsorg/analysis.toml tests/fixtures/ .gitignore
git commit -m "G2: nordisk-omsorg analysis config + live-captured fixtures (NO/SE/FI)"
```

---

### Task 5: Instance compute core (`stages.py` part 1) + findings schema

**Files:**
- Create: `analyses/nordisk-omsorg/stages.py`
- Test: `tests/test_nordisk_omsorg.py` (compute units)

- [ ] **Step 1: Failing unit tests** — `tests/test_nordisk_omsorg.py`:

```python
"""nordisk-omsorg instance: compute units, planted hallucination, offline e2e."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]


def load_instance():
    spec = importlib.util.spec_from_file_location(
        "nordisk_stages", REPO / "analyses" / "nordisk-omsorg" / "stages.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSqueezeTable:
    def small(self) -> pd.DataFrame:
        return pd.DataFrame({
            "geo_id": ["NO-0001", "NO-0002", "NO-0003", "NO-0004"],
            "geo_name": ["A", "B", "C", "D"],
            "coverage": [40.0, 30.0, 20.0, 10.0],
            "elderly_base": [100, 100, 100, 100],
            "elderly_latest": [100, 110, 120, 130],
        })

    def test_squeeze_orders_low_coverage_high_growth_first(self) -> None:
        mod = load_instance()
        out = mod.squeeze_table(self.small())
        # D: lowest coverage + highest growth -> rank 1; A: opposite -> rank 4
        assert out.sort_values("rank")["geo_name"].tolist() == ["D", "C", "B", "A"]
        assert out["growth_pct"].round(1).tolist() == [0.0, 10.0, 20.0, 30.0]

    def test_zero_std_gives_zero_z(self) -> None:
        mod = load_instance()
        df = self.small().assign(coverage=25.0)  # constant -> std 0
        out = mod.squeeze_table(df)
        assert (out["z_coverage"] == 0).all()

    def test_missing_rows_dropped_and_counted(self) -> None:
        mod = load_instance()
        df = self.small()
        df.loc[0, "coverage"] = np.nan
        out = mod.squeeze_table(df)
        assert len(out) == 3
        assert out.attrs["n_dropped"] == 1


class TestFindings:
    def tables(self) -> dict[str, pd.DataFrame]:
        mod = load_instance()
        base = TestSqueezeTable().small()
        return {
            "NO": mod.squeeze_table(base),
            "SE": mod.squeeze_table(base.assign(
                geo_id=["SE-0001", "SE-0002", "SE-0003", "SE-0004"])),
        }

    def test_findings_shape_and_schema(self) -> None:
        mod = load_instance()
        from omsorgsradar.core.contracts import validate_artifact
        findings = mod.findings_from_tables(
            self.tables(), params={"base_year": 2019, "latest_year": 2023, "top_n": 2},
            context={},
        )
        validate_artifact("nordic_findings", findings)  # schema registered on import
        no = findings["countries"]["NO"]
        assert no["n_municipalities"] == 4
        assert no["coverage_median"] == 25.0
        assert len(no["top_squeeze"]) == 2
        assert no["top_squeeze"][0]["geo_name"] == "D"
        assert findings["analysis_years"] == {"base": 2019, "latest": 2023}

    def test_high_squeeze_share(self) -> None:
        mod = load_instance()
        f = mod.findings_from_tables(
            self.tables(), params={"base_year": 2019, "latest_year": 2023, "top_n": 2},
            context={},
        )
        # growth>median AND coverage<median: C and D qualify -> 2/4
        assert f["countries"]["NO"]["high_squeeze_share"] == 0.5
```

Run: `uv run pytest tests/test_nordisk_omsorg.py -q` → FAIL (no stages.py).

- [ ] **Step 2: Implement the compute core** — create `analyses/nordisk-omsorg/stages.py`
(part 1 of 3; Tasks 6–8 append the stage functions and `register`):

```python
"""nordisk-omsorg instance stages — NO/SE/FI ageing vs home-care capacity.

Shadows core analyze/verify/report for this analysis only (G0 extension
point). All numbers in the report come from nordic_findings.json, which the
verify stage independently recomputes from nordic_table.csv (tool receipts).

Comparability (hard caveat, repeated in the report): NO/SE coverage is 80+,
FI is 75+; definitions differ per country. Squeeze scores are therefore
z-normalized WITHIN country; only patterns are compared across countries.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

import numpy as np
import pandas as pd

from omsorgsradar.core.contracts import (
    register_schema,
    validate_artifact,
    write_manifest,
)
from omsorgsradar.core.geo import make_geo_id
from omsorgsradar.core.registry import PipelineGateError, StageContext, StageRegistry
from omsorgsradar.kommune_mergers import normalize_knr_series

logger = logging.getLogger(__name__)

COUNTRY_AGE_CUT = {"NO": "80+", "SE": "80+", "FI": "75+"}

NORDIC_FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["countries", "analysis_years"],
    "properties": {
        "analysis_years": {
            "type": "object",
            "required": ["base", "latest"],
            "properties": {"base": {"type": "integer"}, "latest": {"type": "integer"}},
        },
        "countries": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["n_municipalities", "n_dropped", "coverage_median",
                             "growth_median", "high_squeeze_share", "age_cut",
                             "top_squeeze"],
                "properties": {
                    "n_municipalities": {"type": "integer"},
                    "n_dropped": {"type": "integer"},
                    "coverage_median": {"type": "number"},
                    "growth_median": {"type": "number"},
                    "high_squeeze_share": {"type": "number"},
                    "age_cut": {"type": "string"},
                    "top_squeeze": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["geo_id", "geo_name", "squeeze",
                                         "coverage", "growth_pct", "rank"],
                        },
                    },
                },
            },
        },
        "comparison": {
            "type": "object",
            "required": ["lowest_high_squeeze_share_country"],
        },
        "context": {"type": "object"},
    },
}
register_schema("nordic_findings", NORDIC_FINDINGS_SCHEMA)


# ── compute core (pure functions, unit-tested) ───────────────────────────────

def _z(series: pd.Series) -> pd.Series:
    std = float(series.std(ddof=0))
    if std == 0.0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def squeeze_table(df: pd.DataFrame) -> pd.DataFrame:
    """Add growth_pct, z-scores, squeeze, rank. Drops rows missing either
    metric; the drop count is in ``out.attrs['n_dropped']``."""
    out = df.copy()
    out["growth_pct"] = (
        (out["elderly_latest"] - out["elderly_base"]) / out["elderly_base"] * 100
    )
    n_before = len(out)
    out = out.dropna(subset=["coverage", "growth_pct"]).copy()
    out = out[np.isfinite(out["growth_pct"])]
    out.attrs["n_dropped"] = n_before - len(out)
    out["z_coverage"] = _z(out["coverage"])
    out["z_growth"] = _z(out["growth_pct"])
    out["squeeze"] = out["z_growth"] - out["z_coverage"]
    out = out.sort_values("squeeze", ascending=False).reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


def findings_from_tables(
    tables: Mapping[str, pd.DataFrame],
    params: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    countries: dict[str, Any] = {}
    for country, t in sorted(tables.items()):
        cov_med = float(t["coverage"].median())
        gro_med = float(t["growth_pct"].median())
        high = ((t["growth_pct"] > gro_med) & (t["coverage"] < cov_med))
        top_n = int(params.get("top_n", 10))
        countries[country] = {
            "n_municipalities": int(len(t)),
            "n_dropped": int(t.attrs.get("n_dropped", 0)),
            "coverage_median": round(cov_med, 2),
            "growth_median": round(gro_med, 2),
            "high_squeeze_share": round(float(high.mean()), 4),
            "age_cut": COUNTRY_AGE_CUT.get(country, "?"),
            "top_squeeze": [
                {
                    "geo_id": r.geo_id,
                    "geo_name": r.geo_name,
                    "squeeze": round(float(r.squeeze), 3),
                    "coverage": round(float(r.coverage), 2),
                    "growth_pct": round(float(r.growth_pct), 2),
                    "rank": int(r.rank),
                }
                for r in t.head(top_n).itertuples()
            ],
        }
    lowest = min(countries, key=lambda c: countries[c]["high_squeeze_share"])
    return {
        "analysis_years": {"base": int(params["base_year"]),
                           "latest": int(params["latest_year"])},
        "countries": countries,
        "comparison": {"lowest_high_squeeze_share_country": lowest},
        "context": dict(context),
    }
```

- [ ] **Step 3:** `uv run pytest tests/test_nordisk_omsorg.py -q` → unit tests pass.
Full suite green. **Commit:**
```bash
git add analyses/nordisk-omsorg/stages.py tests/test_nordisk_omsorg.py
git commit -m "G2: nordisk compute core — within-country z-squeeze + findings schema"
```

---

### Task 6: Country table builders + analyze stage

**Files:**
- Modify: `analyses/nordisk-omsorg/stages.py` (append)
- Test: `tests/test_nordisk_omsorg.py` (append)

- [ ] **Step 1: Failing test** — append to `tests/test_nordisk_omsorg.py`:

```python
def _fixture_datasets() -> dict[str, pd.DataFrame]:
    """Build the ingest-stage output by running the REAL adapters against the
    committed fixtures through a seeded cache (no network)."""
    import json as _json
    import shutil
    import tempfile

    from omsorgsradar.core.adapters import make_adapter
    from omsorgsradar.core.config import load_run_config

    tmp = Path(tempfile.mkdtemp())
    fx = REPO / "tests" / "fixtures"
    seeds = {
        "nordisk_no_kostra_12209.json": "ssb_12209_g2_fixture.json",
        "nordisk_no_befolkning_07459.json": "ssb_07459_g2_fixture.json",
        "nordisk_se_befolkning.json": "scb_befolkning_fixture.json",
        "sotkanet_regions.json": "sotkanet_regions_fixture.json",
        "sotkanet_5513_2023_total.json": "sotkanet_5513_fixture.json",
        "sotkanet_171_2019-2023_total.json": "sotkanet_171_fixture.json",
        "sotkanet_127_2019-2023_total.json": "sotkanet_127_g2_fixture.json",
        "kolada_municipalities.json": "kolada_municipalities_fixture.json",
        "kolada_N21704_2023.json": "kolada_n21704_fixture.json",
        "kuhr_LE_2019_2023_t2ad.json": "kuhr_le_2ad_g2_fixture.json",
    }
    for cache_name, fixture_name in seeds.items():
        shutil.copy(fx / fixture_name, tmp / cache_name)
    cfg = load_run_config(REPO / "analyses" / "nordisk-omsorg", REPO / "workflow.toml")
    return {
        src["id"]: make_adapter(
            src, cache_dir=tmp, base_dir=cfg.analysis_dir
        ).fetch(src)
        for src in cfg.sources
    }


class TestCountryTables:
    def test_build_country_tables_from_fixtures(self) -> None:
        mod = load_instance()
        datasets = _fixture_datasets()
        tables = mod.build_country_tables(
            datasets, params={"base_year": 2019, "latest_year": 2023}
        )
        assert set(tables) == {"NO", "SE", "FI"}
        for country, t in tables.items():
            assert len(t) >= 3, country          # 5 seeded municipalities, ≥3 survive
            assert t["coverage"].notna().all()
            assert t["geo_id"].str.startswith(country).all()
        # Kristiansund must be present and named (NO labels from label_columns)
        no = tables["NO"]
        assert "NO-1505" in set(no["geo_id"])
        assert "Kristiansund" in " ".join(no["geo_name"].tolist())
```

Run → FAIL (`build_country_tables` missing).

- [ ] **Step 2: Implement** — append to `analyses/nordisk-omsorg/stages.py`:

```python
# ── country table builders ───────────────────────────────────────────────────

def _no_table(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> pd.DataFrame:
    kostra = datasets["no_kostra"]
    pop = datasets["no_befolkning"]
    region_col = next(c for c in kostra.columns if "region" in c.lower())
    k = kostra[kostra[region_col].astype(str).str.fullmatch(r"\d{4}")].copy()
    k["knr"] = normalize_knr_series(k[region_col].astype(str).str.zfill(4))
    k["aar"] = pd.to_numeric(k["Tid"], errors="coerce")
    k["value"] = pd.to_numeric(k["value"], errors="coerce")
    cov = (k[k["aar"] == latest]
           .groupby("knr")
           .agg(coverage=("value", "mean"),
                geo_name=(f"{region_col}_label", "first"))
           .reset_index())

    p = pop[pop["Region"].astype(str).str.fullmatch(r"\d{4}")].copy()
    p["knr"] = normalize_knr_series(p["Region"].astype(str).str.zfill(4))
    p["aar"] = pd.to_numeric(p["Tid"], errors="coerce")
    p["value"] = pd.to_numeric(p["value"], errors="coerce")
    sums = (p.groupby(["knr", "aar"])["value"].sum().unstack())
    eld = pd.DataFrame({
        "knr": sums.index,
        "elderly_base": sums.get(base),
        "elderly_latest": sums.get(latest),
    }).reset_index(drop=True)

    out = cov.merge(eld, on="knr", how="inner")
    out["geo_id"] = out["knr"].map(lambda c: make_geo_id("NO", c))
    return out[["geo_id", "geo_name", "coverage", "elderly_base", "elderly_latest"]]


def _se_table(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> pd.DataFrame:
    hem = datasets["se_hemtjanst"]
    pop = datasets["se_befolkning"]
    cov = (hem[hem["aar"] == latest][["geo_id", "geo_name", "value"]]
           .rename(columns={"value": "coverage"}))

    p = pop[pop["Region"].astype(str).str.fullmatch(r"\d{4}")].copy()
    p["aar"] = pd.to_numeric(p["Tid"], errors="coerce")
    p["value"] = pd.to_numeric(p["value"], errors="coerce")
    p["geo_id"] = p["Region"].map(lambda c: make_geo_id("SE", c))
    sums = p.groupby(["geo_id", "aar"])["value"].sum().unstack()
    eld = pd.DataFrame({
        "geo_id": sums.index,
        "elderly_base": sums.get(base),
        "elderly_latest": sums.get(latest),
    }).reset_index(drop=True)

    return cov.merge(eld, on="geo_id", how="inner")[
        ["geo_id", "geo_name", "coverage", "elderly_base", "elderly_latest"]
    ]


def _fi_table(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> pd.DataFrame:
    care = datasets["fi_homecare"]
    share = datasets["fi_elderly_share"]
    popn = datasets["fi_population"]
    cov = (care[care["aar"] == latest][["geo_id", "geo_name", "value"]]
           .rename(columns={"value": "coverage"}))

    # 75+ count = share% x total population / 100, per kunta-year
    merged = share[["geo_id", "aar", "value"]].rename(columns={"value": "share"}).merge(
        popn[["geo_id", "aar", "value"]].rename(columns={"value": "pop"}),
        on=["geo_id", "aar"], how="inner",
    )
    merged["elderly"] = merged["share"] * merged["pop"] / 100.0
    sums = merged.pivot_table(index="geo_id", columns="aar", values="elderly")
    eld = pd.DataFrame({
        "geo_id": sums.index,
        "elderly_base": sums.get(base),
        "elderly_latest": sums.get(latest),
    }).reset_index(drop=True)

    return cov.merge(eld, on="geo_id", how="inner")[
        ["geo_id", "geo_name", "coverage", "elderly_base", "elderly_latest"]
    ]


def build_country_tables(
    datasets: Mapping[str, pd.DataFrame], params: Mapping[str, Any]
) -> dict[str, pd.DataFrame]:
    base, latest = int(params["base_year"]), int(params["latest_year"])
    return {
        "NO": _no_table(datasets, base, latest),
        "SE": _se_table(datasets, base, latest),
        "FI": _fi_table(datasets, base, latest),
    }


def kuhr_context(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> dict[str, Any]:
    """National KUHR context: GP consultation volume (takst 2ad) and change."""
    k = datasets.get("no_kuhr")
    if k is None or k.empty:
        return {}
    by_year = k.groupby("aar")["antall_regninger"].sum()
    if base not in by_year.index or latest not in by_year.index:
        return {}
    v_base, v_latest = float(by_year[base]), float(by_year[latest])
    return {
        "kuhr_konsultasjoner_latest": int(v_latest),
        "kuhr_konsultasjoner_change_pct": round((v_latest - v_base) / v_base * 100, 1),
    }


# ── analyze stage ────────────────────────────────────────────────────────────

def stage_analyze_nordisk(ctx: StageContext) -> None:
    params = ctx.config.params
    datasets = ctx.state["datasets"]
    tables = build_country_tables(datasets, params)
    squeezed = {c: squeeze_table(t) for c, t in tables.items()}

    full = pd.concat(
        [t.assign(country=c) for c, t in squeezed.items()], ignore_index=True
    )
    table_path = ctx.data_dir / "nordic_table.csv"
    full.to_csv(table_path, index=False)
    # attrs don't survive CSV — persist drop counts beside the table
    drops = {c: int(t.attrs.get("n_dropped", 0)) for c, t in squeezed.items()}
    (ctx.data_dir / "nordic_drops.json").write_text(
        json.dumps(drops), encoding="utf-8"
    )
    write_manifest(table_path, artifact="nordic_table", producer="analyze")

    context = kuhr_context(datasets, int(params["base_year"]), int(params["latest_year"]))
    findings = findings_from_tables(squeezed, params, context)
    findings_path = ctx.data_dir / "nordic_findings.json"
    findings_path.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validate_artifact("nordic_findings", findings)
    write_manifest(findings_path, artifact="nordic_findings", producer="analyze",
                   inputs=[str(table_path)])
    ctx.state["nordic_findings"] = findings
    ctx.artifacts["nordic_table"] = table_path
    ctx.artifacts["findings"] = findings_path
```

(Note: `nordic_table` has no entry in core SCHEMAS — `write_manifest` does not validate,
only `validate_artifact` does, and we only call that for `nordic_findings`. The CSV is
hashed in its manifest.)

- [ ] **Step 3:** `uv run pytest tests/test_nordisk_omsorg.py -q` → green. Full suite
green. **Commit:**
```bash
git add analyses/nordisk-omsorg/stages.py tests/test_nordisk_omsorg.py
git commit -m "G2: nordisk country tables + analyze stage (artifacts + manifests)"
```

---

### Task 7: Verify stage (independent recompute) + planted-hallucination test

**Files:**
- Modify: `analyses/nordisk-omsorg/stages.py` (append)
- Test: `tests/test_nordisk_omsorg.py` (append)

- [ ] **Step 1: Failing tests** — append:

```python
class TestNordiskVerify:
    def _run_analyze(self, tmp_path: Path):
        from omsorgsradar.core.config import load_run_config
        from omsorgsradar.core.journal import RunJournal
        from omsorgsradar.core.registry import StageContext

        mod = load_instance()
        cfg = load_run_config(REPO / "analyses" / "nordisk-omsorg",
                              REPO / "workflow.toml")
        journal = RunJournal.start(tmp_path / "runs", analysis="nordisk-omsorg",
                                   config_snapshot={})
        ctx = StageContext(config=cfg, data_dir=tmp_path,
                           reports_dir=tmp_path / "reports", journal=journal)
        ctx.state["datasets"] = _fixture_datasets()
        mod.stage_analyze_nordisk(ctx)
        return mod, ctx

    def test_verify_passes_on_honest_findings(self, tmp_path: Path) -> None:
        import json as _json
        mod, ctx = self._run_analyze(tmp_path)
        mod.stage_verify_nordisk(ctx)
        v = _json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
        assert v["verdict"] == "PASS"
        assert v["failed"] == 0
        assert v["total_claims"] >= 12  # >=4 claims x 3 countries

    def test_planted_hallucination_caught(self, tmp_path: Path) -> None:
        import json as _json
        from omsorgsradar.core.registry import PipelineGateError

        mod, ctx = self._run_analyze(tmp_path)
        f_path = tmp_path / "nordic_findings.json"
        findings = _json.loads(f_path.read_text(encoding="utf-8"))
        findings["countries"]["NO"]["coverage_median"] += 7.7   # plant the lie
        findings["countries"]["NO"]["top_squeeze"][0]["geo_id"] = "NO-9999"
        f_path.write_text(_json.dumps(findings, ensure_ascii=False),
                          encoding="utf-8")
        ctx.state["nordic_findings"] = findings
        with pytest.raises(PipelineGateError):
            mod.stage_verify_nordisk(ctx)
        v = _json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
        assert v["verdict"] == "FAIL"
        assert v["failed"] >= 2
```

Run → FAIL (`stage_verify_nordisk` missing).

- [ ] **Step 2: Implement** — append to `stages.py`. The verifier reads BOTH artifacts
from disk and recomputes every published number with INDEPENDENT inline pandas (not via
`findings_from_tables` — a shared bug must not self-certify):

```python
# ── verify stage (tool receipts: independent recompute from disk) ────────────

def _check(claims: list[dict[str, Any]], name: str, expected: Any, actual: Any,
           tol: float = 1e-6) -> None:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(float(expected) - float(actual)) <= tol
    else:
        ok = expected == actual
    claims.append({"claim": name, "expected": expected, "actual": actual, "ok": ok})


def stage_verify_nordisk(ctx: StageContext) -> None:
    findings = ctx.state.get("nordic_findings")
    if findings is None:
        findings = json.loads(
            (ctx.data_dir / "nordic_findings.json").read_text(encoding="utf-8")
        )
    table = pd.read_csv(ctx.data_dir / "nordic_table.csv")
    drops = json.loads(
        (ctx.data_dir / "nordic_drops.json").read_text(encoding="utf-8")
    )

    claims: list[dict[str, Any]] = []
    for country, c in findings["countries"].items():
        t = table[table["country"] == country]
        _check(claims, f"{country}.n_municipalities", c["n_municipalities"], len(t))
        _check(claims, f"{country}.n_dropped", c["n_dropped"], drops.get(country, 0))
        _check(claims, f"{country}.coverage_median", c["coverage_median"],
               round(float(t["coverage"].median()), 2), tol=0.005)
        _check(claims, f"{country}.growth_median", c["growth_median"],
               round(float(t["growth_pct"].median()), 2), tol=0.005)
        gro_med = float(t["growth_pct"].median())
        cov_med = float(t["coverage"].median())
        high = float(((t["growth_pct"] > gro_med) & (t["coverage"] < cov_med)).mean())
        _check(claims, f"{country}.high_squeeze_share", c["high_squeeze_share"],
               round(high, 4), tol=0.0005)
        top1 = t.sort_values("squeeze", ascending=False).iloc[0]
        _check(claims, f"{country}.top1_geo_id",
               c["top_squeeze"][0]["geo_id"], str(top1["geo_id"]))
        _check(claims, f"{country}.top1_squeeze",
               c["top_squeeze"][0]["squeeze"], round(float(top1["squeeze"]), 3),
               tol=0.005)

    shares = {k: v["high_squeeze_share"] for k, v in findings["countries"].items()}
    _check(claims, "comparison.lowest_high_squeeze_share_country",
           findings["comparison"]["lowest_high_squeeze_share_country"],
           min(shares, key=shares.get))

    failed = [c for c in claims if not c["ok"]]
    payload = {
        "verdict": "PASS" if not failed else "FAIL",
        "total_claims": len(claims),
        "passed": len(claims) - len(failed),
        "failed": len(failed),
        "failures": [
            f"{c['claim']}: findings={c['expected']!r} recomputed={c['actual']!r}"
            for c in failed
        ],
    }
    path = ctx.data_dir / "verification.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    validate_artifact("verification", payload)
    write_manifest(path, artifact="verification", producer="verify",
                   inputs=[str(ctx.data_dir / "nordic_findings.json"),
                           str(ctx.data_dir / "nordic_table.csv")])
    ctx.artifacts["verification"] = path
    ctx.state["nordic_verification"] = payload
    if payload["verdict"] != "PASS":
        raise PipelineGateError(
            f"nordisk verify FAIL: {payload['failed']}/{payload['total_claims']} "
            f"claims — {payload['failures'][:3]}"
        )
```

**Important:** the core pipeline's verify-before-report rule keys on the stage NAME
"verify" — the instance shadows that name in `register()` (Task 8), so the engine gate
semantics (`resolve_stage_list`, journal, abort) apply unchanged.

- [ ] **Step 3:** `uv run pytest tests/test_nordisk_omsorg.py -q` → green (incl. planted
test). Full suite green. **Commit:**
```bash
git add analyses/nordisk-omsorg/stages.py tests/test_nordisk_omsorg.py
git commit -m "G2: nordisk verify — independent recompute, planted-hallucination test green"
```

---

### Task 8: Bokmål report stage + figures + `register()`

**Files:**
- Modify: `analyses/nordisk-omsorg/stages.py` (append)
- Test: `tests/test_nordisk_omsorg.py` (append)

- [ ] **Step 1: Failing tests** — append:

```python
class TestNordiskReport:
    def test_report_renders_from_findings_only(self, tmp_path: Path) -> None:
        mod, ctx = TestNordiskVerify()._run_analyze(tmp_path)
        mod.stage_verify_nordisk(ctx)
        mod.stage_report_nordisk(ctx)
        report = (tmp_path / "reports" / "nordisk-omsorg_rapport.md").read_text(
            encoding="utf-8"
        )
        f = ctx.state["nordic_findings"]
        assert "deskriptivt, ikke kausalt" in report
        assert "75+" in report and "80+" in report      # comparability block
        for country in ("NO", "SE", "FI"):
            assert f["countries"][country]["top_squeeze"][0]["geo_name"] in report
            assert str(f["countries"][country]["coverage_median"]) in report
        assert f["comparison"]["lowest_high_squeeze_share_country"] in report
        figs = list((tmp_path / "reports" / "figures").glob("nordisk_*.png"))
        assert len(figs) == 3

    def test_report_refuses_without_green_verification(self, tmp_path: Path) -> None:
        from omsorgsradar.core.registry import PipelineGateError
        mod, ctx = TestNordiskVerify()._run_analyze(tmp_path)
        with pytest.raises(PipelineGateError):
            mod.stage_report_nordisk(ctx)   # no verification in state -> refuse


class TestRegister:
    def test_register_shadows_three_stages(self) -> None:
        from omsorgsradar.core.registry import StageRegistry
        from omsorgsradar.stages import build_default_registry

        mod = load_instance()
        reg = build_default_registry()
        mod.register(reg)
        assert reg.get("analyze") is mod.stage_analyze_nordisk
        assert reg.get("verify") is mod.stage_verify_nordisk
        assert reg.get("report") is mod.stage_report_nordisk
        assert reg.get("ingest") is not None    # core stages untouched
```

Run → FAIL.

- [ ] **Step 2: Implement** — append to `stages.py`:

```python
# ── report stage (bokmål; numbers ONLY from findings dict) ───────────────────

def _fig_scatter(table: pd.DataFrame, out_dir) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), sharey=False)
    for ax, country in zip(axes, ("NO", "SE", "FI")):
        t = table[table["country"] == country]
        ax.scatter(t["coverage"], t["growth_pct"], s=12, alpha=0.6)
        ax.axvline(t["coverage"].median(), ls="--", lw=0.8, color="grey")
        ax.axhline(t["growth_pct"].median(), ls="--", lw=0.8, color="grey")
        ax.set_title(f"{country} ({COUNTRY_AGE_CUT[country]})")
        ax.set_xlabel("Dekning hjemmetjeneste (%)")
    axes[0].set_ylabel("Vekst eldre befolkning (%)")
    fig.suptitle("Dekning vs. aldring per kommune — høy-skvis = nede til høyre? Nei: oppe til venstre")
    fig.tight_layout()
    p = out_dir / "nordisk_scatter.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def _fig_box(table: pd.DataFrame, out_dir) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    data = [table[table["country"] == c]["squeeze"] for c in ("NO", "SE", "FI")]
    ax.boxplot(data, tick_labels=["NO (80+)", "SE (80+)", "FI (75+)"])
    ax.set_ylabel("Skvis-skår (z-differanse, innen land)")
    ax.set_title("Fordeling av skvis-skår per land")
    fig.tight_layout()
    p = out_dir / "nordisk_skvis_fordeling.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def _fig_top_no(table: pd.DataFrame, out_dir, top_n: int) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = (table[table["country"] == "NO"]
         .sort_values("squeeze", ascending=False).head(top_n).iloc[::-1])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(t["geo_name"], t["squeeze"])
    ax.set_xlabel("Skvis-skår")
    ax.set_title(f"Topp {top_n} norske kommuner etter skvis-skår")
    fig.tight_layout()
    p = out_dir / "nordisk_topp_no.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def _country_section(name_nb: str, c: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {r['rank']} | {r['geo_name']} (`{r['geo_id']}`) | {r['squeeze']} "
        f"| {r['coverage']} | {r['growth_pct']} |"
        for r in c["top_squeeze"]
    )
    return f"""### {name_nb} (aldersgrense {c['age_cut']})

{c['n_municipalities']} kommuner i analysen ({c['n_dropped']} utelatt pga.
manglende data). Median dekning: **{c['coverage_median']} %**. Median vekst i
eldre befolkning: **{c['growth_median']} %**. Andel kommuner i
høy-skvis-kvadranten: **{c['high_squeeze_share']}**.

| # | Kommune | Skvis | Dekning (%) | Eldrevekst (%) |
|---|---------|-------|-------------|----------------|
{rows}
"""


def stage_report_nordisk(ctx: StageContext) -> None:
    verification = ctx.state.get("nordic_verification")
    if verification is None or verification.get("verdict") != "PASS":
        raise PipelineGateError(
            "nordisk report requires a green verification artifact"
        )
    findings = ctx.state["nordic_findings"]
    table = pd.read_csv(ctx.data_dir / "nordic_table.csv")
    fig_dir = ctx.reports_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    top_n = int(ctx.config.params.get("top_n", 10))
    figs = [_fig_scatter(table, fig_dir), _fig_box(table, fig_dir),
            _fig_top_no(table, fig_dir, top_n)]

    f = findings
    years = f["analysis_years"]
    comp = f["comparison"]["lowest_high_squeeze_share_country"]
    comp_nb = {"NO": "Norge", "SE": "Sverige", "FI": "Finland"}[comp]
    ctx_block = ""
    if f.get("context", {}).get("kuhr_konsultasjoner_latest"):
        ctx_block = (
            f"\nKontekst (KUHR, åpne helserefusjonsdata): "
            f"{f['context']['kuhr_konsultasjoner_latest']:,} fastlegekonsultasjoner "
            f"(takst 2ad) i {years['latest']}, en endring på "
            f"{f['context']['kuhr_konsultasjoner_change_pct']} % siden "
            f"{years['base']}.\n".replace(",", " ")
        )

    sections = "\n".join(
        _country_section(nb, f["countries"][cc])
        for cc, nb in (("NO", "Norge"), ("SE", "Sverige"), ("FI", "Finland"))
    )
    report = f"""# Nordisk omsorgsradar: aldring vs. hjemmetjenestekapasitet

**Spørsmål:** {ctx.config.analysis['analysis']['question']}

**Metode.** For hver kommune beregner vi (1) dekning av hjemmetjenester blant
eldre, (2) prosentvis vekst i eldre befolkning {years['base']}–{years['latest']},
og (3) en skvis-skår: z-skår for eldrevekst minus z-skår for dekning,
normalisert **innen hvert land**. Høy skår = sterk aldring kombinert med lav
dekning. Alle tall er beregnet av kode og kontrollregnet av en uavhengig
verifiseringsmodul før denne rapporten ble generert
({{verifisering: {ctx.state['nordic_verification']['passed']}/{ctx.state['nordic_verification']['total_claims']} kontroller OK}}).

## Funn per land

{sections}

## Sammenligning på tvers — med forbehold

Indikatorene er **ikke direkte sammenlignbare** mellom land: Norge og Sverige
måler dekning for 80+, Finland for 75+, og tjenestedefinisjonene er ulike.
Vi sammenligner derfor bare *mønstre innen land*. Andelen kommuner i
høy-skvis-kvadranten (eldrevekst over median OG dekning under median) er
lavest i **{comp_nb}**.
{ctx_block}
## Forbehold

- **Deskriptivt, ikke kausalt.** Analysen rangerer og beskriver; den forklarer ikke.
- Aldersgrenser: NO/SE 80+, FI 75+. Definisjoner av hjemmetjeneste varierer.
- Kommuner med manglende data er utelatt og talt opp per land (se tabellene).
- Datakilder: SSB (KOSTRA 12209, befolkning 07459), Kolada/RKA (N21704,
  Socialstyrelsen-data), SCB (BefolkningNy), THL Sotkanet (5513, 171, 127),
  Helsedirektoratet/NAV KUHR. Åpne data, lisenser tillater viderebruk.

## Figurer

{chr(10).join(f"![figur](figures/{name})" for name in figs)}

---

*Rapporten er generert av omsorgsradar-pipelinen; alle tall kommer fra
`nordic_findings.json` og er verifisert mot `nordic_table.csv`.*
"""
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.reports_dir / "nordisk-omsorg_rapport.md"
    path.write_text(report, encoding="utf-8")
    write_manifest(path, artifact="nordic_report", producer="report",
                   inputs=[str(ctx.data_dir / "nordic_findings.json")])
    ctx.artifacts["report"] = path
    logger.info("Nordisk rapport: %s", path)


# ── instance registration (G0 extension point) ───────────────────────────────

def register(registry: StageRegistry) -> None:
    registry.register("analyze", stage_analyze_nordisk, override=True)
    registry.register("verify", stage_verify_nordisk, override=True)
    registry.register("report", stage_report_nordisk, override=True)
```

- [ ] **Step 3:** `uv run pytest tests/test_nordisk_omsorg.py -q` → green. Full suite
green. **Commit:**
```bash
git add analyses/nordisk-omsorg/stages.py tests/test_nordisk_omsorg.py
git commit -m "G2: nordisk bokmål report + 3 figures + instance register()"
```

---

### Task 9: Offline e2e through the real pipeline

**Files:**
- Test: `tests/test_nordisk_omsorg.py` (append)

- [ ] **Step 1: Write the test**

```python
class TestNordiskE2E:
    def test_full_offline_pipeline(self, tmp_path: Path) -> None:
        import json as _json
        import shutil

        from omsorgsradar.pipeline import run_pipeline

        data_dir = tmp_path / "data"
        cache = data_dir / "cache"
        cache.mkdir(parents=True)
        fx = REPO / "tests" / "fixtures"
        seeds = {
            "nordisk_no_kostra_12209.json": "ssb_12209_g2_fixture.json",
            "nordisk_no_befolkning_07459.json": "ssb_07459_g2_fixture.json",
            "nordisk_se_befolkning.json": "scb_befolkning_fixture.json",
            "sotkanet_regions.json": "sotkanet_regions_fixture.json",
            "sotkanet_5513_2023_total.json": "sotkanet_5513_fixture.json",
            "sotkanet_171_2019-2023_total.json": "sotkanet_171_fixture.json",
            "sotkanet_127_2019-2023_total.json": "sotkanet_127_g2_fixture.json",
            "kolada_municipalities.json": "kolada_municipalities_fixture.json",
            "kolada_N21704_2023.json": "kolada_n21704_fixture.json",
            "kuhr_LE_2019_2023_t2ad.json": "kuhr_le_2ad_g2_fixture.json",
        }
        for cache_name, fixture_name in seeds.items():
            shutil.copy(fx / fixture_name, cache / cache_name)

        report = run_pipeline(
            REPO / "analyses" / "nordisk-omsorg",
            data_dir=data_dir,
            reports_dir=tmp_path / "reports",
            runs_dir=tmp_path / "runs",
        )
        assert report is not None and report.exists()

        v = _json.loads((data_dir / "verification.json").read_text(encoding="utf-8"))
        assert v["verdict"] == "PASS" and v["failed"] == 0

        q = _json.loads((data_dir / "quality_profile.json").read_text(encoding="utf-8"))
        for sid in ("no_kostra", "se_hemtjanst", "fi_homecare"):
            assert q["datasets"][sid]["realness"]["verdict"] in ("PASS", "WARN"), sid

        run_files = list((tmp_path / "runs").glob("*/run.json"))
        assert len(run_files) == 1
        run = _json.loads(run_files[0].read_text(encoding="utf-8"))
        assert run["status"] == "ok"
```

- [ ] **Step 2:** `uv run pytest tests/test_nordisk_omsorg.py::TestNordiskE2E -q` → 1
passed (this exercises ingest→profile→analyze→verify→report through the registry with the
instance extension loaded by `load_extensions`). If it fails on a cache-key mismatch, fix
the SEED FILENAME (inspect `data/nordisk-omsorg/cache/` from Task 4), never the adapter.
Full suite green.

- [ ] **Step 3: Commit**
```bash
git add tests/test_nordisk_omsorg.py
git commit -m "G2: nordisk offline e2e — full pipeline, verify PASS, realness green"
```

---

### Task 10: Live publish run + docs

**Files:**
- Modify: `docs/adapters.md`, `status.md`, `DECISIONS.md`, `CLAUDE.md`
- Commit: `data/nordisk-omsorg/*.json` artifacts + `reports/nordisk-omsorg/`

- [ ] **Step 1: Live run** (network; caches were already warmed in Task 4):

```bash
uv run python -m omsorgsradar.pipeline analyses/nordisk-omsorg \
  --data-dir data/nordisk-omsorg --reports-dir reports/nordisk-omsorg
```
Expected: pipeline completes, `reports/nordisk-omsorg/nordisk-omsorg_rapport.md` + 3
figures, `data/nordisk-omsorg/verification.json` verdict PASS. Read the report and check
the bokmål reads naturally; fix template wording if something is grammatically off
(template only — numbers come from findings).

- [ ] **Step 2: docs/adapters.md** — add after the csv section:

```markdown
## kolada — RKA, Sweden (municipal KPIs)
Required: `kpi` (e.g. "N21704"), `years` (list). Optional: `gender` ("T"), `base_url`.
API: `api.kolada.se/v3` — `/data/kpi/{kpi}/year/{year}` + `/municipality` (type K only;
riket "0000" and regions excluded). Data origin: Socialstyrelsen/SCB official statistics
republished per kommun by RKA. Used for SE elder-care because the sdb API has no
äldreomsorg topic.
```
and extend the pxweb section's optional fields: `use_codes` (codes instead of labels),
`label_columns` (adds `<dim>_label` columns), and the note: *tables with `/` in the path
(SCB-style) MUST set `cache_key` — slashes are rejected by the cache-key sanitizer.*

- [ ] **Step 3: DECISIONS.md** — replace the bullet

```markdown
- v2 first proof dataset: Nordic comparison (Sotkanet FI + Socialstyrelsen SE + KUHR NO) — not NHS EPD/BRFSS first.
```
with
```markdown
- v2 first proof dataset: Nordic comparison — Sotkanet (FI), Kolada/RKA (SE; Socialstyrelsen-data — sdb-API-et mangler äldreomsorg, verifisert 2026-06-12) + SCB, SSB/KUHR (NO). Not NHS EPD/BRFSS first.
- Cross-country comparisons are within-country-normalized patterns only; never compare indicator levels across countries (different age cuts/definitions).
```

- [ ] **Step 4: status.md** — append (fill N with the real final test count):

```markdown
- **2026-06-12** — **G2 (nordisk-omsorg) shipped.** First cross-country instance:
  `analyses/nordisk-omsorg/` (NO/SE/FI aldring vs. hjemmetjenestedekning per kommune,
  within-country z-skvis). Core gains: pxweb `use_codes`/`label_columns`, kolada adapter
  (SE — sdb-API-et mangler äldreomsorg), `contracts.register_schema`, pipeline
  `--data-dir`/`--reports-dir`. Instance shadows analyze/verify/report via G0 extension
  point; verify recomputes every published number independently from `nordic_table.csv`;
  planted-hallucination test green. Bokmål report + 3 figurer published from live run
  (`reports/nordisk-omsorg/`). Tests: 184 → N (offline) + live. **Next: G3 —
  /magic-analyze + /add-dataset skills (security gate: base_url allowlist + csv path
  containment are hard prerequisites — see spec).**
```

- [ ] **Step 5: CLAUDE.md** — update the Status line: G2 shipped, next G3.

- [ ] **Step 6: Final verification + commit**

Run: `uv run pytest -q` and `uv run pytest -m live -q` — record counts.
```bash
git add docs/adapters.md status.md DECISIONS.md CLAUDE.md data/nordisk-omsorg reports/nordisk-omsorg
git commit -m "G2: close out — live nordisk run published, docs + decisions updated"
```
(Note: `data/nordisk-omsorg/cache/` and `*.duckdb` must remain ignored — verify with
`git status` before committing; only JSON artifacts + manifests + report are committed.)

---

## Self-review checklist (run before execution)

- Spec G2 line: «`analyses/nordisk-omsorg` end-to-end + bokmål report +
  planted-hallucination test» — Tasks 4–9 cover end-to-end, Task 8 the bokmål report,
  Task 7 the planted test. ✓
- DECISIONS compliance: every report number is a verified claim (Task 7 claims cover every
  number rendered in Task 8's template — n_municipalities, n_dropped, medians,
  high_squeeze_share, top-list entries, comparison country; KUHR context numbers are in
  `findings["context"]` → **add two claims**: `context.kuhr_konsultasjoner_latest` and
  `context.kuhr_konsultasjoner_change_pct` recomputed from the KUHR rows? The KUHR raw
  rows are not in nordic_table.csv — verify recomputes them from
  `datasets` is not available at verify time offline… **Resolution (binding):** analyze
  also persists the two context numbers' inputs in `nordic_drops.json`-style sidecar?
  Simpler: keep KUHR numbers OUT of verify by keeping them out of *claims* — but
  DECISIONS requires every claimed statistic verified. **Final resolution:** analyze
  writes `nordic_context.json` (the two KUHR aggregates + the per-year sums used), verify
  recomputes change_pct from the persisted per-year sums and checks both numbers
  (2 extra claims), report renders only from findings. Implementer: add the sidecar in
  Task 6 (`(ctx.data_dir / "nordic_context.json").write_text(json.dumps({"by_year":
  {str(y): float(v) for y, v in by_year.items()}, **context}))` inside
  `stage_analyze_nordisk` right after `context = kuhr_context(...)`), and in Task 7 add:

```python
    ctx_f = findings.get("context", {})
    if ctx_f.get("kuhr_konsultasjoner_latest") is not None:
        side = json.loads((ctx.data_dir / "nordic_context.json").read_text(encoding="utf-8"))
        by_year = {int(k): float(v) for k, v in side["by_year"].items()}
        latest = int(findings["analysis_years"]["latest"])
        base = int(findings["analysis_years"]["base"])
        _check(claims, "context.kuhr_konsultasjoner_latest",
               ctx_f["kuhr_konsultasjoner_latest"], int(by_year[latest]))
        _check(claims, "context.kuhr_konsultasjoner_change_pct",
               ctx_f["kuhr_konsultasjoner_change_pct"],
               round((by_year[latest] - by_year[base]) / by_year[base] * 100, 1),
               tol=0.05)
```
- Engine boundary: core changes are generic only (use_codes/labels, kolada, register_schema,
  CLI flags). All nordisk logic in the instance. ✓
- Honesty: comparability caveat in metode + sammenligning + forbehold; n_dropped published;
  within-country normalization. ✓
- Offline-first: every test except `-m live` runs without network. ✓
