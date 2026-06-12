# G1 — Nordic Adapters + Realness Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship four new dataset adapters (sotkanet, socialstyrelsen, kuhr, csv), NO/SE/FI geo
harmonization, and mandatory realness gates in the profile stage — per
`docs/specs/2026-06-11-v2-generalization-design.md` §Adapters.

**Architecture:** Each adapter is one module in `src/omsorgsradar/core/adapters/` satisfying the
existing `DatasetAdapter` protocol (`source_id`, `fetch(source) -> pd.DataFrame`), sharing one
JSON disk cache with sanitized keys. A new adapter registry dispatches non-legacy `[[sources]]`
blocks generically from `run_ingest`; legacy v1 source ids keep their special fetchers untouched
(byte-identical v1 behavior). Nordic adapters emit one tidy contract: `country, geo_code, geo_id,
geo_name, aar, indicator, value` with country-prefixed `geo_id` ("NO-1505", "SE-0180", "FI-091")
from a new `core/geo.py`. Realness gates (5 checks from the Retraction-Watch/Kaggle research) run
inside the profile stage; a FAIL verdict aborts via the existing `PipelineGateError`, and the
verdict is always published in `quality_profile.json` first.

**Tech Stack:** Python 3.11+ via `uv`, pandas, requests, jsonschema, pytest (all already in
`pyproject.toml` — no new dependencies).

**API ground truth (verified live 2026-06-12):**

- **Sotkanet (THL, FI)** — `GET https://sotkanet.fi/rest/1.1/json?indicator=127&years=2023&genders=total`
  → JSON list of `{"indicator":127,"region":52,"year":2023,"gender":"total","value":9646}`.
  `region` is a Sotkanet-internal id; `GET /rest/1.1/regions` → list of
  `{"id":833,"code":"1","category":"ALUEHALLINTOVIRASTO","title":{"fi":...,"en":...,"sv":...},...}`;
  municipalities have `category == "KUNTA"` and 3-digit `code`. CC BY 4.0, no auth.
- **Socialstyrelsen statistikdatabas (SE)** — base `https://sdb.socialstyrelsen.se/api/v1/sv`.
  `GET /{amne}` topics; `GET /{amne}/matt` → `[{"id":1,"text":"Antal"}]`; `GET /{amne}/region` →
  `[{"id":"0180","kod":"0180","text":"Stockholm"}]` (4-digit kod = kommun, 2-digit = län, "00" = riket);
  `GET /{amne}/resultat/matt/{id}[/ar/{y1,y2}]?per_sida=N` →
  `{"data":[{"variabelId":"D","regionId":0,"alderId":1,"mattId":1,"ar":1998,"varde":"4264"}],
  "nasta_sida":"http://...sida=2",...}` — paginated, `varde` is a **string**, `nasta_sida` is
  **http://** (follow as https). ⚠ The live topic list has **no äldreomsorg topic** (only amning,
  diagnoser, läkemedel, skador-per-kommun, dödsorsaker, …) — the adapter is generic over the API;
  Swedish elder-care data for G2 comes from Socialstyrelsen open-data CSV files via the csv adapter.
- **KUHR (Helsedirektoratet/NAV, NO)** — base `https://opne-data-api.helserefusjon.no/v1`
  (docs: github.com/navikt/Helserefusjon-apne-data).
  `GET /takstbruk/agtakst/kommune/ar?fagomraade=LE&fomar=2023&tomar=2023&kommuner=1505&takstkoder=2ad`
  with `Accept: application/json` → `{"antall":4,"takstbruk":[{"ar":"2023",
  "behandler_kommunenr":"1505","sum_antall_takst":57602,"takstkode":"2ad","fagomraade":"LE",
  "praksis_type_kode":"FALE","samhandler_praksis_type":"Fastlege","antall_regninger":57602,
  "sum_refusjon":4756525.0,"sum_egenandel_betalt_av_pasient":5697640.0,
  "sum_egenandel_dekket_av_folketrygden":3806230.0}, …]}`. Optional filters: `takstkoder`,
  `kommuner`, `praksistyper`; also `/fylke/ar`, `/landet/ar`, `/kommune/maned` (max 13 months).
  `GET /fagomraader` lists fagområde codes (LE = lege, etc.). No auth.

**Realness gates (spec + wiki `tech/agentic-healthcare-analysis-workflow-2026` §Kaggle):**
1. provenance (URL/DOI resolvable), 2. named institution, 3. exact-duplicate rate (>1% = FAIL),
4. missingness plausibility (0 missing in a large dataset = WARN — the fabrication signature;
≥95% missing value column = FAIL), 5. distribution sanity (zero variance at scale = FAIL).
Verdict per dataset: PASS / WARN / FAIL / SKIP (empty). FAIL aborts the pipeline **after** the
quality profile is written.

**Conventions for the implementer:**
- Run everything with `uv run …` — never bare `python`/`pip`.
- After every task: `uv run pytest -x -q` must pass (offline) before committing. Baseline: 114 tests.
- Commit messages prefixed `G1:`.
- Repo root is the working directory for all commands.
- Fixture-capture steps hit live APIs once and print the literal values to paste into known-value
  assertions — paste exactly what the capture script prints; never invent numbers.

**Execution notes (workspace policy):** sonnet implementers, ≤10 parallel agents (owner budget
constraint). Tasks 3–6 are independent of each other (parallelizable after Tasks 1–2). Tasks 7→10
are sequential. End-of-phase review panel before the final commit: blast-radius-mapper (opus) →
correctness (opus) + security (opus) + integration (sonnet).

---

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `src/omsorgsradar/core/adapters/cache.py` | create | shared JSON disk cache, sanitized keys |
| `src/omsorgsradar/core/adapters/pxweb.py` | modify | use shared cache (behavior-identical) |
| `src/omsorgsradar/core/geo.py` | create | NO/SE/FI municipality-code harmonization |
| `src/omsorgsradar/core/adapters/sotkanet.py` | create | THL Sotkanet REST adapter |
| `src/omsorgsradar/core/adapters/socialstyrelsen.py` | create | SE statistikdatabas REST adapter |
| `src/omsorgsradar/core/adapters/kuhr.py` | create | NO helserefusjon (KUHR) adapter |
| `src/omsorgsradar/core/adapters/csvfile.py` | create | local CSV adapter |
| `src/omsorgsradar/core/adapters/__init__.py` | modify | protocol + registry + source validation |
| `src/omsorgsradar/core/config.py` | modify | source `id` pattern lock |
| `src/omsorgsradar/ingest.py` | modify | generic adapter dispatch in `run_ingest` |
| `src/omsorgsradar/realness.py` | create | the 5 realness gate checks |
| `src/omsorgsradar/profile.py` | modify | generic profiler + realness wiring |
| `src/omsorgsradar/stages.py` | modify | profile-stage gate raise |
| `src/omsorgsradar/pipeline.py` | modify | startup source validation; journal correct stage on gate fail |
| `src/omsorgsradar/core/contracts.py` | modify | quality-profile schema gains realness |
| `tests/core/test_cache.py`, `tests/core/test_geo.py`, `tests/core/test_sotkanet_adapter.py`, `tests/core/test_socialstyrelsen_adapter.py`, `tests/core/test_kuhr_adapter.py`, `tests/core/test_csv_adapter.py`, `tests/core/test_adapter_registry.py`, `tests/test_realness.py`, `tests/test_nordic_integration.py` | create | per-unit + integration coverage |
| `tests/fixtures/sotkanet_*.json`, `tests/fixtures/sst_skador_*.json`, `tests/fixtures/kuhr_le_1505_fixture.json` | create | real captured API payloads, trimmed |
| `docs/adapters.md` | create | `[[sources]]` reference per adapter |
| `.claude/skills/pipeline-stages/SKILL.md`, `CLAUDE.md`, `status.md` | modify | docs current |

---

### Task 1: Shared JSON cache with sanitized keys

**Files:**
- Create: `src/omsorgsradar/core/adapters/cache.py`
- Modify: `src/omsorgsradar/core/adapters/pxweb.py`
- Test: `tests/core/test_cache.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_cache.py`:
```python
"""Shared adapter cache: round-trip, miss, and key sanitization."""

from pathlib import Path

import pytest

from omsorgsradar.core.adapters.cache import CacheKeyError, JsonCache


class TestJsonCache:
    def test_round_trip(self, tmp_path: Path) -> None:
        cache = JsonCache(tmp_path)
        cache.save("sotkanet_127_2023_2023_total", {"a": [1, 2]})
        assert cache.load("sotkanet_127_2023_2023_total") == {"a": [1, 2]}
        assert (tmp_path / "sotkanet_127_2023_2023_total.json").exists()

    def test_miss_returns_none(self, tmp_path: Path) -> None:
        assert JsonCache(tmp_path).load("absent") is None

    def test_none_dir_is_noop(self) -> None:
        cache = JsonCache(None)
        cache.save("k", {"x": 1})  # must not raise
        assert cache.load("k") is None

    @pytest.mark.parametrize("bad", ["a/b", "../etc", "a..b", "a b", "", "nøkkel"])
    def test_bad_keys_rejected(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(CacheKeyError):
            JsonCache(tmp_path).save(bad, {})
        with pytest.raises(CacheKeyError):
            JsonCache(tmp_path).load(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsorgsradar.core.adapters.cache'`

- [ ] **Step 3: Implement the cache**

`src/omsorgsradar/core/adapters/cache.py`:
```python
"""Shared raw-JSON disk cache for adapters.

Cache keys are restricted to ``[A-Za-z0-9._-]`` with no ``..`` so a
machine-authored config can never traverse out of the cache directory
(security flag 2026-06-11, partially landed here ahead of G3).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60  # seconds, shared by all HTTP adapters

_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class CacheKeyError(ValueError):
    """Cache key contains path separators, '..', or other unsafe characters."""


class JsonCache:
    """Raw JSON to ``<cache_dir>/<key>.json``; ``cache_dir=None`` disables."""

    def __init__(self, cache_dir: Path | str | None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None

    @staticmethod
    def check_key(key: str) -> str:
        if not _KEY_RE.match(key) or ".." in key:
            raise CacheKeyError(
                f"unsafe cache key {key!r} — allowed: letters, digits, '.', '_', '-'"
            )
        return key

    def load(self, key: str) -> Any | None:
        self.check_key(key)
        if self.cache_dir is None:
            return None
        f = self.cache_dir / f"{key}.json"
        if f.exists():
            logger.debug("Cache hit: %s", f)
            return json.loads(f.read_text(encoding="utf-8"))
        return None

    def save(self, key: str, data: Any) -> None:
        self.check_key(key)
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
```

- [ ] **Step 4: Refactor PxWebAdapter onto the shared cache (behavior-identical)**

In `src/omsorgsradar/core/adapters/pxweb.py`, replace the `__init__` body and the two private
cache methods with the shared cache. Replace:

```python
    def __init__(
        self,
        base_url: str,
        cache_dir: Path | None = None,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.timeout = timeout

    # ── cache ────────────────────────────────────────────────────────────────
    def _cache_load(self, key: str) -> Any | None:
        if self.cache_dir is None:
            return None
        f = self.cache_dir / f"{key}.json"
        if f.exists():
            logger.debug("Cache hit: %s", f)
            return json.loads(f.read_text(encoding="utf-8"))
        return None

    def _cache_save(self, key: str, data: Any) -> None:
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
```

with:

```python
    def __init__(
        self,
        base_url: str,
        cache_dir: Path | None = None,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout

    def _cache_load(self, key: str) -> Any | None:
        return self.cache.load(key)

    def _cache_save(self, key: str, data: Any) -> None:
        self.cache.save(key, data)
```

