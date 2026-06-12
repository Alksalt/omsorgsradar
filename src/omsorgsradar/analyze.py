"""Analysis module — compute press-index per kommune.

All numeric findings are written to structured JSON before any narration step.
The LLM layer only reads this JSON; it never performs calculations.

Pipeline:
1. Build elder-share projections 2025–2035 per kommune
   (extrapolating from current population age structure using national
   growth-rate adjustment because municipality-level SSB projections are
   not available via the public PxWebAPI).
2. Compute current coverage rate: ``brukere_per_1000_80plus``
   (KOSTRA BrukerHjem / population 80+) for latest available year.
3. Compute pressure index:
     ``press_index = projected_80plus_2035 / current_80plus  *
                     (1 / (coverage_rate + epsilon))``
   Normalised to [0, 1] across all kommuner.
4. Produce top-20 ranking (highest press-index).

All intermediate series are preserved in the returned :class:`AnalysisResult`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FINDINGS_PATH = Path(__file__).parent.parent.parent / "data" / "findings.json"

# Small epsilon to guard against division by zero in coverage rate
_EPSILON = 1e-6

# ── CAGR-guard code defaults (overridable via analysis.toml [params]) ─────────
# A per-kommune CAGR computed from a short or noisy window, then extrapolated
# ~9 years, explodes. These defaults are the last-resort fallback when the
# pipeline does not pass config values; the documented source of truth is
# analyses/<name>/analysis.toml. See run_analysis().
DEFAULT_MIN_GROWTH_WINDOW_YEARS = 5
DEFAULT_KOMMUNE_RATE_MIN_PA = -0.05  # -5%/yr floor (steeper decline = noise)
DEFAULT_KOMMUNE_RATE_MAX_PA = 0.10   # +10%/yr ceiling (faster = artifact)
# National default 80+ CAGR (SSB 2024 report: ~3.5% p.a. over 2010–2024).
DEFAULT_NATIONAL_RATE_PA = 0.035


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class KommuneMetrics:
    """Per-kommune computed metrics."""

    knr: str
    navn: str = ""
    # Population
    pop_80plus_latest: float = float("nan")
    pop_80plus_projected_2035: float = float("nan")
    pop_80plus_growth_pct: float = float("nan")
    # KOSTRA
    coverage_rate: float = float("nan")  # brukere_hjem per 1000 80+
    inst_places_per_1000_80plus: float = float("nan")
    # Derived
    press_index_raw: float = float("nan")
    press_index_norm: float = float("nan")  # [0,1]
    rank: int = 0
    latest_kostra_year: int = 0
    latest_pop_year: int = 0
    # Growth source provenance: "kommune" | "national" | "default"
    growth_source: str = "default"


@dataclass
class AnalysisResult:
    """Container for all analysis outputs."""

    kommuner: list[KommuneMetrics] = field(default_factory=list)
    national_80plus_latest: float = float("nan")
    national_80plus_2035: float = float("nan")
    national_growth_rate_2035: float = float("nan")
    analysis_year_range: tuple[int, int] = (0, 0)
    notes: list[str] = field(default_factory=list)
    # Description of which growth-rate path dominated for this run
    growth_method: str = "default"


# ──────────────────────────────────────────────────────────────────────────────
# Population analysis
# ──────────────────────────────────────────────────────────────────────────────


def _extract_80plus_by_kommune(df_pop: pd.DataFrame) -> pd.DataFrame:
    """Extract population aged 80+ per kommune for the latest available year.

    Handles SSB age labels such as ``"80 år"`` through ``"99 år"`` and
    ``"100 år eller eldre"``.

    Args:
        df_pop: Output of :func:`ingest.fetch_population_current`.

    Returns:
        DataFrame with columns ``knr``, ``aar``, ``pop_80plus``.
    """
    if df_pop.empty:
        return pd.DataFrame(columns=["knr", "aar", "pop_80plus"])

    df = df_pop.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Identify age column
    age_col = "alder" if "alder" in df.columns else None
    if age_col is None:
        logger.warning("No age column found in population data")
        return pd.DataFrame(columns=["knr", "aar", "pop_80plus"])

    # Parse age from labels like "80 år", "81 år", ..., "100 år eller eldre"
    def parse_age(label: str) -> int | None:
        label = str(label).strip()
        # "0 år" through "99 år" or "100 år eller eldre"
        digits = "".join(c for c in label.split()[0] if c.isdigit())
        if digits:
            return int(digits)
        return None

    df["age_int"] = df[age_col].map(parse_age)
    df_80 = df[df["age_int"].fillna(0) >= 80].copy()

    if df_80.empty:
        logger.warning("No 80+ age rows found; checking age column values: %s",
                       df[age_col].unique()[:10])
        return pd.DataFrame(columns=["knr", "aar", "pop_80plus"])

    # For each kommune, use the latest available year
    group_cols = ["knr", "aar"]
    result = (
        df_80.groupby(group_cols)["value"]
        .sum()
        .reset_index()
        .rename(columns={"value": "pop_80plus"})
    )

    # Keep latest year per kommune
    result = result.sort_values("aar").groupby("knr").last().reset_index()
    return result


def _extract_80plus_all_years(df_pop: pd.DataFrame) -> pd.DataFrame:
    """Extract population aged 80+ per kommune for ALL available years.

    Used to compute per-kommune historical growth rates (CAGR) in
    :func:`_compute_kommune_growth_rates`.

    Args:
        df_pop: Output of :func:`ingest.fetch_population_current`.

    Returns:
        DataFrame with columns ``knr``, ``aar``, ``pop_80plus`` — one row
        per (knr, year) combination.
    """
    if df_pop.empty:
        return pd.DataFrame(columns=["knr", "aar", "pop_80plus"])

    df = df_pop.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    age_col = "alder" if "alder" in df.columns else None
    if age_col is None:
        return pd.DataFrame(columns=["knr", "aar", "pop_80plus"])

    def parse_age(label: str) -> int | None:
        label = str(label).strip()
        digits = "".join(c for c in label.split()[0] if c.isdigit())
        return int(digits) if digits else None

    df["age_int"] = df[age_col].map(parse_age)
    df_80 = df[df["age_int"].fillna(0) >= 80].copy()

    if df_80.empty:
        return pd.DataFrame(columns=["knr", "aar", "pop_80plus"])

    result = (
        df_80.groupby(["knr", "aar"])["value"]
        .sum()
        .reset_index()
        .rename(columns={"value": "pop_80plus"})
    )
    result = result[result["pop_80plus"] > 0]  # drop zero-count years (merged codes)
    return result


def _compute_kommune_growth_rates(df_pop: pd.DataFrame) -> pd.DataFrame:
    """Compute per-kommune historical 80+ CAGR from multi-year population data.

    Uses the earliest and latest year with positive 80+ count per kommune to
    compute a compound annual growth rate.  Requires at least 2 years with
    positive count; otherwise the rate is NaN (will trigger national fallback).

    Args:
        df_pop: Raw population DataFrame (output of
            :func:`ingest.fetch_population_current`) with all available years.

    Returns:
        DataFrame with columns ``knr``, ``kommune_cagr`` (as a fraction,
        e.g. 0.0134 for 1.34% p.a.) and ``window_years`` (span between the
        first and last positive-count year, used by the short-window guard in
        :func:`_project_80plus`).  One row per kommune.
    """
    df_all = _extract_80plus_all_years(df_pop)
    if df_all.empty:
        return pd.DataFrame(columns=["knr", "kommune_cagr", "window_years"])

    records: list[dict] = []
    for knr, grp in df_all.groupby("knr"):
        grp_sorted = grp.sort_values("aar")
        # Need at least 2 data points with positive population
        valid = grp_sorted[grp_sorted["pop_80plus"] > 0]
        if len(valid) < 2:
            records.append({"knr": knr, "kommune_cagr": float("nan"),
                            "window_years": 0})
            continue
        pop_start = float(valid.iloc[0]["pop_80plus"])
        pop_end = float(valid.iloc[-1]["pop_80plus"])
        years = int(valid.iloc[-1]["aar"]) - int(valid.iloc[0]["aar"])
        if pop_start <= 0 or years <= 0:
            records.append({"knr": knr, "kommune_cagr": float("nan"),
                            "window_years": years})
            continue
        cagr = (pop_end / pop_start) ** (1.0 / years) - 1.0
        records.append({"knr": knr, "kommune_cagr": cagr, "window_years": years})

    return pd.DataFrame(records)


def _project_80plus(
    df_80: pd.DataFrame,
    target_year: int = 2035,
    df_proj: pd.DataFrame | None = None,
    df_pop_all_years: pd.DataFrame | None = None,
    *,
    min_window_years: int = DEFAULT_MIN_GROWTH_WINDOW_YEARS,
    rate_min_pa: float = DEFAULT_KOMMUNE_RATE_MIN_PA,
    rate_max_pa: float = DEFAULT_KOMMUNE_RATE_MAX_PA,
) -> pd.DataFrame:
    """Project 80+ population to *target_year* per kommune.

    Growth-rate fallback chain (best available wins):
      1. **Kommune-level historical CAGR** — computed from ``df_pop_all_years``
         (the full multi-year population DataFrame).  Accepted only when the
         observation window is long enough AND the per-annum rate is plausible
         (two guards, below); otherwise we fall back to the national rate.
      2. **National-level CAGR from SSB projections** — derived from
         ``df_proj`` if supplied.
      3. **Default 3.5% p.a.** — Norwegian 80+ trend 2010–2024 (SSB 2024).

    CAGR guards (G7-fix Bug 3) — a short or noisy window extrapolated ~9 years
    explodes (a 2-year split-artifact window once put Hvaler at +252%):
      * **Short-window guard**: if the window between the first and last
        positive-count year is ``< min_window_years``, use the national rate
        and tag ``growth_source = "national_short_window"``.
      * **Outlier-clamp guard**: if the kommune CAGR is outside
        ``[rate_min_pa, rate_max_pa]`` p.a., use the national rate and tag
        ``growth_source = "national_outlier_rate"``.

    Emits a ``growth_source`` column: ``"kommune"`` | ``"national"`` |
    ``"default"`` | ``"national_short_window"`` | ``"national_outlier_rate"``
    indicating which path was used per row.

    Args:
        df_80: DataFrame from :func:`_extract_80plus_by_kommune` (one row per
            kommune, latest year only).
        target_year: Projection horizon year.
        df_proj: Optional national projection DataFrame.
        df_pop_all_years: Optional full population DataFrame with all years
            (used to compute per-kommune historical CAGR).
        min_window_years: Minimum first-to-last positive-year span to trust a
            kommune-level CAGR (below it → national fallback).
        rate_min_pa: Lower clamp on the per-annum kommune CAGR (fraction).
        rate_max_pa: Upper clamp on the per-annum kommune CAGR (fraction).

    Returns:
        *df_80* with additional columns ``pop_80plus_2035``,
        ``pop_80plus_growth_pct``, and ``growth_source``.
    """
    if df_80.empty:
        df_80 = df_80.copy()
        df_80["pop_80plus_2035"] = pd.Series(dtype=float)
        df_80["pop_80plus_growth_pct"] = pd.Series(dtype=float)
        df_80["growth_source"] = pd.Series(dtype=str)
        return df_80

    baseline_year = int(df_80["aar"].max())
    years_ahead = target_year - baseline_year

    # ── Step 1: Attempt to derive national growth rate from SSB projections ──
    national_growth_rate: float | None = None
    national_is_projection = False
    if df_proj is not None and not df_proj.empty and "value" in df_proj.columns:
        try:
            df_proj_num = df_proj.copy()
            df_proj_num["value"] = pd.to_numeric(df_proj_num["value"], errors="coerce")
            total_now = df_proj_num[df_proj_num["aar"] == baseline_year]["value"].sum()
            total_2035 = df_proj_num[df_proj_num["aar"] == target_year]["value"].sum()
            if total_now > 0 and total_2035 > 0 and years_ahead > 0:
                national_growth_rate = (total_2035 / total_now) ** (1 / years_ahead) - 1
                national_is_projection = True
                logger.info(
                    "National growth rate from projections: %.3f%% p.a.",
                    national_growth_rate * 100,
                )
        except Exception as exc:
            logger.warning("Could not derive growth rate from projections: %s", exc)

    if national_growth_rate is None:
        # Default: Norwegian 80+ cohort grew ~3.5% p.a. over 2010–2024 (SSB 2024 report)
        national_growth_rate = DEFAULT_NATIONAL_RATE_PA

    # ── Step 2: Compute per-kommune CAGR from historical data ─────────────────
    kommune_rates: pd.DataFrame = pd.DataFrame(
        columns=["knr", "kommune_cagr", "window_years"]
    )
    if df_pop_all_years is not None and not df_pop_all_years.empty:
        kommune_rates = _compute_kommune_growth_rates(df_pop_all_years)

    # ── Step 3: Build per-row growth rate with guarded fallback chain ─────────
    df_out = df_80.copy()
    if not kommune_rates.empty:
        df_out = df_out.merge(kommune_rates, on="knr", how="left")
    else:
        df_out["kommune_cagr"] = float("nan")
        df_out["window_years"] = 0

    # Label used when we fall back to the national rate for "no usable kommune
    # CAGR" reasons (missing history): "national" if a real projection drove the
    # rate, else "default" (the 3.5% constant).
    national_label = "national" if national_is_projection else "default"

    rates: list[float] = []
    sources: list[str] = []
    for _, row in df_out.iterrows():
        k_cagr = row.get("kommune_cagr", float("nan"))
        window = row.get("window_years", 0)
        window = int(window) if pd.notna(window) else 0

        if pd.isna(k_cagr):
            # No usable kommune history → national/default.
            rates.append(float(national_growth_rate))
            sources.append(national_label)
        elif window < min_window_years:
            # Short-window guard: too few years to trust the kommune CAGR.
            rates.append(float(national_growth_rate))
            sources.append("national_short_window")
        elif not (rate_min_pa <= float(k_cagr) <= rate_max_pa):
            # Outlier-clamp guard: implausible per-annum rate → national.
            rates.append(float(national_growth_rate))
            sources.append("national_outlier_rate")
        else:
            rates.append(float(k_cagr))
            sources.append("kommune")

    df_out["_rate"] = rates
    df_out["growth_source"] = sources
    df_out["pop_80plus_2035"] = df_out["pop_80plus"] * (1 + df_out["_rate"]) ** years_ahead
    df_out["pop_80plus_growth_pct"] = (
        (df_out["pop_80plus_2035"] - df_out["pop_80plus"])
        / df_out["pop_80plus"].replace(0, float("nan"))
        * 100
    )
    df_out = df_out.drop(columns=["_rate"])
    for col in ("kommune_cagr", "window_years"):
        if col in df_out.columns:
            df_out = df_out.drop(columns=[col])

    # Log distribution
    source_counts = pd.Series(sources).value_counts().to_dict()
    logger.info("Growth-rate sources: %s", source_counts)
    return df_out


# ──────────────────────────────────────────────────────────────────────────────
# KOSTRA analysis
# ──────────────────────────────────────────────────────────────────────────────


def _extract_coverage_rate(df_kostra: pd.DataFrame, df_80: pd.DataFrame) -> pd.DataFrame:
    """Compute coverage rate (brukere per 1000 pop 80+) per kommune.

    Args:
        df_kostra: KOSTRA pleie DataFrame.
        df_80: DataFrame with ``knr`` and ``pop_80plus``.

    Returns:
        DataFrame with columns ``knr``, ``coverage_rate``,
        ``inst_places_per_1000_80plus``, ``latest_year``.
    """
    if df_kostra.empty:
        return pd.DataFrame(
            columns=["knr", "coverage_rate", "inst_places_per_1000_80plus", "latest_year"]
        )

    df = df_kostra.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Identify contents code column
    contents_col = "ContentsCode" if "ContentsCode" in df.columns else None

    # Use latest year per kommune: find max year per knr, then filter
    if "knr" not in df.columns:
        return pd.DataFrame(
            columns=["knr", "coverage_rate", "inst_places_per_1000_80plus", "latest_year"]
        )

    max_year_per_knr = df.groupby("knr")["aar"].max().reset_index().rename(columns={"aar": "max_aar"})
    df_with_max = df.merge(max_year_per_knr, on="knr", how="left")
    df_latest = df_with_max[df_with_max["aar"] == df_with_max["max_aar"]].drop(columns=["max_aar"])

    latest_year_per_knr = df_latest.groupby("knr")["aar"].max().reset_index()
    latest_year_per_knr.columns = ["knr", "latest_year"]

    # Real SSB variable codes from KOSTRA 12209
    # KOShjtj80aarover0001 = andel 80+ som bruker hjemmetjenester (%)
    # KOSsykhjand80aar0000 = andel 80+ med institusjonsopphold (%)
    KOSTRA_HJEM_CODE = "KOShjtj80aarover0001"
    KOSTRA_INST_CODE = "KOSsykhjand80aar0000"

    if contents_col:
        # Try exact code match first (real SSB data)
        df_hjem = df_latest[df_latest[contents_col] == KOSTRA_HJEM_CODE].copy()
        df_inst = df_latest[df_latest[contents_col] == KOSTRA_INST_CODE].copy()
        # Fallback: substring match (test fixtures use human-readable labels)
        if df_hjem.empty:
            df_hjem = df_latest[
                df_latest[contents_col].str.contains("BrukerHjem|hjemme|Hjem|hjetj", case=False, na=False)
            ].copy()
        if df_inst.empty:
            df_inst = df_latest[
                df_latest[contents_col].str.contains("PlassInst|Inst|institusjons|sykehj", case=False, na=False)
            ].copy()
    else:
        df_hjem = df_latest.copy()
        df_inst = df_latest.copy()

    # Aggregate per kommune
    hjem_agg = (
        df_hjem.groupby("knr")["value"].mean().reset_index().rename(columns={"value": "brukere_hjem"})
    )
    inst_agg = (
        df_inst.groupby("knr")["value"].mean().reset_index().rename(columns={"value": "inst_places"})
    )

    # Join with population
    df_pop = df_80[["knr", "pop_80plus"]].copy()
    result = df_pop.merge(hjem_agg, on="knr", how="left")
    result = result.merge(inst_agg, on="knr", how="left")
    result = result.merge(latest_year_per_knr, on="knr", how="left")

    # Coverage rate: KOSTRA gives % of 80+ using home services → use directly as rate
    # (already per 100 residents; treat as "coverage %" for ranking purposes)
    # NaN means no KOSTRA reporting — do NOT replace with 0 (that would inflate press index)
    result["coverage_rate"] = pd.to_numeric(result["brukere_hjem"], errors="coerce")
    result["inst_places_per_1000_80plus"] = pd.to_numeric(result["inst_places"], errors="coerce")

    # Replace literal 0.0 coverage with NaN only if KOSTRA has no row for that kommune
    # (true zero = reported zero is legitimate; missing row = no data)
    has_kostra = set(hjem_agg["knr"].tolist())
    result.loc[~result["knr"].isin(has_kostra), "coverage_rate"] = float("nan")

    return result[["knr", "coverage_rate", "inst_places_per_1000_80plus", "latest_year"]]


# ──────────────────────────────────────────────────────────────────────────────
# Pressure index
# ──────────────────────────────────────────────────────────────────────────────


def _compute_press_index(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the raw and normalised pressure index.

    Formula::

        press_raw = (pop_80plus_2035 / pop_80plus) * (1 / (coverage_rate + ε))

    A high press index = rapid 80+ growth AND currently low service coverage.
    Kommuner with no KOSTRA coverage data (NaN) are assigned NaN press index
    and excluded from the ranking (they lack sufficient data for ranking).

    Args:
        df: DataFrame with ``pop_80plus``, ``pop_80plus_2035``,
            ``coverage_rate`` columns.

    Returns:
        *df* with ``press_index_raw`` and ``press_index_norm`` columns added.
    """
    df = df.copy()
    pop_ratio = df["pop_80plus_2035"] / df["pop_80plus"].replace(0, float("nan"))

    # Only compute press index for kommuner with valid KOSTRA data
    # NaN coverage → NaN press index (no data, not ranked)
    has_data = df["coverage_rate"].notna()
    coverage_inv = pd.Series(float("nan"), index=df.index)
    coverage_inv[has_data] = 1.0 / (df.loc[has_data, "coverage_rate"] + _EPSILON)

    df["press_index_raw"] = pop_ratio * coverage_inv

    # Normalise to [0, 1] on the non-NaN subset
    raw = df["press_index_raw"]
    valid = raw.dropna()
    df["press_index_norm"] = float("nan")
    if len(valid) > 1:
        min_v = valid.min()
        max_v = valid.max()
        if max_v > min_v:
            df.loc[raw.notna(), "press_index_norm"] = (raw[raw.notna()] - min_v) / (max_v - min_v)
        else:
            df.loc[raw.notna(), "press_index_norm"] = 0.5
    elif len(valid) == 1:
        df.loc[raw.notna(), "press_index_norm"] = 1.0

    return df


