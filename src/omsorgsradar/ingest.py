"""Ingest module — queries SSB PxWebAPI v2 and FHI NOKKEL, normalises
kommune IDs, and persists to DuckDB.

Design notes
------------
- All HTTP calls go through :class:`.core.adapters.pxweb.PxWebAdapter`.  A
  ``cache_dir`` argument writes raw responses to disk so tests and re-runs
  avoid network round-trips.
- The entire SSB JSON-stat2 payload → DataFrame path is deterministic and
  unit-testable with a small fixture (see ``tests/fixtures/``).
- DuckDB is opened as a file DB at ``data/omsorgsradar.duckdb``; tables are
  (re)created with REPLACE semantics so the pipeline is idempotent.

SSB PxWebAPI v2 endpoint discovery
------------------------------------
Tables used:
  - ``12209``  — KOSTRA Pleie og omsorg, kommuner (all years)
  - ``07459``  — Folkemengde etter alder, 1-årsklasser (current population)
  - ``13873``  — Folkemengde og befolkningsframskrivinger MMMM (medium scenario)
        NB: the exact population-projection table IDs shift; this module
        queries the metadata endpoint first and falls back to table 12880
        (the long-standing projection series).

FHI NOKKEL endpoint
-------------------
  Base URL: https://statistikk-data.fhi.no/api/open/v1/
  Used for socioeconomic context (levekårsindeks per kommune).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import requests

from .core.adapters.pxweb import (  # noqa: F401  (backwards-compat re-exports)
    PxWebAdapter,
    REQUEST_PAUSE,
    REQUEST_TIMEOUT,
    jsonstat2_to_df,
)
from .kommune_mergers import normalize_knr_series

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "omsorgsradar.duckdb"
DEFAULT_CACHE = Path(__file__).parent.parent.parent / "data" / "cache"

# ── Population-projection fetch (SSB national framskriving) ───────────────────
# Table 13599 (Framskrevet folkemengde etter kjønn, alder, framskrivingsalternativ)
# is the national 1-year-age projection table reaching past 2035. The "framskrivinger"
# source in analysis.toml is configured to it; these defaults shape the 80+ ×
# main-alternative selection. (The old config pointed at 12880, which is the
# *macroeconomic* accounts table — no age dimension, ends 2029 — so the projection
# rate was never derivable; see docs/api_drift.md and Finding 3.)
PROJECTION_MIN_AGE = 80
PROJECTION_TARGET_YEAR = 2035
# SSB main-alternative ("hovedalternativ") projection code. 13599 labels it "MMM";
# the long-form "MMMM" appears in some regional tables. We discover the actual
# main-alternative code from metadata and fall back to these candidates.
PROJECTION_MAIN_ALT_CANDIDATES = ("MMMM", "MMM")
PROJECTION_ALT_VAR_CANDIDATES = ("Framskriv", "Alternativ", "PerFramskrives")


# ──────────────────────────────────────────────────────────────────────────────
# SSB table metadata discovery
# ──────────────────────────────────────────────────────────────────────────────

def _discover_ssb_table(base_url: str, table_id: str) -> dict[str, Any]:
    """Fetch the metadata for an SSB table to discover available variables."""
    url = f"{base_url.rstrip('/')}/{table_id}"
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ──────────────────────────────────────────────────────────────────────────────
# SSB fetchers
# ──────────────────────────────────────────────────────────────────────────────

def fetch_kostra_pleie(
    *,
    base_url: str,
    table_id: str,
    var_map: dict[str, str],
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Fetch KOSTRA table (default 12209) — pleie og omsorg, alle kommuner, alle år.

    Returns a tidy DataFrame with columns:
        - ``knr_raw``: original kommune number from SSB
        - ``knr``: normalised post-2020 kommune number
        - ``knr_name``: municipality name from SSB labels
        - ``aar``: year (int)
        - ``ContentsCode``: KOSTRA variable code
        - ``value``: numeric value (may be NaN for unreported years)

    Raises:
        requests.HTTPError: on API failure.
    """
    wanted_codes = list(var_map.values())

    logger.info("Discovering KOSTRA table %s metadata", table_id)
    meta = _discover_ssb_table(base_url, table_id)

    variables = meta.get("variables", [])
    # Region variable has a long code in this table
    region_var = next(
        (v for v in variables if "region" in v.get("code", "").lower()
         or v.get("code") == "Region"),
        None,
    )
    time_var = next(
        (v for v in variables if v.get("code") in ("Tid", "AAR", "Aar")), None
    )
    contents_var = next(
        (v for v in variables if v.get("code") == "ContentsCode"), None
    )

    if region_var is None or time_var is None or contents_var is None:
        raise ValueError(
            f"Unexpected table structure for {table_id}. "
            f"Variables: {[v.get('code') for v in variables]}"
        )

    region_code = region_var["code"]  # e.g. "KOKkommuneregion0000"
    contents_values: list[str] = contents_var.get("values", [])
    all_years: list[str] = time_var.get("values", [])

    # Pick the relevant KOSTRA variables (use discovered codes)
    wanted_contents = [c for c in contents_values if c in wanted_codes]
    if not wanted_contents:
        logger.warning(
            "var_map values not found; available: %s. Using first 6.",
            contents_values[:6],
        )
        wanted_contents = contents_values[:6]

    query = {
        "query": [
            {
                "code": region_code,
                "selection": {"filter": "all", "values": ["*"]},
            },
            {
                "code": time_var["code"],
                "selection": {"filter": "item", "values": all_years},
            },
            {
                "code": "ContentsCode",
                "selection": {"filter": "item", "values": wanted_contents},
            },
        ],
        "response": {"format": "json-stat2"},
    }

    adapter = PxWebAdapter(base_url=base_url, cache_dir=cache_dir)
    payload = adapter.post_table(table_id, query)
    df = jsonstat2_to_df(payload, use_codes=True)

    # Build name lookup from region metadata (codes → human names via label dict)
    region_vals = region_var.get("values", [])
    region_texts = region_var.get("valueTexts", region_vals)
    knr_name_map: dict[str, str] = dict(zip(region_vals, region_texts))

    # Rename dimension columns to consistent names
    rename_map: dict[str, str] = {}
    if time_var["code"] in df.columns:
        rename_map[time_var["code"]] = "aar"
    if region_code in df.columns:
        rename_map[region_code] = "knr_raw"

    df = df.rename(columns=rename_map)

    # knr_raw now holds the 4-digit code directly from SSB values
    df["knr_raw"] = df["knr_raw"].astype(str).str.strip().str.zfill(4)
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["knr_name"] = df["knr_raw"].map(knr_name_map).fillna("")
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")

    logger.info(
        "KOSTRA %s: %d rows, %d kommuner, years %s–%s",
        table_id,
        len(df),
        df["knr"].nunique(),
        int(df["aar"].min()),
        int(df["aar"].max()),
    )
    return df