and add the import at the top (keep existing imports; `json` stays — `jsonstat2_to_df` callers
elsewhere import nothing from it but the module still uses `json` nowhere else after this edit,
so **remove `import json` only if ruff/pytest confirms it is unused**):

```python
from .cache import JsonCache
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -x -q`
Expected: 114 + 9 new = all pass. `tests/core/test_pxweb_adapter.py::TestAdapterCache` proves
cache naming (`<key>.json`) is unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/omsorgsradar/core/adapters/cache.py src/omsorgsradar/core/adapters/pxweb.py tests/core/test_cache.py
git commit -m "G1: shared adapter JSON cache with sanitized keys; pxweb refactored onto it"
```

---

### Task 2: Geo harmonization (NO/SE/FI)

**Files:**
- Create: `src/omsorgsradar/core/geo.py`
- Test: `tests/core/test_geo.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_geo.py`:
```python
"""Country-prefixed municipality ids: NO-1505, SE-0180, FI-091."""

import pytest

from omsorgsradar.core.geo import GeoError, make_geo_id, normalize_code, split_geo_id


class TestNormalizeCode:
    @pytest.mark.parametrize(
        ("country", "raw", "expected"),
        [
            ("NO", "1505", "1505"),   # Kristiansund
            ("NO", "301", "0301"),    # Oslo, zero-padded
            ("SE", "0180", "0180"),   # Stockholm
            ("SE", 180, "0180"),      # int from JSON survives
            ("FI", "091", "091"),     # Helsinki
            ("FI", "91", "091"),
            ("fi", "91", "091"),      # case-insensitive country
        ],
    )
    def test_known_values(self, country: str, raw, expected: str) -> None:
        assert normalize_code(country, raw) == expected

    @pytest.mark.parametrize(
        ("country", "raw"),
        [("NO", "12345"), ("NO", "12x5"), ("FI", "1234"), ("DK", "0101"), ("SE", "")],
    )
    def test_invalid_rejected(self, country: str, raw) -> None:
        with pytest.raises(GeoError):
            normalize_code(country, raw)