# ──────────────────────────────────────────────────────────────────────────────
# Municipality name lookup
# ──────────────────────────────────────────────────────────────────────────────


def _build_name_lookup(df_kostra: pd.DataFrame) -> dict[str, str]:
    """Build a knr → municipality name dict from KOSTRA region labels.

    Handles both:
    - ``knr_name`` column (new ingest format, SSB valueTexts)
    - ``region_label`` column (old format: "0301 Oslo")
    """
    # Prefer the dedicated knr_name column (new ingest format)
    if "knr_name" in df_kostra.columns and "knr" in df_kostra.columns:
        lookup = (
            df_kostra[["knr", "knr_name"]]
            .drop_duplicates()
            .set_index("knr")["knr_name"]
            .to_dict()
        )
        # Filter out empty/missing names
        return {k: v for k, v in lookup.items() if v and str(v).strip()}

    # Fallback: parse from old "0301 Oslo" format
    label_col = "region_label" if "region_label" in df_kostra.columns else None
    if label_col is None or "knr" not in df_kostra.columns:
        return {}

    lookup: dict[str, str] = {}
    for _, row in df_kostra[[label_col, "knr"]].drop_duplicates().iterrows():
        label = str(row[label_col])
        knr = str(row["knr"])
        parts = label.split(" ", 1)
        if len(parts) == 2:
            lookup[knr] = parts[1].strip()
    return lookup