def fetch_population_current(
    *,
    base_url: str,
    table_id: str,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Fetch current population by age (1-year classes) from SSB (default table 07459).

    Fetches only ages 80+ (codes 080–104) for all kommuner, both sexes summed,
    for the most recent 10 years.

    Returns a tidy DataFrame with columns:
        - ``knr_raw``: original kommune number
        - ``knr``: normalised post-2020 kommune number
        - ``alder``: age label (e.g. "80 år")
        - ``aar``: year (int)
        - ``value``: population count
    """
    logger.info("Fetching SSB table %s — folkemengde etter alder (80+)", table_id)
    meta = _discover_ssb_table(base_url, table_id)
    variables = meta.get("variables", [])

    time_var = next(
        (v for v in variables if v.get("code") in ("Tid", "AAR", "Aar")), None
    )
    age_var = next(
        (v for v in variables if v.get("code") in ("Alder", "alder")), None
    )
    sex_var = next(
        (v for v in variables if v.get("code") in ("Kjonn", "kjonn")), None
    )
    region_var = next(
        (v for v in variables if v.get("code") == "Region"), None
    )

    if time_var is None or age_var is None or region_var is None:
        raise ValueError(
            f"Expected variables not found in {table_id}. Found: {[v.get('code') for v in variables]}"
        )

    all_years: list[str] = time_var.get("values", [])
    # Use most recent 10 years
    recent_years = all_years[-10:] if len(all_years) > 10 else all_years

    # Find all 4-char kommune codes (exactly 4 digits → kommunenivå, not county/national)
    all_regions: list[str] = region_var.get("values", [])
    kommune_regions = [r for r in all_regions if len(r) == 4 and r.isdigit()]

    # 80+ age codes (3-digit zero-padded, ≥ 080)
    all_ages: list[str] = age_var.get("values", [])
    age_80plus = [a for a in all_ages if a.isdigit() and int(a) >= 80]

    # Both sex codes available
    sex_codes: list[str] = sex_var.get("values", []) if sex_var else []

    query: dict = {
        "query": [
            {
                "code": "Region",
                "selection": {"filter": "item", "values": kommune_regions},
            },
            {
                "code": age_var["code"],
                "selection": {"filter": "item", "values": age_80plus},
            },
            {
                "code": time_var["code"],
                "selection": {"filter": "item", "values": recent_years},
            },
        ],
        "response": {"format": "json-stat2"},
    }

    # Include both sexes if variable is present
    if sex_var and sex_codes:
        query["query"].append({
            "code": sex_var["code"],
            "selection": {"filter": "item", "values": sex_codes},
        })

    # Build name lookup
    region_vals = region_var.get("values", [])
    region_texts = region_var.get("valueTexts", region_vals)
    knr_name_map: dict[str, str] = dict(zip(region_vals, region_texts))

    age_vals = age_var.get("values", [])
    age_texts = age_var.get("valueTexts", age_vals)
    age_label_map: dict[str, str] = dict(zip(age_vals, age_texts))

    adapter = PxWebAdapter(base_url=base_url, cache_dir=cache_dir)
    payload = adapter.post_table(table_id, query)
    df = jsonstat2_to_df(payload, use_codes=True)

    # Rename
    rename_map: dict[str, str] = {}
    if time_var["code"] in df.columns:
        rename_map[time_var["code"]] = "aar"
    if "Region" in df.columns:
        rename_map["Region"] = "knr_raw"
    if age_var["code"] in df.columns:
        rename_map[age_var["code"]] = "alder_code"

    df = df.rename(columns=rename_map)
    df["knr_raw"] = df["knr_raw"].astype(str).str.strip().str.zfill(4)
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["knr_name"] = df["knr_raw"].map(knr_name_map).fillna("")
    df["alder"] = df["alder_code"].map(age_label_map).fillna(df["alder_code"])
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Sum both sexes per knr/age/year
    group_cols = ["knr_raw", "knr", "knr_name", "alder", "aar"]
    df = df.groupby(group_cols, as_index=False)["value"].sum()

    logger.info(
        "Population %s (80+): %d rows, %d kommuner, years %s–%s",
        table_id,
        len(df),
        df["knr"].nunique(),
        int(df["aar"].min()),
        int(df["aar"].max()),
    )
    return df


def _select_main_alternative(values: list[str]) -> str | None:
    """Pick the SSB main-projection ("hovedalternativ") code from a Framskriv
    value list. Prefers the known codes (MMMM/MMM); otherwise None."""
    for cand in PROJECTION_MAIN_ALT_CANDIDATES:
        if cand in values:
            return cand
    return None


def parse_projection_payload(
    payload: dict[str, Any],
    *,
    time_code: str,
    age_code: str,
) -> pd.DataFrame:
    """Parse a json-stat2 projection payload into a tidy national 80+ frame.

    Sums across sex (and any remaining dimensions) per (year) and returns
    columns ``knr`` (``"NATIONAL"``), ``alder`` (``"80+"``), ``aar`` (int),
    ``value`` (float). Factored out so the offline known-value test can drive it
    directly from a fixture without any network.
    """
    df = jsonstat2_to_df(payload, use_codes=True)
    rename_map: dict[str, str] = {}
    if time_code in df.columns:
        rename_map[time_code] = "aar"
    df = df.rename(columns=rename_map)
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    # Sum every remaining dimension (sex, age, alternative) per year → national 80+.
    out = df.groupby("aar", as_index=False)["value"].sum()
    out["knr"] = "NATIONAL"
    out["alder"] = f"{PROJECTION_MIN_AGE}+"
    return out[["knr", "alder", "aar", "value"]]


def fetch_population_projections(
    *,
    base_url: str,
    table_id: str,
    cache_dir: Path | None = None,
    target_year: int = PROJECTION_TARGET_YEAR,
) -> pd.DataFrame:
    """Fetch SSB's *national* 80+ population projection (main alternative).

    Queries the configured projection table (default 13599 — Framskrevet
    folkemengde etter kjønn, alder, framskrivingsalternativ), selecting:
      - ages ``>= PROJECTION_MIN_AGE`` (80+),
      - the main-alternative ("hovedalternativ") projection code (MMMM/MMM),
      - both sexes (summed),
      - years spanning the earliest available projection year through
        ``target_year``.

    Returns a tidy DataFrame with columns ``knr`` (``"NATIONAL"``), ``alder``
    (``"80+"``), ``aar`` (int), ``value`` (summed 80+ count per year). The
    analysis module derives the national growth rate from this frame
    (:func:`analyze._project_80plus`) and stores the 80+ baseline→2035 growth as
    ``ssb_projection_growth_2035``.

    On any failure (table shape unexpected, network error, no age/alternative
    dimension) returns an empty frame with the expected schema, and the analysis
    falls back to the documented default national rate.
    """
    try:
        logger.info("Fetching SSB projection table %s (national 80+ main alt.)", table_id)
        meta = _discover_ssb_table(base_url, table_id)
        variables = meta.get("variables", [])

        time_var = next(
            (v for v in variables if v.get("code") in ("Tid", "AAR", "Aar")), None
        )
        age_var = next(
            (v for v in variables if v.get("code") in ("Alder", "alder")), None
        )
        sex_var = next(
            (v for v in variables if v.get("code") in ("Kjonn", "kjonn")), None
        )
        alt_var = next(
            (v for v in variables if v.get("code") in PROJECTION_ALT_VAR_CANDIDATES),
            None,
        )
        if time_var is None or age_var is None:
            raise ValueError(
                f"projection table {table_id} lacks a time or age dimension "
                f"(found {[v.get('code') for v in variables]}) — not a usable "
                f"age-resolved projection table"
            )

        all_years = [y for y in time_var.get("values", []) if str(y).isdigit()]
        years = sorted(y for y in all_years if int(y) <= target_year)
        if str(target_year) not in years:
            raise ValueError(
                f"projection table {table_id} does not reach {target_year} "
                f"(max year {max(years) if years else 'n/a'})"
            )

        ages = [
            a for a in age_var.get("values", [])
            if str(a).isdigit() and int(a) >= PROJECTION_MIN_AGE
        ]
        if not ages:
            raise ValueError(
                f"projection table {table_id} age dimension has no {PROJECTION_MIN_AGE}+ codes"
            )

        query_items: list[dict[str, Any]] = [
            {"code": age_var["code"], "selection": {"filter": "item", "values": ages}},
            {"code": time_var["code"], "selection": {"filter": "item", "values": years}},
        ]
        if sex_var and sex_var.get("values"):
            query_items.append({
                "code": sex_var["code"],
                "selection": {"filter": "item", "values": list(sex_var["values"])},
            })
        if alt_var is not None:
            main_alt = _select_main_alternative(alt_var.get("values", []))
            if main_alt is None:
                raise ValueError(
                    f"projection table {table_id} alternative dimension "
                    f"{alt_var['code']} has no known main-alternative code "
                    f"(looked for {PROJECTION_MAIN_ALT_CANDIDATES})"
                )
            query_items.append({
                "code": alt_var["code"],
                "selection": {"filter": "item", "values": [main_alt]},
            })

        query = {"query": query_items, "response": {"format": "json-stat2"}}
        adapter = PxWebAdapter(base_url=base_url, cache_dir=cache_dir)
        payload = adapter.post_table(table_id, query, cache_key=f"proj_{table_id}")
        df = parse_projection_payload(
            payload, time_code=time_var["code"], age_code=age_var["code"]
        )

        logger.info(
            "Projection table %s: national 80+ %s rows, years %s",
            table_id,
            len(df),
            sorted(int(y) for y in df["aar"].dropna().unique()),
        )
        return df

    except Exception as exc:
        logger.warning(
            "Projection table %s failed (%s); national rate falls back to default",
            table_id, exc,
        )
        time.sleep(REQUEST_PAUSE)

    return pd.DataFrame(columns=["knr", "alder", "aar", "value"])


def fetch_fhi_nokkel(
    *,
    base_url: str,
    source: str,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Fetch a social/health indicator from FHI NOKKEL (folkehelsestatistikk).

    Tries to fetch a levekårs/eldreprofil indicator for all kommuner.

    Args:
        base_url: FHI API base URL, e.g. ``"https://statistikk-data.fhi.no/api/open/v1"``.
        source: NOKKEL data source identifier (e.g. ``"nokkel"``).
        cache_dir: Cache directory for raw responses.

    Returns:
        DataFrame with columns ``knr``, ``aar``, ``indicator``, ``value``.
        May be empty if the endpoint is unreachable.
    """
    indicator = "Andel80+"
    adapter = PxWebAdapter(base_url=base_url, cache_dir=cache_dir)

    # Discover available indicators from the NOKKEL API
    try:
        indicators_url = f"{base_url.rstrip('/')}/datakilder/{source}/indikatorer"
        logger.info("Fetching FHI NOKKEL indicator list")
        data = adapter.get_json(
            indicators_url, cache_key="fhi_indicators"
        )
    except Exception as exc:
        logger.warning("FHI NOKKEL indicator list fetch failed: %s", exc)
        return pd.DataFrame(columns=["knr", "aar", "indicator", "value"])

    # Find a relevant indicator ID
    ind_id = None
    if isinstance(data, list):
        for item in data:
            name = (
                item.get("navn", "") or item.get("name", "") or item.get("id", "")
            ).lower()
            if indicator.lower() in name or "levekår" in name or "eldre" in name:
                ind_id = item.get("id") or item.get("indicatorId")
                break
        if ind_id is None and data:
            ind_id = data[0].get("id") or data[0].get("indicatorId")

    if ind_id is None:
        logger.warning("No matching FHI NOKKEL indicator found for '%s'", indicator)
        return pd.DataFrame(columns=["knr", "aar", "indicator", "value"])

    # Fetch data for that indicator
    try:
        data_url = f"{base_url.rstrip('/')}/datakilder/{source}/data"
        payload = adapter.get_json(
            data_url,
            params={"indikatorId": ind_id, "geografi": "kommuner"},
            cache_key=f"fhi_nokkel_{ind_id}",
        )
    except Exception as exc:
        logger.warning("FHI NOKKEL data fetch failed for indicator %s: %s", ind_id, exc)
        return pd.DataFrame(columns=["knr", "aar", "indicator", "value"])

    # Parse whatever shape FHI returns
    if isinstance(payload, list):
        df = pd.DataFrame(payload)
    elif isinstance(payload, dict):
        df = pd.DataFrame([payload])
    else:
        return pd.DataFrame(columns=["knr", "aar", "indicator", "value"])

    # Normalise column names
    col_lower = {c: c.lower() for c in df.columns}
    df = df.rename(columns=col_lower)

    knr_col = next((c for c in df.columns if "kommune" in c or c in ("geo", "region")), None)
    year_col = next((c for c in df.columns if c in ("aar", "year", "tid", "periode")), None)
    val_col = next((c for c in df.columns if c in ("value", "verdi", "data")), None)

    if knr_col:
        df["knr"] = normalize_knr_series(df[knr_col].astype(str))
    else:
        df["knr"] = "UNKNOWN"

    df["aar"] = pd.to_numeric(df[year_col], errors="coerce") if year_col else pd.NA
    df["value"] = pd.to_numeric(df[val_col], errors="coerce") if val_col else pd.NA
    df["indicator"] = str(ind_id)

    logger.info("FHI NOKKEL: %d rows, indicator '%s'", len(df), ind_id)
    return df[["knr", "aar", "indicator", "value"]]


# ──────────────────────────────────────────────────────────────────────────────
# DuckDB persistence
# ──────────────────────────────────────────────────────────────────────────────

def save_to_duckdb(
    df: pd.DataFrame,
    table_name: str,
    db_path: Path = DEFAULT_DB,
    mode: str = "replace",
) -> None:
    """Persist a DataFrame to DuckDB.

    Args:
        df: DataFrame to save.
        table_name: Target table name.
        db_path: Path to the DuckDB file.
        mode: ``"replace"`` (default) or ``"append"``.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        if mode == "replace":
            con.execute(f"DROP TABLE IF EXISTS {table_name}")
        con.execute(f"CREATE TABLE IF NOT EXISTS {table_name} AS SELECT * FROM df")
        if mode == "append":
            con.execute(f"INSERT INTO {table_name} SELECT * FROM df")
        logger.info("Saved %d rows to %s.%s", len(df), db_path.name, table_name)
    finally:
        con.close()


def load_from_duckdb(
    table_name: str,
    db_path: Path = DEFAULT_DB,
    query: str | None = None,
) -> pd.DataFrame:
    """Load a table (or arbitrary query) from DuckDB.

    Args:
        table_name: Table to load (used if *query* is None).
        db_path: Path to the DuckDB file.
        query: Optional SQL override.

    Returns:
        DataFrame.
    """
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        sql = query or f"SELECT * FROM {table_name}"
        return con.execute(sql).df()
    finally:
        con.close()


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────────

_FETCHERS = {
    "kostra_pleie": lambda s, cache_dir: fetch_kostra_pleie(
        base_url=s["base_url"], table_id=s["table"],
        var_map=dict(s.get("var_map", {})), cache_dir=cache_dir),
    "befolkning": lambda s, cache_dir: fetch_population_current(
        base_url=s["base_url"], table_id=s["table"], cache_dir=cache_dir),
    "framskrivinger": lambda s, cache_dir: fetch_population_projections(
        base_url=s["base_url"], table_id=s["table"], cache_dir=cache_dir),
    "fhi_nokkel": lambda s, cache_dir: fetch_fhi_nokkel(
        base_url=s["base_url"], source=s["source"], cache_dir=cache_dir),
}


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