class TestGeoId:
    def test_make_and_split_round_trip(self) -> None:
        gid = make_geo_id("NO", "1505")
        assert gid == "NO-1505"
        assert split_geo_id(gid) == ("NO", "1505")
        assert make_geo_id("FI", "91") == "FI-091"
        assert make_geo_id("SE", 180) == "SE-0180"

    def test_split_rejects_garbage(self) -> None:
        for bad in ("NO1505", "XX-1505", "NO-15"):
            with pytest.raises(GeoError):
                split_geo_id(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_geo.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsorgsradar.core.geo'`

- [ ] **Step 3: Implement**

`src/omsorgsradar/core/geo.py`:
```python
"""Municipality-code harmonization across NO/SE/FI.

Canonical cross-country key: ``<ISO2>-<national code>`` — "NO-1505",
"SE-0180", "FI-091". National codes keep their official zero-padding
(NO/SE 4 digits, FI 3 digits). Norwegian codes must additionally pass
through :func:`omsorgsradar.kommune_mergers.normalize_knr_series` (adapter
responsibility) so pre-2020 numbers land on post-merger municipalities.
"""

from __future__ import annotations


class GeoError(ValueError):
    """A municipality code or geo id does not match its country's format."""


CODE_LENGTHS: dict[str, int] = {"NO": 4, "SE": 4, "FI": 3}


def normalize_code(country: str, code: object) -> str:
    c2 = country.upper()
    if c2 not in CODE_LENGTHS:
        raise GeoError(f"unknown country '{country}' (known: {sorted(CODE_LENGTHS)})")
    n = CODE_LENGTHS[c2]
    raw = str(code).strip()
    if raw.isdigit() and 0 < len(raw) <= n:
        return raw.zfill(n)
    raise GeoError(f"{c2}: invalid municipality code {code!r} (expected ≤{n} digits)")


def make_geo_id(country: str, code: object) -> str:
    return f"{country.upper()}-{normalize_code(country, code)}"


def split_geo_id(geo_id: str) -> tuple[str, str]:
    country, sep, code = str(geo_id).partition("-")
    if not sep:
        raise GeoError(f"invalid geo id {geo_id!r} (expected '<CC>-<code>')")
    c2 = country.upper()
    if c2 not in CODE_LENGTHS or len(code) != CODE_LENGTHS[c2] or not code.isdigit():
        raise GeoError(f"invalid geo id {geo_id!r}")
    return c2, code
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/core/test_geo.py -q`
Expected: PASS (all parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add src/omsorgsradar/core/geo.py tests/core/test_geo.py
git commit -m "G1: NO/SE/FI geo harmonization (country-prefixed municipality ids)"
```

---

### Task 3: Sotkanet adapter (FI)

**Files:**
- Create: `src/omsorgsradar/core/adapters/sotkanet.py`
- Create: `tests/fixtures/sotkanet_regions_fixture.json`, `tests/fixtures/sotkanet_127_fixture.json`
- Test: `tests/core/test_sotkanet_adapter.py`
- Modify: `pyproject.toml` (exclude `live` tests from default runs)

- [ ] **Step 1: Exclude live-marked tests from the default run**

In `pyproject.toml` change:
```toml
addopts = "-v --tb=short"
```
to:
```toml
addopts = "-v --tb=short -m 'not live'"
```
(`uv run pytest` stays offline-green; live checks run via `uv run pytest -m live`.)

- [ ] **Step 2: Capture real fixtures (one-time live calls)**

```bash
uv run python - <<'EOF'
import json, requests
BASE = "https://sotkanet.fi/rest/1.1"
regions = requests.get(f"{BASE}/regions", timeout=60).json()
keep = {"091", "049", "837", "853", "564"}  # Helsinki, Espoo, Tampere, Turku, Oulu
kunta = [r for r in regions if r.get("category") == "KUNTA" and r["code"] in keep]
other = [r for r in regions if r.get("category") == "MAAKUNTA"][:2]  # filtering proof
json.dump(kunta + other, open("tests/fixtures/sotkanet_regions_fixture.json", "w"),
          ensure_ascii=False, indent=1)
ids = {r["id"] for r in kunta}
data = requests.get(f"{BASE}/json",
                    params={"indicator": "127", "years": ["2023"], "genders": "total"},
                    timeout=60).json()
rows = [d for d in data if d["region"] in ids]
json.dump(rows, open("tests/fixtures/sotkanet_127_fixture.json", "w"), indent=1)
hki_id = next(r["id"] for r in kunta if r["code"] == "091")
print("PASTE INTO TEST — Helsinki indicator-127 2023 value:",
      next(d["value"] for d in rows if d["region"] == hki_id))
EOF
```
Expected: both fixture files written; one `PASTE INTO TEST` line printed.

- [ ] **Step 3: Write the failing tests** (paste the printed Helsinki value where marked)

`tests/core/test_sotkanet_adapter.py`:
```python
"""Sotkanet adapter — offline via pre-seeded cache + real trimmed fixtures."""

import json
import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.sotkanet import SotkanetAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Paste the value printed by the fixture-capture script (Task 3 / Step 2):
HELSINKI_127_2023 = 0  # <- replace 0 with the printed integer before running


def seeded_adapter(tmp_path: Path) -> SotkanetAdapter:
    """Unreachable base_url + pre-seeded cache: any HTTP attempt would fail."""
    shutil.copy(FIXTURE_DIR / "sotkanet_regions_fixture.json",
                tmp_path / "sotkanet_regions.json")
    shutil.copy(FIXTURE_DIR / "sotkanet_127_fixture.json",
                tmp_path / "sotkanet_127_2023_2023_total.json")
    return SotkanetAdapter(base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path)


class TestMunicipalities:
    def test_kunta_only(self, tmp_path: Path) -> None:
        kunta = seeded_adapter(tmp_path).municipalities()
        assert len(kunta) == 5  # MAAKUNTA fixture entries excluded
        assert ("091", "Helsinki") in kunta.values()


class TestFetch:
    def test_tidy_known_value(self, tmp_path: Path) -> None:
        source = {"adapter": "sotkanet", "id": "fi_test",
                  "indicators": [127], "years": [2023]}
        df = seeded_adapter(tmp_path).fetch(source)
        assert list(df.columns) == ["country", "geo_code", "geo_id", "geo_name",
                                    "aar", "indicator", "gender", "value"]
        assert set(df["country"]) == {"FI"}
        hki = df[df["geo_id"] == "FI-091"]
        assert len(hki) == 1
        assert hki.iloc[0]["geo_name"] == "Helsinki"
        assert hki.iloc[0]["aar"] == 2023
        assert hki.iloc[0]["value"] == HELSINKI_127_2023

    def test_empty_indicator_gives_empty_tidy_df(self, tmp_path: Path) -> None:
        ad = seeded_adapter(tmp_path)
        (tmp_path / "sotkanet_999_2023_2023_total.json").write_text("[]")
        df = ad.fetch({"adapter": "sotkanet", "id": "x",
                       "indicators": [999], "years": [2023]})
        assert df.empty and "geo_id" in df.columns


@pytest.mark.live
class TestLive:
    def test_live_fetch_has_many_kunta(self) -> None:
        ad = SotkanetAdapter()
        df = ad.fetch({"adapter": "sotkanet", "id": "live",
                       "indicators": [127], "years": [2023]})
        assert df["geo_id"].nunique() > 250  # ~290 Finnish municipalities
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_sotkanet_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsorgsradar.core.adapters.sotkanet'`

- [ ] **Step 5: Implement**

`src/omsorgsradar/core/adapters/sotkanet.py`:
```python
"""Sotkanet (THL, Finland) REST adapter.

API shapes verified live 2026-06-12:
- data:    GET {base}/json?indicator=<id>&years=<y>…&genders=total
           -> [{"indicator":127,"region":52,"year":2023,"gender":"total","value":9646}, …]
- regions: GET {base}/regions -> [{"id":…,"code":"091","category":"KUNTA",
           "title":{"fi":"Helsinki",…}}, …]  ("region" in data rows = internal "id")
License CC BY 4.0, no auth. ~3,700 indicators, municipality level.
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


class SotkanetAdapter:
    source_id = "sotkanet"
    DEFAULT_BASE_URL = "https://sotkanet.fi/rest/1.1"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout

    def _get_json(self, url: str, params: dict | None, cache_key: str) -> Any:
        cached = self.cache.load(cache_key)
        if cached is not None:
            return cached
        logger.info("GET %s", url)
        resp = requests.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        self.cache.save(cache_key, data)
        return data

    def municipalities(self) -> dict[int, tuple[str, str]]:
        """Sotkanet internal region id -> (3-digit kunta code, Finnish name)."""
        regions = self._get_json(
            f"{self.base_url}/regions", params=None, cache_key="sotkanet_regions"
        )
        return {
            r["id"]: (str(r["code"]).zfill(3), r.get("title", {}).get("fi", ""))
            for r in regions
            if r.get("category") == "KUNTA"
        }

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        years = sorted(int(y) for y in source["years"])
        gender = str(source.get("genders", "total"))
        kunta = self.municipalities()
        frames: list[pd.DataFrame] = []
        for ind in source["indicators"]:
            key = f"sotkanet_{ind}_{years[0]}_{years[-1]}_{gender}"
            rows = self._get_json(
                f"{self.base_url}/json",
                params={"indicator": str(ind),
                        "years": [str(y) for y in years],
                        "genders": gender},
                cache_key=key,
            )
            df = pd.DataFrame(rows)
            if df.empty:
                logger.warning("Sotkanet indicator %s returned no rows", ind)
                continue
            df = df[df["region"].isin(kunta)].copy()
            df["geo_code"] = df["region"].map(lambda r: kunta[r][0])
            df["geo_name"] = df["region"].map(lambda r: kunta[r][1])
            df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("FI", c))
            df["aar"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
            df["indicator"] = str(ind)
            df["country"] = "FI"
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            frames.append(df[TIDY_COLUMNS])
        if not frames:
            return pd.DataFrame(columns=TIDY_COLUMNS)
        out = pd.concat(frames, ignore_index=True)
        logger.info("Sotkanet: %d rows, %d kunta, indicators %s",
                    len(out), out["geo_id"].nunique(), sorted(out["indicator"].unique()))
        return out
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/core/test_sotkanet_adapter.py -q`
Expected: 3 passed, live test deselected.

- [ ] **Step 7: Full suite + commit**

Run: `uv run pytest -x -q` — all pass.
```bash
git add pyproject.toml src/omsorgsradar/core/adapters/sotkanet.py tests/core/test_sotkanet_adapter.py tests/fixtures/sotkanet_regions_fixture.json tests/fixtures/sotkanet_127_fixture.json
git commit -m "G1: Sotkanet (FI) adapter with offline fixtures + known-value test"
```

---

### Task 4: Socialstyrelsen adapter (SE)

**Files:**
- Create: `src/omsorgsradar/core/adapters/socialstyrelsen.py`
- Create: `tests/fixtures/sst_skador_regions_fixture.json`, `tests/fixtures/sst_skador_data_fixture.json`
- Test: `tests/core/test_socialstyrelsen_adapter.py`

- [ ] **Step 1: Capture real fixtures**

```bash
uv run python - <<'EOF'
import json, requests
BASE = "https://sdb.socialstyrelsen.se/api/v1/sv"
AMNE = "skadorochskadehandelserisverigeskommunerochlan"  # kommun-level topic
KEEP = {"0180", "1480", "1280", "0580", "2480"}  # Sthlm, Gbg, Malmö, Linköping, Umeå
regions = requests.get(f"{BASE}/{AMNE}/region", timeout=60).json()
trimmed = [r for r in regions if r["kod"] in KEEP | {"00", "01"}]  # + riket + ett län
json.dump(trimmed, open("tests/fixtures/sst_skador_regions_fixture.json", "w"),
          ensure_ascii=False, indent=1)
url = f"{BASE}/{AMNE}/resultat/matt/1/region/" + ",".join(sorted(KEEP)) + "/ar/2023"
payload = requests.get(url, params={"per_sida": 5000}, timeout=60).json()
rows = payload["data"]
assert payload.get("nasta_sida") is None, "unexpected pagination in fixture capture"
json.dump(rows, open("tests/fixtures/sst_skador_data_fixture.json", "w"), indent=1)
sthlm = [r for r in rows if str(r["regionId"]).zfill(4) == "0180"]
print("PASTE INTO TEST — n fixture rows:", len(rows))
print("PASTE INTO TEST — Stockholm 2023 first varde:", sthlm[0]["varde"],
      "(variabelId", repr(sthlm[0]["variabelId"]), "alderId", sthlm[0]["alderId"], ")")
EOF
```
Expected: two fixture files; two `PASTE INTO TEST` lines.

- [ ] **Step 2: Write the failing tests** (paste printed literals where marked)

`tests/core/test_socialstyrelsen_adapter.py`:
```python
"""Socialstyrelsen statistikdatabas adapter — offline cache + pagination unit."""

import json
import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.socialstyrelsen import SocialstyrelsenAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
AMNE = "skadorochskadehandelserisverigeskommunerochlan"

# Paste literals printed by the capture script (Task 4 / Step 1):
N_FIXTURE_ROWS = 0          # <- replace
STHLM_FIRST_VARDE = "0"     # <- replace (string, as the API returns it)


def seeded_adapter(tmp_path: Path) -> SocialstyrelsenAdapter:
    shutil.copy(FIXTURE_DIR / "sst_skador_regions_fixture.json",
                tmp_path / f"sst_{AMNE}_regions.json")
    shutil.copy(FIXTURE_DIR / "sst_skador_data_fixture.json",
                tmp_path / f"sst_{AMNE}_m1_2023_2023.json")
    return SocialstyrelsenAdapter(base_url="http://127.0.0.1:9/unreachable",
                                  cache_dir=tmp_path)


class TestFetch:
    def test_tidy_kommun_known_value(self, tmp_path: Path) -> None:
        source = {"adapter": "socialstyrelsen", "id": "se_test",
                  "amne": AMNE, "matt": 1, "years": [2023]}
        df = seeded_adapter(tmp_path).fetch(source)
        assert set(df["country"]) == {"SE"}
        assert set(df["geo_id"]) <= {"SE-0180", "SE-1480", "SE-1280", "SE-0580", "SE-2480"}
        assert len(df) == N_FIXTURE_ROWS  # riket/län rows were already excluded at capture
        sthlm = df[df["geo_id"] == "SE-0180"].sort_index()
        assert sthlm.iloc[0]["geo_name"] == "Stockholm"
        assert sthlm.iloc[0]["aar"] == 2023
        assert str(sthlm.iloc[0]["value_raw"]) == STHLM_FIRST_VARDE

    def test_lan_and_riket_rows_dropped(self, tmp_path: Path) -> None:
        ad = seeded_adapter(tmp_path)
        rows = json.loads((tmp_path / f"sst_{AMNE}_m1_2023_2023.json").read_text())
        rows.append({"variabelId": "X", "regionId": 0, "alderId": 1,
                     "mattId": 1, "ar": 2023, "varde": "999"})   # riket
        rows.append({"variabelId": "X", "regionId": 1, "alderId": 1,
                     "mattId": 1, "ar": 2023, "varde": "999"})   # Stockholms län
        (tmp_path / f"sst_{AMNE}_m1_2023_2023.json").write_text(json.dumps(rows))
        df = ad.fetch({"adapter": "socialstyrelsen", "id": "se_test",
                       "amne": AMNE, "matt": 1, "years": [2023]})
        assert len(df) == N_FIXTURE_ROWS  # the two non-kommun rows are gone


class TestPagination:
    def test_follows_nasta_sida_as_https(self, tmp_path: Path, monkeypatch) -> None:
        pages = {
            "https://sdb.socialstyrelsen.se/p1": {
                "data": [{"variabelId": "D", "regionId": 180, "alderId": 1,
                          "mattId": 1, "ar": 2023, "varde": "1"}],
                "nasta_sida": "http://sdb.socialstyrelsen.se/p2",
            },
            "https://sdb.socialstyrelsen.se/p2": {
                "data": [{"variabelId": "D", "regionId": 180, "alderId": 2,
                          "mattId": 1, "ar": 2023, "varde": "2"}],
                "nasta_sida": None,
            },
        }
        calls: list[str] = []

        class FakeResp:
            def __init__(self, payload): self._p = payload
            def raise_for_status(self): pass
            def json(self): return self._p

        def fake_get(url, params=None, timeout=None):
            calls.append(url)
            return FakeResp(pages[url])

        monkeypatch.setattr("omsorgsradar.core.adapters.socialstyrelsen.requests.get",
                            fake_get)
        ad = SocialstyrelsenAdapter(cache_dir=None)
        rows = ad._fetch_all_pages("https://sdb.socialstyrelsen.se/p1", max_pages=10)
        assert [r["varde"] for r in rows] == ["1", "2"]
        assert calls == ["https://sdb.socialstyrelsen.se/p1",
                         "https://sdb.socialstyrelsen.se/p2"]  # http→https rewritten

    def test_max_pages_exceeded_raises(self, tmp_path: Path, monkeypatch) -> None:
        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"data": [], "nasta_sida": "http://sdb.socialstyrelsen.se/next"}

        monkeypatch.setattr("omsorgsradar.core.adapters.socialstyrelsen.requests.get",
                            lambda url, params=None, timeout=None: FakeResp())
        ad = SocialstyrelsenAdapter(cache_dir=None)
        with pytest.raises(RuntimeError, match="max_pages"):
            ad._fetch_all_pages("https://sdb.socialstyrelsen.se/p1", max_pages=3)


@pytest.mark.live
class TestLive:
    def test_live_topic_list_still_has_amne(self) -> None:
        import requests
        topics = requests.get("https://sdb.socialstyrelsen.se/api/v1/sv",
                              timeout=60).json()
        assert AMNE in {t["namn"] for t in topics}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_socialstyrelsen_adapter.py -q`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement**

`src/omsorgsradar/core/adapters/socialstyrelsen.py`:
```python
"""Socialstyrelsen statistikdatabas (SE) REST adapter.

API shapes verified live 2026-06-12 (docs: sdb.socialstyrelsen.se/sdbapi.aspx):
- topics:  GET {base}            -> [{"namn":"amning","text":…}, …]
- regions: GET {base}/{amne}/region -> [{"id":"0180","kod":"0180","text":"Stockholm"}]
           (4-digit kod = kommun, 2-digit = län, "00" = riket)
- data:    GET {base}/{amne}/resultat/matt/{id}[/region/…][/ar/y1,y2]?per_sida=N
           -> {"data":[{"variabelId":"D","regionId":0,"alderId":1,"mattId":1,
               "ar":1998,"varde":"4264"}], "nasta_sida": "http://…sida=2", …}
           varde is a string ("X"/".." = suppressed); nasta_sida links are http.
NB 2026-06-12: the topic list carries no äldreomsorg topic — Swedish elder-care
data arrives via Socialstyrelsen open-data CSV files (csv adapter) in G2.
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

TIDY_COLUMNS = ["country", "geo_code", "geo_id", "geo_name", "aar", "indicator",
                "variabelId", "alderId", "value_raw", "value"]
DEFAULT_PER_PAGE = 5000
DEFAULT_MAX_PAGES = 50


class SocialstyrelsenAdapter:
    source_id = "socialstyrelsen"
    DEFAULT_BASE_URL = "https://sdb.socialstyrelsen.se/api/v1/sv"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout

    def _fetch_all_pages(self, url: str, *, max_pages: int) -> list[dict[str, Any]]:
        """Accumulate `data` rows following `nasta_sida` (rewritten to https)."""
        rows: list[dict[str, Any]] = []
        page_url: str | None = url
        for _ in range(max_pages):
            if page_url is None:
                return rows
            logger.info("GET %s", page_url)
            resp = requests.get(page_url, params=None, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            rows.extend(payload.get("data", []))
            nxt = payload.get("nasta_sida")
            page_url = nxt.replace("http://", "https://", 1) if nxt else None
        if page_url is not None:
            raise RuntimeError(
                f"socialstyrelsen: exceeded max_pages={max_pages} at {page_url} — "
                "narrow years/regions or raise max_pages in the source block"
            )
        return rows

    def _municipalities(self, amne: str) -> dict[str, str]:
        """kommun kod ('0180') -> name; non-kommun region rows excluded."""
        key = f"sst_{amne}_regions"
        regions = self.cache.load(key)
        if regions is None:
            resp = requests.get(f"{self.base_url}/{amne}/region", timeout=self.timeout)
            resp.raise_for_status()
            regions = resp.json()
            self.cache.save(key, regions)
        return {r["kod"]: r["text"] for r in regions
                if len(str(r["kod"])) == 4 and str(r["kod"]).isdigit()}

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        amne = source["amne"]
        matt = int(source["matt"])
        years = [str(int(y)) for y in source.get("years", [])]
        kommun = self._municipalities(amne)
        # int(kod) is collision-free: län 01–25 -> 1–25, kommun koder start at 0114.
        by_int = {int(k): k for k in kommun}

        key = f"sst_{amne}_m{matt}" + (f"_{years[0]}_{years[-1]}" if years else "")
        rows = self.cache.load(key)
        if rows is None:
            url = f"{self.base_url}/{amne}/resultat/matt/{matt}"
            if source.get("regions"):
                url += "/region/" + ",".join(str(r) for r in source["regions"])
            if years:
                url += "/ar/" + ",".join(years)
            url += f"?per_sida={int(source.get('per_sida', DEFAULT_PER_PAGE))}"
            rows = self._fetch_all_pages(
                url, max_pages=int(source.get("max_pages", DEFAULT_MAX_PAGES))
            )
            self.cache.save(key, rows)

        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=TIDY_COLUMNS)
        df["geo_code"] = df["regionId"].map(lambda r: by_int.get(int(r)))
        df = df[df["geo_code"].notna()].copy()  # kommun rows only
        df["geo_name"] = df["geo_code"].map(kommun)
        df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("SE", c))
        df["aar"] = pd.to_numeric(df["ar"], errors="coerce").astype("Int64")
        df["indicator"] = f"{amne}_matt{matt}"
        df["country"] = "SE"
        df["value_raw"] = df["varde"]
        df["value"] = pd.to_numeric(df["varde"], errors="coerce")  # "X"/".." -> NaN
        logger.info("Socialstyrelsen %s matt=%d: %d kommun rows, %d kommuner",
                    amne, matt, len(df), df["geo_id"].nunique())
        return df[TIDY_COLUMNS].reset_index(drop=True)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/test_socialstyrelsen_adapter.py -q`
Expected: 4 passed, 1 deselected (live).

- [ ] **Step 6: Full suite + commit**

Run: `uv run pytest -x -q` — all pass.
```bash
git add src/omsorgsradar/core/adapters/socialstyrelsen.py tests/core/test_socialstyrelsen_adapter.py tests/fixtures/sst_skador_regions_fixture.json tests/fixtures/sst_skador_data_fixture.json
git commit -m "G1: Socialstyrelsen (SE) adapter — pagination, suppressed values, kommun filter"
```

---

### Task 5: KUHR adapter (NO)

**Files:**
- Create: `src/omsorgsradar/core/adapters/kuhr.py`
- Create: `tests/fixtures/kuhr_le_1505_fixture.json`
- Test: `tests/core/test_kuhr_adapter.py`

- [ ] **Step 1: Capture the real fixture**

```bash
uv run python - <<'EOF'
import json, requests
r = requests.get(
    "https://opne-data-api.helserefusjon.no/v1/takstbruk/agtakst/kommune/ar",
    params={"fagomraade": "LE", "fomar": "2023", "tomar": "2023",
            "kommuner": "1505", "takstkoder": "2ad"},
    headers={"Accept": "application/json"}, timeout=60)
r.raise_for_status()
json.dump(r.json(), open("tests/fixtures/kuhr_le_1505_fixture.json", "w"),
          ensure_ascii=False, indent=1)
fale = [t for t in r.json()["takstbruk"] if t["praksis_type_kode"] == "FALE"][0]
print("PASTE INTO TEST — FALE antall_regninger:", fale["antall_regninger"],
      "sum_refusjon:", fale["sum_refusjon"])
EOF
```
Expected: fixture written; printed literals (live values on 2026-06-12 were
`antall_regninger: 57602`, `sum_refusjon: 4756525.0` — paste whatever the script prints).

- [ ] **Step 2: Write the failing tests** (paste printed literals)

`tests/core/test_kuhr_adapter.py`:
```python
"""KUHR (helserefusjon åpne data) adapter — offline via pre-seeded cache."""

import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.kuhr import KuhrAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Paste literals printed by the capture script (Task 5 / Step 1):
FALE_ANTALL_REGNINGER = 0   # <- replace
FALE_SUM_REFUSJON = 0.0     # <- replace

SOURCE = {"adapter": "kuhr", "id": "no_kuhr", "fagomraade": "LE",
          "fomar": 2023, "tomar": 2023, "kommuner": ["1505"], "takstkoder": ["2ad"]}


def seeded_adapter(tmp_path: Path) -> KuhrAdapter:
    shutil.copy(FIXTURE_DIR / "kuhr_le_1505_fixture.json",
                tmp_path / "kuhr_LE_2023_2023_t2ad_k1505.json")
    return KuhrAdapter(base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path)


class TestFetch:
    def test_tidy_known_values(self, tmp_path: Path) -> None:
        df = seeded_adapter(tmp_path).fetch(SOURCE)
        assert set(df["country"]) == {"NO"}
        assert set(df["geo_id"]) == {"NO-1505"}      # Kristiansund, post-merger stable
        assert set(df["aar"]) == {2023}
        assert set(df["indicator"]) == {"LE_2ad"}
        fale = df[df["praksis_type_kode"] == "FALE"]
        assert len(fale) == 1
        assert fale.iloc[0]["antall_regninger"] == FALE_ANTALL_REGNINGER
        assert fale.iloc[0]["sum_refusjon"] == FALE_SUM_REFUSJON
        assert fale.iloc[0]["value"] == FALE_ANTALL_REGNINGER  # default value_field

    def test_value_field_override(self, tmp_path: Path) -> None:
        src = dict(SOURCE, value_field="sum_refusjon")
        df = seeded_adapter(tmp_path).fetch(src)
        fale = df[df["praksis_type_kode"] == "FALE"]
        assert fale.iloc[0]["value"] == FALE_SUM_REFUSJON

    def test_merger_normalization(self, tmp_path: Path) -> None:
        import json
        ad = seeded_adapter(tmp_path)
        payload = json.loads(
            (FIXTURE_DIR / "kuhr_le_1505_fixture.json").read_text(encoding="utf-8")
        )
        payload["takstbruk"][0]["behandler_kommunenr"] = "0220"  # gamle Asker
        (tmp_path / "kuhr_LE_2023_2023_t2ad_k1505.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        df = ad.fetch(SOURCE)
        assert "NO-3025" in set(df["geo_id"])  # 0220 -> 3025 (Asker, 2020-merger)


@pytest.mark.live
class TestLive:
    def test_live_fagomraader_contains_lege(self) -> None:
        import requests
        data = requests.get("https://opne-data-api.helserefusjon.no/v1/fagomraader",
                            headers={"Accept": "application/json"}, timeout=60).json()
        assert "LE" in {f["fagomraadekode"] for f in data["fagomraader"]}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_kuhr_adapter.py -q`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement**

`src/omsorgsradar/core/adapters/kuhr.py`:
```python
"""KUHR / helserefusjon åpne data (Helsedirektoratet+NAV, NO) adapter.

API verified live 2026-06-12 (docs: github.com/navikt/Helserefusjon-apne-data):
GET {base}/takstbruk/agtakst/kommune/ar?fagomraade=LE&fomar=2023&tomar=2023
    [&takstkoder=2ad,…][&kommuner=1505,…][&praksistyper=FALE,…]
Accept: application/json ->
{"antall":4,"takstbruk":[{"ar":"2023","behandler_kommunenr":"1505",
 "sum_antall_takst":57602,"takstkode":"2ad","fagomraade":"LE",
 "praksis_type_kode":"FALE","samhandler_praksis_type":"Fastlege",
 "antall_regninger":57602,"sum_refusjon":4756525.0,
 "sum_egenandel_betalt_av_pasient":…,"sum_egenandel_dekket_av_folketrygden":…}]}
Geography = practitioner's municipality. No auth.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests

from ...kommune_mergers import normalize_knr_series
from ..geo import make_geo_id
from .cache import DEFAULT_TIMEOUT, JsonCache

logger = logging.getLogger(__name__)

MEASURE_COLUMNS = ["sum_antall_takst", "antall_regninger", "sum_refusjon",
                   "sum_egenandel_betalt_av_pasient",
                   "sum_egenandel_dekket_av_folketrygden"]
TIDY_COLUMNS = (["country", "geo_code", "geo_id", "knr_raw", "aar", "indicator",
                 "fagomraade", "takstkode", "praksis_type_kode",
                 "samhandler_praksis_type"] + MEASURE_COLUMNS + ["value"])
DEFAULT_VALUE_FIELD = "antall_regninger"


class KuhrAdapter:
    source_id = "kuhr"
    DEFAULT_BASE_URL = "https://opne-data-api.helserefusjon.no/v1"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout

    @staticmethod
    def _cache_key(source: Mapping[str, Any]) -> str:
        parts = ["kuhr", str(source["fagomraade"]),
                 str(source["fomar"]), str(source["tomar"])]
        for prefix, field in (("t", "takstkoder"), ("k", "kommuner"),
                              ("p", "praksistyper")):
            vals = source.get(field)
            if vals:
                parts.append(prefix + "-".join(str(v) for v in vals))
        return "_".join(parts)

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        key = self._cache_key(source)
        payload = self.cache.load(key)
        if payload is None:
            params: dict[str, str] = {
                "fagomraade": str(source["fagomraade"]),
                "fomar": str(source["fomar"]),
                "tomar": str(source["tomar"]),
            }
            for field in ("takstkoder", "kommuner", "praksistyper"):
                vals = source.get(field)
                if vals:
                    params[field] = ",".join(str(v) for v in vals)
            url = f"{self.base_url}/takstbruk/agtakst/kommune/ar"
            logger.info("GET %s %s", url, params)
            resp = requests.get(url, params=params,
                                headers={"Accept": "application/json"},
                                timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            self.cache.save(key, payload)

        rows = payload.get("takstbruk", [])
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=TIDY_COLUMNS)
        df["knr_raw"] = df["behandler_kommunenr"].astype(str).str.strip().str.zfill(4)
        df["geo_code"] = normalize_knr_series(df["knr_raw"])
        df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("NO", c))
        df["aar"] = pd.to_numeric(df["ar"], errors="coerce").astype("Int64")
        df["indicator"] = df["fagomraade"].astype(str) + "_" + df["takstkode"].astype(str)
        df["country"] = "NO"
        for col in MEASURE_COLUMNS:
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        value_field = str(source.get("value_field", DEFAULT_VALUE_FIELD))
        if value_field not in MEASURE_COLUMNS:
            raise ValueError(
                f"kuhr source '{source.get('id')}': unknown value_field "
                f"'{value_field}' (known: {MEASURE_COLUMNS})"
            )
        df["value"] = df[value_field]
        logger.info("KUHR %s: %d rows, %d kommuner, years %s",
                    source["fagomraade"], len(df), df["geo_id"].nunique(),
                    sorted(df["aar"].dropna().unique().tolist()))
        return df[TIDY_COLUMNS]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/core/test_kuhr_adapter.py -q`
Expected: 3 passed, 1 deselected.

- [ ] **Step 6: Full suite + commit**

Run: `uv run pytest -x -q` — all pass.
```bash
git add src/omsorgsradar/core/adapters/kuhr.py tests/core/test_kuhr_adapter.py tests/fixtures/kuhr_le_1505_fixture.json
git commit -m "G1: KUHR (NO) adapter — kommune/år takstbruk with merger-normalized geo ids"
```

---

### Task 6: CSV adapter

**Files:**
- Create: `src/omsorgsradar/core/adapters/csvfile.py`
- Test: `tests/core/test_csv_adapter.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_csv_adapter.py`:
```python
"""Local-file CSV adapter."""

from pathlib import Path

import pytest

from omsorgsradar.core.adapters.csvfile import CsvAdapter


def write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestFetch:
    def test_reads_renames_and_types(self, tmp_path: Path) -> None:
        write_csv(tmp_path / "d.csv", "Kommun;År;Värde\n0180;2023;12,5\n1480;2023;9,0\n")
        source = {"adapter": "csv", "id": "se_csv", "path": "d.csv",
                  "sep": ";", "decimal": ",",
                  "rename": {"Kommun": "geo_code", "År": "aar", "Värde": "value"},
                  "provenance": {"institution": "Socialstyrelsen", "url": "https://x"}}
        df = CsvAdapter(base_dir=tmp_path).fetch(source)
        assert list(df.columns) == ["geo_code", "aar", "value"]
        assert df["value"].tolist() == [12.5, 9.0]

    def test_absolute_path_wins(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "abs.csv", "a,b\n1,2\n")
        df = CsvAdapter(base_dir=tmp_path / "elsewhere").fetch(
            {"adapter": "csv", "id": "x", "path": str(p),
             "provenance": {"institution": "T", "url": "https://x"}})
        assert df["a"].tolist() == [1]

    def test_missing_file_raises_with_path(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="nope.csv"):
            CsvAdapter(base_dir=tmp_path).fetch(
                {"adapter": "csv", "id": "x", "path": "nope.csv",
                 "provenance": {"institution": "T", "url": "https://x"}})

    def test_keeps_leading_zeros_in_code_columns(self, tmp_path: Path) -> None:
        write_csv(tmp_path / "z.csv", "geo_code,value\n0180,1\n")
        df = CsvAdapter(base_dir=tmp_path).fetch(
            {"adapter": "csv", "id": "x", "path": "z.csv",
             "dtype": {"geo_code": "str"},
             "provenance": {"institution": "T", "url": "https://x"}})
        assert df["geo_code"].tolist() == ["0180"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_csv_adapter.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`src/omsorgsradar/core/adapters/csvfile.py`:
```python
"""Local CSV adapter (downloaded open-data files, Kaggle official re-hosts).

The realness provenance gate has no known-host fallback for local files, so
csv sources MUST carry [sources.provenance] with institution + url — enforced
by validate_source (registry) and re-checked by the profile-stage gates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

logger = logging.getLogger(__name__)


class CsvAdapter:
    source_id = "csv"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else None

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        p = Path(str(source["path"]))
        if not p.is_absolute():
            p = (self.base_dir or Path.cwd()) / p
        if not p.exists():
            raise FileNotFoundError(
                f"csv source '{source.get('id')}': file not found: {p}"
            )
        df = pd.read_csv(
            p,
            sep=str(source.get("sep", ",")),
            encoding=str(source.get("encoding", "utf-8")),
            decimal=str(source.get("decimal", ".")),
            dtype=dict(source.get("dtype", {})) or None,
        )
        rename = dict(source.get("rename", {}))
        if rename:
            df = df.rename(columns=rename)
        logger.info("CSV %s: %d rows, %d columns from %s",
                    source.get("id"), len(df), len(df.columns), p.name)
        return df
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/core/test_csv_adapter.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/omsorgsradar/core/adapters/csvfile.py tests/core/test_csv_adapter.py
git commit -m "G1: csv adapter for local open-data files"
```

---

### Task 7: Adapter registry + source validation + generic ingest dispatch

**Files:**
- Modify: `src/omsorgsradar/core/adapters/__init__.py`
- Modify: `src/omsorgsradar/core/config.py` (source id pattern)
- Modify: `src/omsorgsradar/ingest.py` (`run_ingest` dispatch + `base_dir` param)
- Modify: `src/omsorgsradar/stages.py` (`stage_ingest` passes `base_dir`)
- Modify: `src/omsorgsradar/pipeline.py` (startup validation)
- Modify: `tests/test_ingest.py` (one error-message expectation)
- Test: `tests/core/test_adapter_registry.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_adapter_registry.py`:
```python
"""Adapter registry: validation errors name the offending key; dispatch works."""

from pathlib import Path

import pytest

from omsorgsradar.core.adapters import (
    LEGACY_SOURCE_IDS,
    REQUIRED_SOURCE_FIELDS,
    make_adapter,
    validate_source,
)
from omsorgsradar.core.config import ConfigError


class TestValidateSource:
    def test_legacy_ids_skip_validation(self) -> None:
        for sid in LEGACY_SOURCE_IDS:
            validate_source({"id": sid, "adapter": "whatever"})  # no raise

    def test_unknown_adapter_names_it(self) -> None:
        with pytest.raises(ConfigError, match="unknown adapter 'nope'"):
            validate_source({"id": "x", "adapter": "nope"})

    @pytest.mark.parametrize("adapter", sorted(REQUIRED_SOURCE_FIELDS))
    def test_missing_required_fields_named(self, adapter: str) -> None:
        with pytest.raises(ConfigError, match="missing required"):
            validate_source({"id": "x", "adapter": adapter})

    def test_csv_requires_full_provenance(self) -> None:
        with pytest.raises(ConfigError, match="provenance"):
            validate_source({"id": "x", "adapter": "csv", "path": "f.csv",
                             "provenance": {"institution": "T"}})  # url missing


class TestMakeAdapter:
    def test_each_adapter_constructs(self, tmp_path: Path) -> None:
        sources = [
            {"id": "a", "adapter": "pxweb",
             "base_url": "https://data.ssb.no/api/v0/no/table", "table": "12209"},
            {"id": "b", "adapter": "sotkanet", "indicators": [127], "years": [2023]},
            {"id": "c", "adapter": "socialstyrelsen", "amne": "amning", "matt": 1},
            {"id": "d", "adapter": "kuhr", "fagomraade": "LE",
             "fomar": 2023, "tomar": 2023},
            {"id": "e", "adapter": "csv", "path": "f.csv",
             "provenance": {"institution": "T", "url": "https://x"}},
        ]
        for src in sources:
            adapter = make_adapter(src, cache_dir=tmp_path, base_dir=tmp_path)
            assert adapter.source_id == src["adapter"]

    def test_fetchers_and_legacy_ids_agree(self) -> None:
        from omsorgsradar.ingest import _FETCHERS
        assert set(_FETCHERS) == set(LEGACY_SOURCE_IDS)


class TestConfigSchema:
    def test_source_id_pattern_locked(self, tmp_path: Path) -> None:
        from omsorgsradar.core.config import load_analysis_config
        (tmp_path / "analysis.toml").write_text(
            '[analysis]\nname = "t"\n[stages]\nlist = ["ingest"]\n'
            '[[sources]]\nadapter = "csv"\nid = "Bad-Id"\npath = "f.csv"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="id"):
            load_analysis_config(tmp_path / "analysis.toml")
```

Also in `tests/test_ingest.py`, update the dispatch-error test (line ~91) — the source has no
`adapter` key, so the new error is `unknown adapter`:

```python
    def test_unknown_source_id_raises(self, tmp_path: Path) -> None:
        sources = [{"id": "nonexistent_source", "base_url": "http://x", "table": "0"}]
        with pytest.raises(ValueError, match="unknown adapter"):
            run_ingest(sources, db_path=tmp_path / "test.duckdb")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_adapter_registry.py -q`
Expected: FAIL — `ImportError: cannot import name 'LEGACY_SOURCE_IDS'`

- [ ] **Step 3: Implement the registry**

Append to `src/omsorgsradar/core/adapters/__init__.py` (keep the existing docstring and
`DatasetAdapter` protocol; add below them):

```python
from pathlib import Path

from ..config import ConfigError
from .csvfile import CsvAdapter
from .kuhr import KuhrAdapter
from .pxweb import PxWebAdapter
from .socialstyrelsen import SocialstyrelsenAdapter
from .sotkanet import SotkanetAdapter

# v1 sources keep their bespoke fetchers in ingest._FETCHERS (dispatch by id,
# byte-identical behavior). A test pins this set == set(_FETCHERS).
LEGACY_SOURCE_IDS = frozenset(
    {"kostra_pleie", "befolkning", "framskrivinger", "fhi_nokkel"}
)

REQUIRED_SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "pxweb": ("base_url", "table"),
    "sotkanet": ("indicators", "years"),
    "socialstyrelsen": ("amne", "matt"),
    "kuhr": ("fagomraade", "fomar", "tomar"),
    "csv": ("path", "provenance"),
}


def _make_pxweb(source, *, cache_dir=None, base_dir=None) -> "PxWebAdapter":
    return PxWebAdapter(base_url=source["base_url"], cache_dir=cache_dir)


def _make_sotkanet(source, *, cache_dir=None, base_dir=None) -> "SotkanetAdapter":
    return SotkanetAdapter(
        base_url=source.get("base_url", SotkanetAdapter.DEFAULT_BASE_URL),
        cache_dir=cache_dir,
    )


def _make_socialstyrelsen(source, *, cache_dir=None, base_dir=None):
    return SocialstyrelsenAdapter(
        base_url=source.get("base_url", SocialstyrelsenAdapter.DEFAULT_BASE_URL),
        cache_dir=cache_dir,
    )


def _make_kuhr(source, *, cache_dir=None, base_dir=None) -> "KuhrAdapter":
    return KuhrAdapter(
        base_url=source.get("base_url", KuhrAdapter.DEFAULT_BASE_URL),
        cache_dir=cache_dir,
    )


def _make_csv(source, *, cache_dir=None, base_dir=None) -> "CsvAdapter":
    return CsvAdapter(base_dir=base_dir)


ADAPTER_FACTORIES = {
    "pxweb": _make_pxweb,
    "sotkanet": _make_sotkanet,
    "socialstyrelsen": _make_socialstyrelsen,
    "kuhr": _make_kuhr,
    "csv": _make_csv,
}


def validate_source(source: Mapping[str, Any]) -> None:
    """Abort at startup with the offending key on bad source blocks (spec rule).

    Legacy v1 ids are exempt — their fetchers own their required keys
    (tests/test_ingest.py pins those).
    """
    sid = source.get("id", "<missing id>")
    if source.get("id") in LEGACY_SOURCE_IDS:
        return
    adapter = source.get("adapter")
    if adapter not in ADAPTER_FACTORIES:
        raise ConfigError(
            f"source '{sid}': unknown adapter '{adapter}' "
            f"(known: {sorted(ADAPTER_FACTORIES)})"
        )
    missing = [f for f in REQUIRED_SOURCE_FIELDS[adapter] if f not in source]
    if missing:
        raise ConfigError(
            f"source '{sid}' (adapter '{adapter}'): missing required field(s) {missing}"
        )
    if adapter == "csv":
        prov = source.get("provenance")
        if (not isinstance(prov, dict) or not prov.get("institution")
                or not prov.get("url")):
            raise ConfigError(
                f"source '{sid}': csv sources require [sources.provenance] "
                "with non-empty institution and url"
            )


def make_adapter(
    source: Mapping[str, Any],
    *,
    cache_dir: Path | None = None,
    base_dir: Path | None = None,
) -> DatasetAdapter:
    validate_source(source)
    return ADAPTER_FACTORIES[source["adapter"]](
        source, cache_dir=cache_dir, base_dir=base_dir
    )
```

- [ ] **Step 4: Lock the source id pattern in the schema**

In `src/omsorgsradar/core/config.py`, ANALYSIS_SCHEMA sources items, change:
```python
                "properties": {
                    "adapter": {"type": "string"},
                    "id": {"type": "string"},
                },
```
to:
```python
                "properties": {
                    "adapter": {"type": "string"},
                    # id becomes a DuckDB table name + cache-key fragment —
                    # pattern-locked so config can never inject SQL/paths.
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                },
```

- [ ] **Step 5: Generic dispatch in run_ingest**

In `src/omsorgsradar/ingest.py`, change the `run_ingest` signature and dispatch block:

```python
def run_ingest(
    sources: list[dict[str, Any]],
    *,
    db_path: Path,
    cache_dir: Path | None = None,
    base_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch every configured source, persist to DuckDB, return DataFrames.

    Legacy v1 source ids dispatch to their bespoke fetchers; anything else
    goes through the adapter registry (core.adapters.make_adapter).
    """
    from .core.adapters import make_adapter

    datasets: dict[str, pd.DataFrame] = {}
    for src in sources:
        sid = src["id"]
        fetcher = _FETCHERS.get(sid)
        if fetcher is not None:
            df = fetcher(src, cache_dir)
        else:
            adapter = make_adapter(src, cache_dir=cache_dir, base_dir=base_dir)
            df = adapter.fetch(src)
        if df is None:
            logger.warning("Source %s returned no data — skipped", sid)
            df = pd.DataFrame()
        datasets[sid] = df
        if not df.empty:
            save_to_duckdb(df, sid, db_path=db_path)
        else:
            logger.info("Source %s returned empty DataFrame — not persisted", sid)
    return datasets
```
(The import is function-local to keep ingest importable without the registry during partial
builds; the old `raise ValueError("no fetcher …")` branch is gone — `make_adapter` raises
`ConfigError`, which is a `ValueError`.)

- [ ] **Step 6: Pass base_dir from the stage; validate at pipeline startup**

`src/omsorgsradar/stages.py`, in `stage_ingest`, change the `run_ingest` call to:
```python
        datasets = run_ingest(
            ctx.config.sources,
            db_path=db_path,
            cache_dir=ctx.data_dir / "cache",
            base_dir=ctx.config.analysis_dir,
        )
```

`src/omsorgsradar/pipeline.py`, right after `cfg = load_run_config(analysis_dir, workflow_path)`:
```python
    from .core.adapters import validate_source

    for src in cfg.sources:
        validate_source(src)
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -x -q`
Expected: all pass, including the updated `test_unknown_source_id_raises` and the canonical
`analyses/omsorgsradar/analysis.toml` startup validation (all four ids are legacy → exempt).

- [ ] **Step 8: Commit**

```bash
git add src/omsorgsradar/core/adapters/__init__.py src/omsorgsradar/core/config.py src/omsorgsradar/ingest.py src/omsorgsradar/stages.py src/omsorgsradar/pipeline.py tests/core/test_adapter_registry.py tests/test_ingest.py
git commit -m "G1: adapter registry, startup source validation, generic ingest dispatch"
```

---

### Task 8: Realness gates module

**Files:**
- Create: `src/omsorgsradar/realness.py`
- Test: `tests/test_realness.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_realness.py`:
```python
"""Realness gates — the 5 Kaggle-fabrication triage checks as code."""

import numpy as np
import pandas as pd
import pytest

from omsorgsradar.realness import (
    GateCheck,
    check_distribution,
    check_duplicates,
    check_missingness,
    resolve_provenance,
    run_realness,
)

SSB_SOURCE = {"id": "kostra_pleie", "adapter": "pxweb",
              "base_url": "https://data.ssb.no/api/v0/no/table", "table": "12209"}


def realistic_df(n: int = 6000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "geo_id": [f"NO-{i % 350:04d}" for i in range(n)],
        "aar": 2015 + (np.arange(n) % 10),
        "value": rng.normal(50, 10, n),
    })
    df.loc[df.sample(frac=0.03, random_state=1).index, "value"] = np.nan
    return df


def fabricated_df(n: int = 10_000) -> pd.DataFrame:
    base = pd.DataFrame({
        "geo_id": [f"NO-{i % 70:04d}" for i in range(n // 2)],
        "aar": 2020,
        "value": np.arange(n // 2) % 100,  # no missing at all
    })
    return pd.concat([base, base], ignore_index=True)  # 50% exact duplicates


class TestProvenance:
    def test_known_host_resolves(self) -> None:
        prov = resolve_provenance(SSB_SOURCE)
        assert prov is not None and "SSB" in prov["institution"]

    def test_explicit_provenance_wins(self) -> None:
        prov = resolve_provenance({"provenance": {"institution": "THL",
                                                  "url": "https://sotkanet.fi"}})
        assert prov == {"institution": "THL", "url": "https://sotkanet.fi"}

    def test_unknown_host_no_provenance_is_none(self) -> None:
        assert resolve_provenance({"base_url": "https://evil.example.com"}) is None

    def test_adapter_default_provenance_when_base_url_omitted(self) -> None:
        # Nordic sources usually omit base_url (adapter default) — provenance
        # must resolve from the adapter name, not FAIL.
        for adapter, marker in (("sotkanet", "THL"), ("kuhr", "Helsedirektoratet"),
                                ("socialstyrelsen", "Socialstyrelsen")):
            prov = resolve_provenance({"id": "x", "adapter": adapter})
            assert prov is not None and marker in prov["institution"], adapter


class TestChecks:
    def test_duplicates_fail_above_one_percent(self) -> None:
        assert check_duplicates(fabricated_df()).status == "FAIL"
        assert check_duplicates(realistic_df()).status == "PASS"

    def test_missingness_warns_on_implausible_perfection(self) -> None:
        assert check_missingness(fabricated_df()).status == "WARN"
        assert check_missingness(realistic_df()).status == "PASS"
        all_nan = realistic_df().assign(value=np.nan)
        assert check_missingness(all_nan).status == "FAIL"

    def test_distribution_zero_variance_fails(self) -> None:
        flat = realistic_df().assign(value=7.0)
        assert check_distribution(flat).status == "FAIL"
        assert check_distribution(realistic_df()).status == "PASS"

    def test_empty_df_skips(self) -> None:
        empty = pd.DataFrame()
        for check in (check_duplicates, check_missingness, check_distribution):
            assert check(empty).status == "SKIP"


class TestVerdict:
    def test_fabricated_dataset_fails_overall(self) -> None:
        report = run_realness(fabricated_df(), SSB_SOURCE)
        assert report["verdict"] == "FAIL"
        by_name = {c["name"]: c["status"] for c in report["checks"]}
        assert by_name["duplicates"] == "FAIL"
        assert by_name["missingness"] == "WARN"

    def test_realistic_known_source_passes(self) -> None:
        report = run_realness(realistic_df(), SSB_SOURCE)
        assert report["verdict"] == "PASS"
        assert {c["name"] for c in report["checks"]} == {
            "provenance", "institution", "duplicates", "missingness", "distribution"
        }

    def test_no_provenance_fails(self) -> None:
        report = run_realness(realistic_df(), {"id": "mystery"})
        assert report["verdict"] == "FAIL"

    def test_empty_df_verdict_skip_never_blocks(self) -> None:
        report = run_realness(pd.DataFrame(), SSB_SOURCE)
        assert report["verdict"] in ("PASS", "SKIP")  # empty data must not gate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_realness.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsorgsradar.realness'`

- [ ] **Step 3: Implement**

`src/omsorgsradar/realness.py`:
```python
"""Dataset realness gates — the Kaggle-fabrication triage checks as code.

Background (wiki tech/agentic-healthcare-analysis-workflow-2026, Retraction
Watch 2026-05): 124 papers were built on fabricated Kaggle health datasets —
thousands of exact duplicates, implausibly few missing values, no traceable
institution. These five checks run in the profile stage on every dataset,
the verdict is published in quality_profile.json, and a FAIL aborts the
pipeline before analysis (DECISIONS.md).

Checks: provenance (URL/DOI), named institution, exact-duplicate rate,
missingness plausibility, distribution sanity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import pandas as pd

# Thresholds (research-derived defaults; override per analysis via
# [params.realness] once a real case demands it — YAGNI until then).
DUPLICATE_FAIL_RATE = 0.01      # >1% exact duplicate rows
ALL_MISSING_FAIL_RATE = 0.95    # value column effectively empty
PERFECT_DATA_MIN_ROWS = 5000    # 0 missing at this size is suspicious
ZERO_VARIANCE_MIN_ROWS = 100

KNOWN_HOSTS: dict[str, str] = {
    "data.ssb.no": "Statistisk sentralbyrå (SSB)",
    "statistikk-data.fhi.no": "Folkehelseinstituttet (FHI)",
    "sotkanet.fi": "Terveyden ja hyvinvoinnin laitos (THL)",
    "sdb.socialstyrelsen.se": "Socialstyrelsen (Sverige)",
    "opne-data-api.helserefusjon.no": "Helsedirektoratet / NAV (helserefusjon, KUHR)",
}

# Fallback when a source omits base_url (the adapter supplies its default URL):
ADAPTER_PROVENANCE: dict[str, dict[str, str]] = {
    "sotkanet": {"institution": "Terveyden ja hyvinvoinnin laitos (THL)",
                 "url": "https://sotkanet.fi/rest/1.1"},
    "socialstyrelsen": {"institution": "Socialstyrelsen (Sverige)",
                        "url": "https://sdb.socialstyrelsen.se/api/v1/sv"},
    "kuhr": {"institution": "Helsedirektoratet / NAV (helserefusjon, KUHR)",
             "url": "https://opne-data-api.helserefusjon.no/v1"},
}


@dataclass(frozen=True)
class GateCheck:
    name: str
    status: str  # PASS | WARN | FAIL | SKIP
    detail: str


def resolve_provenance(source: Mapping[str, Any]) -> dict[str, str] | None:
    """Explicit [sources.provenance] wins; else a known API host; else the
    adapter's default endpoint (sources usually omit base_url)."""
    prov = source.get("provenance")
    if isinstance(prov, Mapping) and prov.get("institution") and prov.get("url"):
        return {"institution": str(prov["institution"]), "url": str(prov["url"])}
    base = str(source.get("base_url", ""))
    host = urlparse(base).netloc.lower()
    for known, institution in KNOWN_HOSTS.items():
        if host == known or host.endswith("." + known):
            return {"institution": institution, "url": base}
    if not base:
        return ADAPTER_PROVENANCE.get(str(source.get("adapter", "")))
    return None


def check_provenance(source: Mapping[str, Any]) -> GateCheck:
    prov = resolve_provenance(source)
    if prov is None:
        return GateCheck("provenance", "FAIL",
                         "no resolvable provenance — add [sources.provenance] "
                         "institution+url or use a known open-data host")
    return GateCheck("provenance", "PASS", f"url: {prov['url']}")


def check_institution(source: Mapping[str, Any]) -> GateCheck:
    prov = resolve_provenance(source)
    if prov is None:
        return GateCheck("institution", "FAIL", "no named institution")
    return GateCheck("institution", "PASS", prov["institution"])


def check_duplicates(df: pd.DataFrame) -> GateCheck:
    if df.empty:
        return GateCheck("duplicates", "SKIP", "empty dataset")
    rate = float(df.duplicated().mean())
    if rate > DUPLICATE_FAIL_RATE:
        return GateCheck("duplicates", "FAIL",
                         f"{rate:.1%} exact duplicate rows (limit {DUPLICATE_FAIL_RATE:.0%})")
    return GateCheck("duplicates", "PASS", f"{rate:.2%} exact duplicate rows")


def check_missingness(df: pd.DataFrame) -> GateCheck:
    if df.empty or "value" not in df.columns:
        return GateCheck("missingness", "SKIP", "empty dataset or no value column")
    rate = float(df["value"].isna().mean())
    if rate >= ALL_MISSING_FAIL_RATE:
        return GateCheck("missingness", "FAIL",
                         f"value column {rate:.0%} missing — no usable data")
    if rate == 0.0 and len(df) >= PERFECT_DATA_MIN_ROWS:
        return GateCheck("missingness", "WARN",
                         f"0 missing values in {len(df):,} rows — implausibly "
                         "perfect for real-world data (fabrication signature)")
    return GateCheck("missingness", "PASS", f"{rate:.1%} missing in value column")


def check_distribution(df: pd.DataFrame) -> GateCheck:
    if df.empty or "value" not in df.columns:
        return GateCheck("distribution", "SKIP", "empty dataset or no value column")
    clean = pd.to_numeric(df["value"], errors="coerce").dropna()
    if clean.empty:
        return GateCheck("distribution", "SKIP", "no numeric values")
    if len(clean) >= ZERO_VARIANCE_MIN_ROWS and clean.nunique() == 1:
        return GateCheck("distribution", "FAIL",
                         f"zero variance: all {len(clean):,} values == {clean.iloc[0]}")
    return GateCheck(
        "distribution", "PASS",
        f"min={clean.min():.4g} median={clean.median():.4g} max={clean.max():.4g}",
    )


def run_realness(df: pd.DataFrame, source: Mapping[str, Any]) -> dict[str, Any]:
    """All five gates; verdict FAIL > WARN > PASS; all-SKIP data never gates."""
    checks = [
        check_provenance(source),
        check_institution(source),
        check_duplicates(df),
        check_missingness(df),
        check_distribution(df),
    ]
    statuses = {c.status for c in checks}
    if "FAIL" in statuses:
        verdict = "FAIL"
    elif "WARN" in statuses:
        verdict = "WARN"
    elif statuses == {"SKIP"}:
        verdict = "SKIP"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "checks": [asdict(c) for c in checks]}
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_realness.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/omsorgsradar/realness.py tests/test_realness.py
git commit -m "G1: realness gates — provenance, institution, duplicates, missingness, distribution"
```

---

### Task 9: Wire realness into the profile stage (mandatory gate)

**Files:**
- Modify: `src/omsorgsradar/profile.py` (generic profiler + realness attachment)
- Modify: `src/omsorgsradar/stages.py` (`stage_profile` raises on FAIL)
- Modify: `src/omsorgsradar/core/contracts.py` (schema)
- Modify: `src/omsorgsradar/pipeline.py` (journal the *failing* stage, not "verify")
- Test: extend `tests/test_profile.py` + `tests/test_pipeline_gate.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile.py`:
```python
class TestRealnessWiring:
    SOURCES = [
        {"id": "kostra_pleie", "adapter": "pxweb",
         "base_url": "https://data.ssb.no/api/v0/no/table", "table": "12209"},
        {"id": "befolkning", "adapter": "pxweb",
         "base_url": "https://data.ssb.no/api/v0/no/table", "table": "07459"},
        {"id": "framskrivinger", "adapter": "pxweb",
         "base_url": "https://data.ssb.no/api/v0/no/table", "table": "12880"},
        {"id": "fhi_nokkel", "adapter": "fhi",
         "base_url": "https://statistikk-data.fhi.no/api/open/v1", "source": "nokkel"},
    ]

    def test_realness_attached_per_dataset(self, fixture_datasets) -> None:
        from omsorgsradar.profile import profile_all

        report = profile_all(fixture_datasets, sources=self.SOURCES)
        for name in fixture_datasets:
            assert "realness" in report["datasets"][name], name
            assert report["datasets"][name]["realness"]["verdict"] in (
                "PASS", "WARN", "SKIP"
            )

    def test_no_sources_keeps_v1_shape(self, fixture_datasets) -> None:
        from omsorgsradar.profile import profile_all

        report = profile_all(fixture_datasets)
        for name in fixture_datasets:
            assert "realness" not in report["datasets"][name]

    def test_generic_dataset_profiled(self) -> None:
        import pandas as pd
        from omsorgsradar.profile import profile_all

        df = pd.DataFrame({"geo_id": ["FI-091"], "aar": [2023], "value": [1.0]})
        report = profile_all({"fi_test": df})
        generic = report["datasets"]["fi_test"]
        assert generic["n_rows"] == 1
        assert generic["year_range"] == [2023, 2023]
        assert generic["n_geo"] == 1
```

Append to `tests/test_pipeline_gate.py`:
```python
class TestRealnessGate:
    def _analysis_dir(self, tmp_path):
        adir = tmp_path / "analyses" / "fabricated"
        adir.mkdir(parents=True)
        rows = "\n".join("NO-0301,2020,7.0" for _ in range(200))
        (adir / "fake.csv").write_text("geo_id,aar,value\n" + rows + "\n")
        (adir / "analysis.toml").write_text(
            '[analysis]\nname = "fabricated"\n'
            '[stages]\nlist = ["ingest", "profile"]\n'
            '[[sources]]\nadapter = "csv"\nid = "fake"\npath = "fake.csv"\n'
            '[sources.provenance]\ninstitution = "Test"\nurl = "https://example.org"\n',
            encoding="utf-8",
        )
        return adir

    def test_fabricated_csv_aborts_after_publishing_verdict(self, tmp_path) -> None:
        import json
        import pytest
        from omsorgsradar.core.registry import PipelineGateError
        from omsorgsradar.pipeline import run_pipeline

        adir = self._analysis_dir(tmp_path)
        data_dir = tmp_path / "data"
        with pytest.raises(PipelineGateError, match="realness"):
            run_pipeline(
                adir,
                data_dir=data_dir,
                reports_dir=tmp_path / "reports",
                runs_dir=tmp_path / "runs",
            )
        # Verdict was published before the abort (spec: verdict in the profile)
        quality = json.loads((data_dir / "quality_profile.json").read_text())
        assert quality["datasets"]["fake"]["realness"]["verdict"] == "FAIL"
        # 200 identical duplicated rows + zero variance triggered it
        statuses = {c["name"]: c["status"]
                    for c in quality["datasets"]["fake"]["realness"]["checks"]}
        assert statuses["duplicates"] == "FAIL"
        assert statuses["distribution"] == "FAIL"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_profile.py tests/test_pipeline_gate.py -q`
Expected: new tests FAIL (`profile_all() got an unexpected keyword argument 'sources'`, no gate).

- [ ] **Step 3: Extend profile.py**

In `src/omsorgsradar/profile.py`, add after `profile_population` (before `profile_all`):

```python
def profile_generic(df: pd.DataFrame) -> dict[str, Any]:
    """Profile any adapter-produced tidy dataset (Nordic adapters, csv)."""
    report: dict[str, Any] = {
        "source": "generic",
        "n_rows": len(df),
        "missing_rates": {},
        "year_range": None,
        "n_geo": None,
        "outliers": {},
    }
    for col in df.columns:
        report["missing_rates"][col] = round(_missing_rate(df[col]), 4)
    if "aar" in df.columns:
        years = pd.to_numeric(df["aar"], errors="coerce").dropna()
        if not years.empty:
            report["year_range"] = [int(years.min()), int(years.max())]
    if "geo_id" in df.columns:
        report["n_geo"] = int(df["geo_id"].nunique())
    if "value" in df.columns:
        report["outliers"]["value"] = _outlier_iqr(
            pd.to_numeric(df["value"], errors="coerce")
        )
    return report
```

Replace the `profile_all` signature and add the generic+realness handling — the function becomes:

```python
def profile_all(
    datasets: dict[str, pd.DataFrame],
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run profiling on all datasets and return combined quality report.

    Args:
        datasets: Dict mapping table name → DataFrame (from :func:`ingest.run_ingest`).
        sources: The analysis ``[[sources]]`` blocks. When given, every dataset
            with a matching source id gets a ``realness`` section (the 5 gates);
            the profile stage aborts the pipeline on any FAIL verdict.

    Returns:
        Combined quality report dict.
    """
    from .realness import run_realness

    report: dict[str, Any] = {"datasets": {}}
    specialized = {"kostra_pleie", "befolkning", "framskrivinger", "fhi_nokkel"}

    if "kostra_pleie" in datasets:
        report["datasets"]["kostra_pleie"] = profile_kostra(datasets["kostra_pleie"])

    if "befolkning" in datasets:
        report["datasets"]["befolkning"] = profile_population(datasets["befolkning"])

    if "framskrivinger" in datasets:
        df_proj = datasets["framskrivinger"]
        report["datasets"]["framskrivinger"] = {
            "source": "SSB population projections",
            "n_rows": len(df_proj),
            "is_national_aggregate": bool(
                df_proj["knr"].eq("NATIONAL").all() if "knr" in df_proj.columns else True
            ),
            "year_range": (
                [int(df_proj["aar"].min()), int(df_proj["aar"].max())]
                if "aar" in df_proj.columns and not df_proj.empty
                else None
            ),
        }

    if "fhi_nokkel" in datasets:
        df_fhi = datasets["fhi_nokkel"]
        report["datasets"]["fhi_nokkel"] = {
            "source": "FHI NOKKEL (folkehelsestatistikk)",
            "n_rows": len(df_fhi),
            "n_kommuner": int(df_fhi["knr"].nunique()) if "knr" in df_fhi.columns else 0,
            "indicators": (
                df_fhi["indicator"].unique().tolist() if "indicator" in df_fhi.columns else []
            ),
            "missing_value_rate": round(_missing_rate(df_fhi.get("value", pd.Series(dtype=float))), 4),
        }

    for name, df in datasets.items():
        if name not in specialized:
            report["datasets"][name] = profile_generic(df)

    if sources is not None:
        by_id = {s["id"]: s for s in sources}
        for name, df in datasets.items():
            if name in by_id and name in report["datasets"]:
                report["datasets"][name]["realness"] = run_realness(df, by_id[name])

    return report
```
(The four specialized blocks are the existing code, unchanged — only the generic loop and the
realness loop are new.)

- [ ] **Step 4: Gate in stage_profile**

In `src/omsorgsradar/stages.py`, replace `stage_profile` with:

```python
def stage_profile(ctx: StageContext) -> None:
    from .profile import profile_all, save_quality_report

    quality = profile_all(ctx.state["datasets"], sources=ctx.config.sources)
    path = ctx.data_dir / "quality_profile.json"
    save_quality_report(quality, path=path)
    validate_artifact("quality_profile", quality)
    write_manifest(path, artifact="quality_profile", producer="profile")
    ctx.state["quality_report"] = quality
    ctx.artifacts["quality_profile"] = path
    # Realness gate (DECISIONS.md): FAIL aborts — but only after the verdict
    # is on disk so the failure is inspectable.
    failed = [
        name
        for name, ds in quality["datasets"].items()
        if isinstance(ds, dict) and ds.get("realness", {}).get("verdict") == "FAIL"
    ]
    if failed:
        raise PipelineGateError(
            f"realness gate FAIL for dataset(s): {', '.join(sorted(failed))} — "
            f"see {path}"
        )
```

- [ ] **Step 5: Journal the failing stage correctly**

In `src/omsorgsradar/pipeline.py`, the `except PipelineGateError` branch hardcodes `"verify"`.
Track the current stage instead — change the run loop to:

```python
    current_stage = "<startup>"
    try:
        for name in stages:
            current_stage = name
            before = dict(ctx.artifacts)
            t0 = time.monotonic()
            logger.info("Stage: %s", name)
            reg.get(name)(ctx)
            journal.record_stage(
                name,
                artifacts=[
                    str(p) for k, p in ctx.artifacts.items() if k not in before
                ],
                duration_s=round(time.monotonic() - t0, 3),
            )
    except PipelineGateError as exc:
        journal.record_stage(current_stage, meta={"error": str(exc)})
        journal.finalize("gate_failed")
        raise
```

- [ ] **Step 6: Schema for the realness section**

In `src/omsorgsradar/core/contracts.py`, replace `QUALITY_PROFILE_SCHEMA` with:

```python
QUALITY_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["datasets"],
    "properties": {
        "datasets": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "realness": {
                        "type": "object",
                        "required": ["verdict", "checks"],
                        "properties": {
                            "verdict": {"enum": ["PASS", "WARN", "FAIL", "SKIP"]},
                            "checks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["name", "status"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "status": {
                                            "enum": ["PASS", "WARN", "FAIL", "SKIP"]
                                        },
                                        "detail": {"type": "string"},
                                    },
                                },
                            },
                        },
                    }
                },
            },
        }
    },
}
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -x -q`
Expected: all pass — existing verify-gate tests still green (verify failures still journal as
"verify" via `current_stage`), v1 profile tests unchanged (no `sources` → no realness section).

- [ ] **Step 8: Commit**

```bash
git add src/omsorgsradar/profile.py src/omsorgsradar/stages.py src/omsorgsradar/pipeline.py src/omsorgsradar/core/contracts.py tests/test_profile.py tests/test_pipeline_gate.py
git commit -m "G1: realness gates mandatory in profile stage — verdict published, FAIL aborts"
```

---

### Task 10: Offline Nordic integration test

**Files:**
- Test: `tests/test_nordic_integration.py`

- [ ] **Step 1: Write the test** (it should pass immediately if Tasks 1–9 are correct — it is
the cross-adapter contract proof, not TDD for new code)

`tests/test_nordic_integration.py`:
```python
"""Fixture-driven ingest+profile run across sotkanet + kuhr + csv — no network.

Caches are pre-seeded under the exact keys the adapters compute, so any HTTP
attempt would hit an unreachable host and fail the test.
"""

import json
import shutil
from pathlib import Path

import duckdb

from omsorgsradar.pipeline import run_pipeline

FIXTURE_DIR = Path(__file__).parent / "fixtures"

ANALYSIS_TOML = """\
[analysis]
name = "nordisk-test"
question = "integrasjonstest"

[stages]
list = ["ingest", "profile"]

[[sources]]
adapter = "sotkanet"
id = "fi_test"
indicators = [127]
years = [2023]

[[sources]]
adapter = "kuhr"
id = "no_kuhr"
fagomraade = "LE"
fomar = 2023
tomar = 2023
kommuner = ["1505"]
takstkoder = ["2ad"]

[[sources]]
adapter = "csv"
id = "se_csv"
path = "se_data.csv"
[sources.rename]
kommun = "geo_code"
ar = "aar"
varde = "value"
[sources.provenance]
institution = "Socialstyrelsen (Sverige)"
url = "https://www.socialstyrelsen.se/statistik-och-data/oppna-data/"
"""


def test_nordic_ingest_profile_offline(tmp_path: Path) -> None:
    adir = tmp_path / "analyses" / "nordisk-test"
    adir.mkdir(parents=True)
    (adir / "analysis.toml").write_text(ANALYSIS_TOML, encoding="utf-8")
    (adir / "se_data.csv").write_text(
        "kommun,ar,varde\n0180,2023,12.5\n1480,2023,9.0\n", encoding="utf-8"
    )

    data_dir = tmp_path / "data"
    cache = data_dir / "cache"
    cache.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "sotkanet_regions_fixture.json",
                cache / "sotkanet_regions.json")
    shutil.copy(FIXTURE_DIR / "sotkanet_127_fixture.json",
                cache / "sotkanet_127_2023_2023_total.json")
    shutil.copy(FIXTURE_DIR / "kuhr_le_1505_fixture.json",
                cache / "kuhr_LE_2023_2023_t2ad_k1505.json")

    run_pipeline(
        adir,
        data_dir=data_dir,
        reports_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
    )

    quality = json.loads((data_dir / "quality_profile.json").read_text(encoding="utf-8"))
    for ds in ("fi_test", "no_kuhr", "se_csv"):
        verdict = quality["datasets"][ds]["realness"]["verdict"]
        assert verdict in ("PASS", "WARN"), f"{ds}: {verdict}"

    con = duckdb.connect(str(data_dir / "nordisk-test.duckdb"), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()
    assert {"fi_test", "no_kuhr", "se_csv"} <= tables

    fi = json.loads((data_dir / "quality_profile.json").read_text(encoding="utf-8"))
    assert fi["datasets"]["fi_test"]["n_geo"] == 5  # the five fixture kuntas
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_nordic_integration.py -q`
Expected: PASS. If a cache-key mismatch makes an adapter hit the network, the unreachable-host
error names the adapter — fix the seed filename, not the adapter.

- [ ] **Step 3: Full suite + commit**

Run: `uv run pytest -x -q` — all pass.
```bash
git add tests/test_nordic_integration.py
git commit -m "G1: offline cross-adapter integration test (sotkanet+kuhr+csv -> profile gates)"
```

---

### Task 11: Docs, skill, status

**Files:**
- Create: `docs/adapters.md`
- Modify: `.claude/skills/pipeline-stages/SKILL.md`, `CLAUDE.md`, `status.md`

- [ ] **Step 1: Write `docs/adapters.md`**

```markdown
# Dataset adapters — `[[sources]]` reference

Adapters live in `src/omsorgsradar/core/adapters/`; dispatch is by `adapter` key
(legacy v1 ids `kostra_pleie`/`befolkning`/`framskrivinger`/`fhi_nokkel` keep bespoke
fetchers). Required fields are validated at pipeline startup. All HTTP adapters cache
raw JSON to `data/cache/` (never read it into model context — hook-enforced).
Nordic adapters emit the tidy contract: `country, geo_code, geo_id, geo_name, aar,
indicator, value` with `geo_id` = `NO-1505` / `SE-0180` / `FI-091` (`core/geo.py`).

## pxweb (SSB; FOHM/DST share the shape)
Required: `base_url`, `table`. Optional: `var_map`, `query`, `cache_key`.

## sotkanet — THL, Finland (CC BY 4.0)
Required: `indicators` (list of ids), `years` (list). Optional: `genders` ("total"),
`base_url`. API: `sotkanet.fi/rest/1.1` — `/json?indicator=…&years=…` + `/regions`
(KUNTA rows). ~3,700 indicators, kommune level.

## socialstyrelsen — Sweden
Required: `amne` (topic slug from `GET /api/v1/sv`), `matt` (measure id). Optional:
`years`, `regions`, `per_sida`, `max_pages`, `base_url`. Paginated via `nasta_sida`;
suppressed values ("X") become NaN, raw string kept in `value_raw`. ⚠ The API has
**no äldreomsorg topic** (verified 2026-06-12) — Swedish elder-care data comes from
Socialstyrelsen open-data CSV files via the csv adapter.

## kuhr — Helsedirektoratet/NAV helserefusjon, Norway
Required: `fagomraade` (e.g. "LE"), `fomar`, `tomar`. Optional: `takstkoder`,
`kommuner`, `praksistyper`, `value_field` (default `antall_regninger`), `base_url`.
API: `opne-data-api.helserefusjon.no/v1/takstbruk/agtakst/kommune/ar` (docs:
github.com/navikt/Helserefusjon-apne-data). Geography = practitioner's kommune;
pre-2020 kommune numbers are merger-normalized.

## csv — local files
Required: `path` (relative to the analysis dir), `provenance` (institution + url —
no known-host fallback for local files). Optional: `sep`, `encoding`, `decimal`,
`dtype`, `rename`.

## Realness gates (profile stage, mandatory)
Five checks per dataset: provenance, named institution, duplicate rate (>1% FAIL),
missingness plausibility (0 missing at scale WARN; ≥95% missing FAIL), distribution
sanity (zero variance FAIL). Verdict in `data/quality_profile.json`; FAIL aborts the
pipeline after the verdict is written. Thresholds: `src/omsorgsradar/realness.py`.
```

- [ ] **Step 2: Update the skill**

In `.claude/skills/pipeline-stages/SKILL.md` §Extend, after the "New analysis" bullet add:

```markdown
- Adapters: `pxweb | sotkanet | socialstyrelsen | kuhr | csv` — required fields per
  adapter in `docs/adapters.md`; validation runs at pipeline startup. New API shape →
  new module in `core/adapters/` + offline fixture + known-value test (never edit an
  existing adapter's behavior for a new dataset).
- Realness gates run in `profile` on every dataset (verdict in
  `data/quality_profile.json`); a FAIL verdict aborts before analyze. csv sources
  must declare `[sources.provenance]` institution + url.
```

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md` (repo), extend the `## v2 engine (G0+)` block's adapter mention — change:

```markdown
Variants = new instance folder,
never core edits. Run/extend/debug: see skill `pipeline-stages`.
```
to:
```markdown
Adapters: pxweb, sotkanet (FI), socialstyrelsen (SE), kuhr (NO), csv —
`docs/adapters.md`; realness gates mandatory in profile. Variants = new instance
folder, never core edits. Run/extend/debug: see skill `pipeline-stages`.
```

- [ ] **Step 4: status.md entry**

Append under the G0 entry (adjust test count to the real final number):

```markdown
- **2026-06-12** — **G1 (Nordic adapters + realness gates) shipped.** Adapters:
  sotkanet (THL FI), socialstyrelsen (SE statistikdatabas, paginated), kuhr
  (helserefusjon NO, merger-normalized), csv (local open data) — each with offline
  fixture + known-value test from live-verified API responses; shared sanitized JSON
  cache; NO/SE/FI geo harmonization (`core/geo.py`, `NO-1505`-style ids); adapter
  registry + startup source validation (id pattern-locked). Realness gates (5
  Kaggle-triage checks) mandatory in profile — verdict published, FAIL aborts
  (fabricated-dataset gate test green). ⚠ Socialstyrelsen API has no äldreomsorg
  topic (verified live) — G2 Swedish elder-care via open-data CSV. Tests: 114 → N.
  **Next: G2 — `analyses/nordisk-omsorg` end-to-end.**
```

- [ ] **Step 5: Final verification + commit**

Run: `uv run pytest -q` (full suite, offline) and `uv run pytest -m live -q` (live API checks —
acceptable to note failures if an API is briefly down, but investigate any shape mismatch).
```bash
git add docs/adapters.md .claude/skills/pipeline-stages/SKILL.md CLAUDE.md status.md
git commit -m "G1: close out — adapters reference, skill + CLAUDE.md + status updates"
```

---

## Self-review checklist (run after drafting, before execution)

- Spec §Adapters: sotkanet ✓ (T3), socialstyrelsen ✓ (T4), kuhr ✓ (T5), csv ✓ (T6), shared
  caching ✓ (T1), per-adapter offline fixture + known-value test ✓ (T3–T6), realness gates
  mandatory in profile with published verdict ✓ (T8–T9), geo harmonization NO/SE/FI ✓ (T2),
  fabricated-dataset gate test ✓ (T8 unit + T9 pipeline-level).
- Out of G1 scope (deliberate): `base_url` host allowlisting (G3 security gate, with
  machine-authored configs), äldreomsorg dataset selection (G2), report/site changes (G2/G6).
- v1 behavior preserved: legacy ids bypass registry; `profile_all(datasets)` without `sources`
  has the v1 shape; verify-gate tests unchanged.
