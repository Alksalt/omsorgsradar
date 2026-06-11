"""Ingest module — queries SSB PxWebAPI v2 and FHI NOKKEL, normalises
kommune IDs, and persists to DuckDB.

Design notes
------------
- All HTTP calls go through :func:`_post_px` / :func:`_get_json`.  A
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

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import requests

from .kommune_mergers import normalize_knr_series

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

SSB_BASE = "https://data.ssb.no/api/v0/no/table"
FHI_BASE = "https://statistikk-data.fhi.no/api/open/v1"

DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "omsorgsradar.duckdb"
DEFAULT_CACHE = Path(__file__).parent.parent.parent / "data" / "cache"

# Variables we need from KOSTRA table 12209
# (pleie og omsorg — kommuner)
KOSTRA_PLEIE_VARS = [
    "Bruker0_Stat",    # brukere totalt
    "BrukerHjem",      # hjemmebaserte tjenester — brukere
    "BrukerInst",      # institusjonsplasser — brukere
    "PlassInst",       # institusjonsplasser totalt
    "Driftsutg",       # driftsutgifter pleie og omsorg (1000 kr)
]

# Real SSB variable codes in KOSTRA 12209 (discovered from API metadata)
# Maps our logical name → SSB variable code
KOSTRA_VAR_MAP = {
    "hjemmetjeneste_andel": "KOShjtj80aarover0001",   # andel innbyggere 80+ med hjemmetjenester
    "institusjon_andel": "KOSsykhjand80aar0000",       # andel 80+ med institusjonsopphold
    "aarsverk_per_bruker": "KOSaarsvbrukerom0000",      # årsverk per bruker
    "utgifter_per_innbygger": "KOSbduFKG9innbyg0000",  # utgifter per innbygger
}

# All SSB variable codes we want from 12209
KOSTRA_WANTED_CODES = list(KOSTRA_VAR_MAP.values())

REQUEST_TIMEOUT = 60  # seconds
REQUEST_PAUSE = 0.5   # pause between SSB requests (be polite)


# ──────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────────────────────────────────────

def _post_px(
    table_id: str,
    query: dict[str, Any],
    cache_dir: Path | None = None,
    cache_key: str | None = None,
) -> dict[str, Any]:
    """POST a PxWebAPI v2 query and return the parsed JSON response.

    Args:
        table_id: SSB table identifier, e.g. ``"12209"``.
        query: PxWebAPI v2 query dict.
        cache_dir: If supplied, save/load raw JSON here.
        cache_key: File stem for the cache file (defaults to table_id).

    Returns:
        Parsed JSON dict (JSON-stat2 or PxAPI2 format).

    Raises:
        requests.HTTPError: on non-2xx response.
    """
    key = cache_key or table_id
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{key}.json"
        if cache_file.exists():
            logger.debug("Cache hit: %s", cache_file)
            return json.loads(cache_file.read_text(encoding="utf-8"))

    url = f"{SSB_BASE}/{table_id}"
    logger.info("POST %s", url)
    resp = requests.post(url, json=query, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if cache_dir is not None:
        cache_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return data


def _get_json(
    url: str,
    params: dict[str, Any] | None = None,
    cache_dir: Path | None = None,
    cache_key: str | None = None,
) -> Any:
    """GET JSON from an arbitrary URL with optional caching."""
    if cache_dir is not None and cache_key is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            logger.debug("Cache hit: %s", cache_file)
            return json.loads(cache_file.read_text(encoding="utf-8"))

    logger.info("GET %s", url)
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    if cache_dir is not None and cache_key is not None:
        cache_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return data


# ──────────────────────────────────────────────────────────────────────────────
# JSON-stat2 → DataFrame
# ──────────────────────────────────────────────────────────────────────────────

def jsonstat2_to_df(
    payload: dict[str, Any],
    use_codes: bool = False,
) -> pd.DataFrame:
    """Convert a JSON-stat2 response (SSB PxWebAPI v2 format) to a DataFrame.

    Handles nested ``dimension`` objects and a flat ``value`` list.

    Args:
        payload: Parsed JSON-stat2 dict.
        use_codes: If True, use the raw category codes (e.g. "3101") as cell
            values instead of human-readable labels (e.g. "Halden").
            Default is False (use labels) for backwards compatibility with
            the test fixtures.

    Returns:
        Tidy DataFrame with one column per dimension plus a ``value`` column.

    Raises:
        KeyError: if the payload is missing required JSON-stat2 keys.
    """
    dims = payload["dimension"]
    dim_ids: list[str] = payload["id"]
    dim_sizes: list[int] = payload["size"]
    values: list[float | None] = payload["value"]

    # Build index arrays (cartesian product of dimension categories)
    import itertools

    category_lists = []
    for dim_id, size in zip(dim_ids, dim_sizes):
        cats = dims[dim_id]["category"]
        label_map = cats.get("label", {})
        index_map = cats.get("index", {})
        # Reorder by index position
        if isinstance(index_map, dict):
            ordered = sorted(index_map.items(), key=lambda x: x[1])
            ordered_ids = [k for k, _ in ordered]
        else:
            ordered_ids = list(index_map)
        if use_codes:
            # Keep the raw codes (e.g. "3101", "KOShjtj80aarover0001", "2022")
            category_lists.append(ordered_ids)
        else:
            # Use human-readable labels (e.g. "Halden", "Andel...", "2022")
            labels = [label_map.get(k, k) for k in ordered_ids]
            category_lists.append(labels)

    rows = list(itertools.product(*category_lists))
    df = pd.DataFrame(rows, columns=dim_ids)
    df["value"] = values
    return df


# ──────────────────────────────────────────────────────────────────────────────
# SSB fetchers
# ──────────────────────────────────────────────────────────────────────────────

def _discover_ssb_table(table_id: str) -> dict[str, Any]:
    """Fetch the metadata for an SSB table to discover available variables."""
    url = f"{SSB_BASE}/{table_id}"
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_kostra_pleie(
    cache_dir: Path | None = DEFAULT_CACHE,
) -> pd.DataFrame:
    """Fetch KOSTRA table 12209 — pleie og omsorg, alle kommuner, alle år.

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
    logger.info("Discovering KOSTRA table 12209 metadata")
    meta = _discover_ssb_table("12209")

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
            f"Unexpected table structure for 12209. "
            f"Variables: {[v.get('code') for v in variables]}"
        )

    region_code = region_var["code"]  # e.g. "KOKkommuneregion0000"
    contents_values: list[str] = contents_var.get("values", [])
    all_years: list[str] = time_var.get("values", [])

    # Pick the relevant KOSTRA variables (use discovered codes)
    wanted_contents = [c for c in contents_values if c in KOSTRA_WANTED_CODES]
    if not wanted_contents:
        logger.warning(
            "KOSTRA_WANTED_CODES not found; available: %s. Using first 6.",
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

    payload = _post_px("12209", query, cache_dir=cache_dir)
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
        "KOSTRA 12209: %d rows, %d kommuner, years %s–%s",
        len(df),
        df["knr"].nunique(),
        int(df["aar"].min()),
        int(df["aar"].max()),
    )
    return df


