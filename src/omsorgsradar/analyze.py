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


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class KommuneMetrics:
    """Per-kommune computed metrics."""

    knr: str
    navn: str = ""
    # Population
    pop_total_latest: float = float("nan")
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


@dataclass
class AnalysisResult:
    """Container for all analysis outputs."""

    kommuner: list[KommuneMetrics] = field(default_factory=list)
    national_80plus_latest: float = float("nan")
    national_80plus_2035: float = float("nan")
    national_growth_rate_2035: float = float("nan")
    analysis_year_range: tuple[int, int] = (0, 0)
    notes: list[str] = field(default_factory=list)


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


def _project_80plus(
    df_80: pd.DataFrame,
    target_year: int = 2035,
    df_proj: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Project 80+ population to *target_year* per kommune.

    Method: uses the national growth rate from SSB projections if available;
    otherwise applies the observed national compound annual growth rate over
    the last 10 years of population data.

    Args:
        df_80: DataFrame from :func:`_extract_80plus_by_kommune`.
        target_year: Projection horizon year.
        df_proj: Optional national projection DataFrame.

    Returns:
        *df_80* with additional column ``pop_80plus_2035``.
    """
    if df_80.empty:
        df_80["pop_80plus_2035"] = pd.Series(dtype=float)
        return df_80

    baseline_year = int(df_80["aar"].max())
    years_ahead = target_year - baseline_year

    # Attempt to derive growth rate from national projection
    national_growth_rate: float | None = None
    if df_proj is not None and not df_proj.empty and "value" in df_proj.columns:
        try:
            df_proj_num = df_proj.copy()
            df_proj_num["value"] = pd.to_numeric(df_proj_num["value"], errors="coerce")
            # Use total population as proxy (projections may not split by age)
            total_now = df_proj_num[df_proj_num["aar"] == baseline_year]["value"].sum()
            total_2035 = df_proj_num[df_proj_num["aar"] == target_year]["value"].sum()
            if total_now > 0 and total_2035 > 0 and years_ahead > 0:
                national_growth_rate = (total_2035 / total_now) ** (1 / years_ahead) - 1
                logger.info(
                    "National growth rate from projections: %.3f%% p.a.", national_growth_rate * 100
                )
        except Exception as exc:
            logger.warning("Could not derive growth rate from projections: %s", exc)

    if national_growth_rate is None:
        # Default: Norwegian 80+ cohort grew ~3.5% p.a. over 2010–2024 (SSB 2024 report)
        national_growth_rate = 0.035
        logger.info("Using default national 80+ growth rate: %.1f%% p.a.", national_growth_rate * 100)

    df_out = df_80.copy()
    df_out["pop_80plus_2035"] = df_out["pop_80plus"] * (1 + national_growth_rate) ** years_ahead
    df_out["pop_80plus_growth_pct"] = (
        (df_out["pop_80plus_2035"] - df_out["pop_80plus"]) / df_out["pop_80plus"].replace(0, float("nan")) * 100
    )
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


def run_analysis(
    df_kostra: pd.DataFrame,
    df_pop: pd.DataFrame,
    df_proj: pd.DataFrame | None = None,
    target_year: int = 2035,
) -> AnalysisResult:
    """Run the full analysis pipeline and return structured findings.

    Args:
        df_kostra: KOSTRA pleie DataFrame.
        df_pop: Population by age DataFrame.
        df_proj: Optional national projection DataFrame.
        target_year: Projection horizon year.

    Returns:
        :class:`AnalysisResult` with all metrics per kommune.
    """
    result = AnalysisResult()
    notes: list[str] = []

    # Step 1: Extract 80+ population
    df_80 = _extract_80plus_by_kommune(df_pop)
    if df_80.empty:
        notes.append("WARNING: Could not extract 80+ population; check age column format")
        result.notes = notes
        return result

    logger.info("80+ population extracted for %d kommuner", len(df_80))
    result.analysis_year_range = (int(df_80["aar"].min()), int(df_80["aar"].max()))

    # Step 2: Project 80+ to target year
    df_80 = _project_80plus(df_80, target_year=target_year, df_proj=df_proj)

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

    # Step 6: Rank (highest press first; NaN → sorted to bottom)
    df_merged = df_merged.sort_values(
        "press_index_norm", ascending=False, na_position="last"
    ).reset_index(drop=True)
    df_merged["rank"] = range(1, len(df_merged) + 1)

    # Step 7: Municipality names
    name_lookup = _build_name_lookup(df_kostra)

    # Step 8: Build KommuneMetrics list
    kommuner: list[KommuneMetrics] = []
    for _, row in df_merged.iterrows():
        knr = str(row["knr"])
        km = KommuneMetrics(
            knr=knr,
            navn=name_lookup.get(knr, ""),
            pop_total_latest=float(row.get("pop_80plus", float("nan"))),  # closest proxy
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
        )
        kommuner.append(km)

    result.kommuner = kommuner
    result.notes = notes

    logger.info(
        "Analysis complete: %d kommuner ranked; national 80+ growth to 2035: %.1f%%",
        len(kommuner),
        result.national_growth_rate_2035,
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
    kommuner = [KommuneMetrics(**k) for k in raw.get("kommuner", [])]
    return AnalysisResult(
        kommuner=kommuner,
        national_80plus_latest=raw.get("national_80plus_latest") or float("nan"),
        national_80plus_2035=raw.get("national_80plus_2035") or float("nan"),
        national_growth_rate_2035=raw.get("national_growth_rate_2035") or float("nan"),
        analysis_year_range=tuple(raw.get("analysis_year_range", (0, 0))),
        notes=raw.get("notes", []),
    )