# ──────────────────────────────────────────────────────────────────────────────
# Main analysis orchestrator
# ──────────────────────────────────────────────────────────────────────────────


def _living_knr_set(df_pop: pd.DataFrame) -> tuple[set[str], int]:
    """Return (set of knr alive in the latest population year, that year).

    A kommune is *alive* if it has a positive summed 80+ count in the latest
    available population year. SSB emits a row for every historical code in
    every year — with value 0 in years the code was not active — so a dead code
    (e.g. the pre-2024 Hvaler code 3011) appears in the latest year with a zero
    sum and must be excluded from ranking. Mirrors the independent DuckDB check
    in :func:`verify.recompute_living_ranked_knrs`.
    """
    df = _extract_80plus_all_years(df_pop)
    if df.empty:
        return set(), 0
    latest = int(df["aar"].max())
    alive = df[(df["aar"] == latest) & (df["pop_80plus"] > 0)]["knr"]
    return set(alive.astype(str)), latest


def run_analysis(
    df_kostra: pd.DataFrame,
    df_pop: pd.DataFrame,
    df_proj: pd.DataFrame | None = None,
    target_year: int = 2035,
    params: dict[str, Any] | None = None,
) -> AnalysisResult:
    """Run the full analysis pipeline and return structured findings.

    Args:
        df_kostra: KOSTRA pleie DataFrame.
        df_pop: Population by age DataFrame.
        df_proj: Optional national projection DataFrame.
        target_year: Projection horizon year (overridden by
            ``params['projection_year']`` when present).
        params: Optional ``[params]`` block from analysis.toml. Recognised keys:
            ``projection_year``, ``min_growth_window_years``,
            ``kommune_rate_min_pa``, ``kommune_rate_max_pa``. Missing keys fall
            back to the module ``DEFAULT_*`` constants.

    Returns:
        :class:`AnalysisResult` with all metrics per kommune. Only kommuner
        alive in the latest population year (positive 80+) are ranked; dead
        historical codes are retained with ``rank = 0``.
    """
    params = dict(params or {})
    target_year = int(params.get("projection_year", target_year))
    min_window_years = int(
        params.get("min_growth_window_years", DEFAULT_MIN_GROWTH_WINDOW_YEARS)
    )
    rate_min_pa = float(params.get("kommune_rate_min_pa", DEFAULT_KOMMUNE_RATE_MIN_PA))
    rate_max_pa = float(params.get("kommune_rate_max_pa", DEFAULT_KOMMUNE_RATE_MAX_PA))

    result = AnalysisResult()
    notes: list[str] = []

    # Step 0: Which kommuner are alive in the latest population year? Only these
    # may be ranked (Bug-2 fix); dead historical codes are kept but unranked.
    living, living_year = _living_knr_set(df_pop)

    # Step 1: Extract 80+ population
    df_80 = _extract_80plus_by_kommune(df_pop)
    if df_80.empty:
        notes.append("WARNING: Could not extract 80+ population; check age column format")
        result.notes = notes
        return result

    logger.info("80+ population extracted for %d kommuner", len(df_80))
    result.analysis_year_range = (int(df_80["aar"].min()), int(df_80["aar"].max()))

    # Step 2: Project 80+ to target year — using per-kommune historical CAGR
    # where available, guarded against short-window / outlier explosions.
    df_80 = _project_80plus(
        df_80,
        target_year=target_year,
        df_proj=df_proj,
        df_pop_all_years=df_pop if not df_pop.empty else None,
        min_window_years=min_window_years,
        rate_min_pa=rate_min_pa,
        rate_max_pa=rate_max_pa,
    )

    # Derive growth_method summary
    if "growth_source" in df_80.columns:
        source_counts = df_80["growth_source"].value_counts().to_dict()
        total = len(df_80)
        parts = [f"{src} for {cnt} of {total}" for src, cnt in sorted(source_counts.items())]
        result.growth_method = "; ".join(parts)
    else:
        result.growth_method = "default"

    # National aggregates
    result.national_80plus_latest = float(df_80["pop_80plus"].sum())
    result.national_80plus_2035 = float(df_80["pop_80plus_2035"].sum())
    if result.national_80plus_latest > 0:
        result.national_growth_rate_2035 = (
            result.national_80plus_2035 / result.national_80plus_latest - 1
        ) * 100

    # Step 3: Coverage rates from KOSTRA
    df_coverage = _extract_coverage_rate(df_kostra, df_80)

    # Step 4: Join everything
    df_merged = df_80.merge(df_coverage, on="knr", how="left")

    # Step 5: Pressure index
    df_merged = _compute_press_index(df_merged)

    # Step 6: Rank — only kommuner alive in the latest population year (Bug-2).
    # Dead historical codes (no positive 80+ in the latest year) are retained in
    # the output for provenance but assigned rank 0 and sorted to the bottom, so
    # they never appear in any "topp N" ranking and never crash the growth sort.
    # If we have no living set (e.g. minimal fixtures without an all-years
    # frame), fall back to ranking everything (legacy behaviour).
    if living:
        df_merged["_is_living"] = df_merged["knr"].astype(str).isin(living)
    else:
        df_merged["_is_living"] = True

    df_merged = df_merged.sort_values(
        ["_is_living", "press_index_norm"],
        ascending=[False, False],
        na_position="last",
    ).reset_index(drop=True)

    n_living = int(df_merged["_is_living"].sum())
    ranks: list[int] = []
    next_rank = 1
    for is_living in df_merged["_is_living"]:
        if is_living:
            ranks.append(next_rank)
            next_rank += 1
        else:
            ranks.append(0)  # unranked: dead/defunct code
    df_merged["rank"] = ranks

    n_dead = len(df_merged) - n_living
    if n_dead:
        notes.append(
            f"{n_dead} defunct/dead kommune code(s) excluded from ranking "
            f"(no positive 80+ population in {living_year}); {n_living} ranked."
        )

    # Step 7: Municipality names
    name_lookup = _build_name_lookup(df_kostra)

    # Step 8: Build KommuneMetrics list
    kommuner: list[KommuneMetrics] = []
    for _, row in df_merged.iterrows():
        knr = str(row["knr"])
        km = KommuneMetrics(
            knr=knr,
            navn=name_lookup.get(knr, ""),
            pop_80plus_latest=float(row.get("pop_80plus", float("nan"))),
            pop_80plus_projected_2035=float(row.get("pop_80plus_2035", float("nan"))),
            pop_80plus_growth_pct=float(row.get("pop_80plus_growth_pct", float("nan"))),
            coverage_rate=float(row.get("coverage_rate", float("nan"))),
            inst_places_per_1000_80plus=float(row.get("inst_places_per_1000_80plus", float("nan"))),
            press_index_raw=float(row.get("press_index_raw", float("nan"))),
            press_index_norm=float(row.get("press_index_norm", float("nan"))),
            rank=int(row.get("rank", 0)),
            latest_kostra_year=int(row.get("latest_year", 0)) if pd.notna(row.get("latest_year")) else 0,
            latest_pop_year=int(row.get("aar", 0)) if pd.notna(row.get("aar")) else 0,
            growth_source=str(row.get("growth_source", "default")),
        )
        kommuner.append(km)

    result.kommuner = kommuner
    result.notes = notes

    logger.info(
        "Analysis complete: %d of %d kommuner ranked (living); national 80+ "
        "growth to 2035: %.1f%%; growth_method: %s",
        n_living,
        len(kommuner),
        result.national_growth_rate_2035,
        result.growth_method,
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation
# ──────────────────────────────────────────────────────────────────────────────


def _safe_float(v: float) -> float | None:
    """Convert NaN/Inf to None for JSON serialisation."""
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return v


def result_to_dict(result: AnalysisResult) -> dict[str, Any]:
    """Convert :class:`AnalysisResult` to a JSON-serialisable dict.

    Args:
        result: Analysis result.

    Returns:
        Dict with all metrics, NaN/Inf replaced with ``null``.
    """
    d = asdict(result)

    def _sanitize(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(i) for i in obj]
        if isinstance(obj, float):
            return _safe_float(obj)
        return obj

    return _sanitize(d)


def save_findings(
    result: AnalysisResult,
    path: Path = FINDINGS_PATH,
) -> None:
    """Write findings JSON to disk.

    Args:
        result: Analysis result.
        path: Output path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d = result_to_dict(result)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Findings saved to %s", path)


def load_findings(path: Path = FINDINGS_PATH) -> AnalysisResult:
    """Load findings JSON and reconstruct an :class:`AnalysisResult`.

    Args:
        path: Path to the findings JSON file.

    Returns:
        :class:`AnalysisResult` instance.

    Raises:
        FileNotFoundError: if the file does not exist.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    # Tolerate schema drift: drop keys that are no longer dataclass fields
    # (e.g. the removed pop_total_latest) so older findings.json still loads.
    valid_fields = {f.name for f in dataclasses.fields(KommuneMetrics)}
    kommuner = [
        KommuneMetrics(**{k: v for k, v in km.items() if k in valid_fields})
        for km in raw.get("kommuner", [])
    ]
    return AnalysisResult(
        kommuner=kommuner,
        national_80plus_latest=raw.get("national_80plus_latest") or float("nan"),
        national_80plus_2035=raw.get("national_80plus_2035") or float("nan"),
        national_growth_rate_2035=raw.get("national_growth_rate_2035") or float("nan"),
        analysis_year_range=tuple(raw.get("analysis_year_range", (0, 0))),
        notes=raw.get("notes", []),
    )