def fetch_population_current(
    cache_dir: Path | None = DEFAULT_CACHE,
) -> pd.DataFrame:
    """Fetch current population by age (1-year classes) from SSB table 07459.

    Fetches only ages 80+ (codes 080–104) for all kommuner, both sexes summed,
    for the most recent 10 years.

    Returns a tidy DataFrame with columns:
        - ``knr_raw``: original kommune number
        - ``knr``: normalised post-2020 kommune number
        - ``alder``: age label (e.g. "80 år")
        - ``aar``: year (int)
        - ``value``: population count
    """
    logger.info("Fetching SSB table 07459 — folkemengde etter alder (80+)")
    meta = _discover_ssb_table("07459")
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
            f"Expected variables not found in 07459. Found: {[v.get('code') for v in variables]}"
        )

    all_years: list[str] = time_var.get("values", [])
    # Use most recent 10 years
    recent_years = all_years[-10:] if len(all_years) > 10 else all_years

    # Find all 4-char komunne codes (exactly 4 digits → kommunenivå, not county/national)
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

    payload = _post_px("07459", query, cache_dir=cache_dir)
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
        "Population 07459 (80+): %d rows, %d kommuner, years %s–%s",
        len(df),
        df["knr"].nunique(),
        int(df["aar"].min()),
        int(df["aar"].max()),
    )
    return df


def fetch_population_projections(
    cache_dir: Path | None = DEFAULT_CACHE,
) -> pd.DataFrame:
    """Fetch SSB population projections (medium scenario) at the national level.

    SSB's kommune-level projections are published in separate tables (e.g.
    13873, 12880).  We try 13873 first, then 12880, then fall back to a
    national-aggregate projection.

    Returns a tidy DataFrame with columns:
        - ``knr``: kommune number (``"NATIONAL"`` if only aggregate available)
        - ``alder``: age group label
        - ``aar``: year (int)
        - ``value``: projected population

    Note: Projections are only available in 5-year intervals or as national
    aggregates in the public PxWebAPI.  For municipality-level projections
    we use the national growth-rate adjustment method in the analysis module.
    """
    for table_id in ("13873", "12880"):
        try:
            logger.info("Trying SSB projection table %s", table_id)
            meta = _discover_ssb_table(table_id)
            variables = meta.get("variables", [])
            time_var = next(
                (v for v in variables if v.get("code") in ("Tid", "AAR", "Aar")),
                None,
            )
            if time_var is None:
                continue

            all_years = time_var.get("values", [])
            projection_years = [y for y in all_years if int(y) >= 2024][:12]
            if not projection_years:
                continue

            query = {
                "query": [
                    {
                        "code": time_var["code"],
                        "selection": {"filter": "item", "values": projection_years},
                    },
                ],
                "response": {"format": "json-stat2"},
            }

            payload = _post_px(
                table_id, query, cache_dir=cache_dir, cache_key=f"proj_{table_id}"
            )
            df = jsonstat2_to_df(payload)

            rename_map: dict[str, str] = {}
            if time_var["code"] in df.columns:
                rename_map[time_var["code"]] = "aar"
            df = df.rename(columns=rename_map)
            df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
            df["knr"] = "NATIONAL"

            logger.info(
                "Projection table %s: %d rows, years %s",
                table_id,
                len(df),
                sorted(df["aar"].unique()),
            )
            return df

        except Exception as exc:
            logger.warning("Table %s failed: %s", table_id, exc)
            time.sleep(REQUEST_PAUSE)
            continue

    # If all projection tables fail, return empty dataframe with expected schema
    logger.warning("All projection table attempts failed; returning empty projection df")
    return pd.DataFrame(columns=["knr", "aar", "value"])


def fetch_fhi_nokkel(
    indicator: str = "Andel80+",
    cache_dir: Path | None = DEFAULT_CACHE,
) -> pd.DataFrame:
    """Fetch a social/health indicator from FHI NOKKEL (folkehelsestatistikk).

    Tries to fetch a levekårs/eldreprofil indicator for all kommuner.

    Args:
        indicator: NOKKEL indicator code or keyword.
        cache_dir: Cache directory for raw responses.

    Returns:
        DataFrame with columns ``knr``, ``aar``, ``indicator``, ``value``.
        May be empty if the endpoint is unreachable.
    """
    # Discover available indicators from the NOKKEL API
    try:
        indicators_url = f"{FHI_BASE}/datakilder/nokkel/indikatorer"
        logger.info("Fetching FHI NOKKEL indicator list")
        data = _get_json(
            indicators_url, cache_dir=cache_dir, cache_key="fhi_indicators"
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
        data_url = f"{FHI_BASE}/datakilder/nokkel/data"
        payload = _get_json(
            data_url,
            params={"indikatorId": ind_id, "geografi": "kommuner"},
            cache_dir=cache_dir,
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

def run_ingest(
    db_path: Path = DEFAULT_DB,
    cache_dir: Path | None = DEFAULT_CACHE,
) -> dict[str, pd.DataFrame]:
    """Run the full ingest pipeline and save all tables to DuckDB.

    Args:
        db_path: Target DuckDB file.
        cache_dir: Cache directory for raw API responses.

    Returns:
        Dict mapping table name → DataFrame for all fetched datasets.
    """
    results: dict[str, pd.DataFrame] = {}

    logger.info("=== Ingest: KOSTRA 12209 ===")
    df_kostra = fetch_kostra_pleie(cache_dir=cache_dir)
    save_to_duckdb(df_kostra, "kostra_pleie", db_path=db_path)
    results["kostra_pleie"] = df_kostra
    time.sleep(REQUEST_PAUSE)

    logger.info("=== Ingest: Population 07459 ===")
    df_pop = fetch_population_current(cache_dir=cache_dir)
    save_to_duckdb(df_pop, "befolkning", db_path=db_path)
    results["befolkning"] = df_pop
    time.sleep(REQUEST_PAUSE)

    logger.info("=== Ingest: Population projections ===")
    df_proj = fetch_population_projections(cache_dir=cache_dir)
    if not df_proj.empty:
        save_to_duckdb(df_proj, "framskrivinger", db_path=db_path)
    results["framskrivinger"] = df_proj
    time.sleep(REQUEST_PAUSE)

    logger.info("=== Ingest: FHI NOKKEL ===")
    df_fhi = fetch_fhi_nokkel(cache_dir=cache_dir)
    if not df_fhi.empty:
        save_to_duckdb(df_fhi, "fhi_nokkel", db_path=db_path)
    results["fhi_nokkel"] = df_fhi

    logger.info("=== Ingest complete ===")
    return results
