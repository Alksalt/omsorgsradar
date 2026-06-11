"""Profile module — data quality audit as a first-class pipeline step.

Produces a structured JSON quality report covering:
- Missing rates per column
- Outlier detection (IQR method)
- Year-over-year coverage continuity
- Definition change flags (KOSTRA variable availability shifts)
- Kommune merger impact summary

The quality report JSON is written to ``data/quality_profile.json`` and a
summary section is embedded in the README.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

QUALITY_REPORT_PATH = Path(__file__).parent.parent.parent / "data" / "quality_profile.json"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _missing_rate(series: pd.Series) -> float:
    """Return fraction of null values in *series*."""
    return float(series.isna().mean())


def _outlier_iqr(series: pd.Series, k: float = 3.0) -> dict[str, Any]:
    """Detect outliers using the IQR method with fence multiplier *k*.

    Returns dict with ``n_outliers``, ``lower_fence``, ``upper_fence``.
    """
    clean = series.dropna()
    if clean.empty:
        return {"n_outliers": 0, "lower_fence": None, "upper_fence": None}
    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1
    lower = q1 - k * iqr
    upper = q3 + k * iqr
    n_out = int(((clean < lower) | (clean > upper)).sum())
    return {"n_outliers": n_out, "lower_fence": round(lower, 2), "upper_fence": round(upper, 2)}


def _coverage_by_year(df: pd.DataFrame, year_col: str = "aar", val_col: str = "value") -> dict[str, float]:
    """Return fraction of non-null values per year."""
    if year_col not in df.columns or val_col not in df.columns:
        return {}
    grp = df.groupby(year_col)[val_col].apply(lambda s: float(s.notna().mean()))
    return {str(int(k)): round(v, 3) for k, v in grp.items()}


# ──────────────────────────────────────────────────────────────────────────────
# Main profiler
# ──────────────────────────────────────────────────────────────────────────────


def profile_kostra(df: pd.DataFrame) -> dict[str, Any]:
    """Profile the KOSTRA pleie DataFrame.

    Args:
        df: Output of :func:`ingest.fetch_kostra_pleie`.

    Returns:
        Dict with quality metrics.
    """
    report: dict[str, Any] = {
        "source": "SSB KOSTRA table 12209",
        "n_rows": len(df),
        "n_kommuner": int(df["knr"].nunique()) if "knr" in df.columns else None,
        "year_range": None,
        "missing_rates": {},
        "outliers": {},
        "coverage_by_year": {},
        "contents_codes_found": [],
        "merger_adjusted_rows": None,
    }

    if "aar" in df.columns:
        years = df["aar"].dropna()
        if not years.empty:
            report["year_range"] = [int(years.min()), int(years.max())]

    for col in df.columns:
        report["missing_rates"][col] = round(_missing_rate(df[col]), 4)

    if "value" in df.columns:
        report["outliers"]["value"] = _outlier_iqr(pd.to_numeric(df["value"], errors="coerce"))
        report["coverage_by_year"] = _coverage_by_year(df)

    if "ContentsCode" in df.columns:
        report["contents_codes_found"] = sorted(df["ContentsCode"].dropna().unique().tolist())

    if "knr_raw" in df.columns and "knr" in df.columns:
        n_merged = int((df["knr_raw"] != df["knr"]).sum())
        report["merger_adjusted_rows"] = n_merged

    return report


def profile_population(df: pd.DataFrame) -> dict[str, Any]:
    """Profile the population DataFrame.

    Args:
        df: Output of :func:`ingest.fetch_population_current`.

    Returns:
        Dict with quality metrics.
    """
    report: dict[str, Any] = {
        "source": "SSB table 07459 — folkemengde etter alder",
        "n_rows": len(df),
        "n_kommuner": int(df["knr"].nunique()) if "knr" in df.columns else None,
        "year_range": None,
        "missing_rates": {},
        "age_groups_found": None,
    }

    if "aar" in df.columns:
        years = df["aar"].dropna()
        if not years.empty:
            report["year_range"] = [int(years.min()), int(years.max())]

    for col in df.columns:
        report["missing_rates"][col] = round(_missing_rate(df[col]), 4)

    if "alder" in df.columns:
        report["age_groups_found"] = int(df["alder"].nunique())

    return report


def profile_all(
    datasets: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Run profiling on all datasets and return combined quality report.

    Args:
        datasets: Dict mapping table name → DataFrame (from :func:`ingest.run_ingest`).

    Returns:
        Combined quality report dict.
    """
    report: dict[str, Any] = {"datasets": {}}

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

    return report


def save_quality_report(
    report: dict[str, Any],
    path: Path = QUALITY_REPORT_PATH,
) -> None:
    """Write quality report to JSON.

    Args:
        report: Report dict from :func:`profile_all`.
        path: Output path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Quality report saved to %s", path)


def load_quality_report(path: Path = QUALITY_REPORT_PATH) -> dict[str, Any]:
    """Load and return the quality report JSON.

    Args:
        path: Path to the JSON file.

    Returns:
        Report dict.

    Raises:
        FileNotFoundError: if the report does not exist yet.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def quality_report_summary_md(report: dict[str, Any]) -> str:
    """Render a short markdown summary of the quality report for the README.

    Args:
        report: Report dict from :func:`profile_all` or :func:`load_quality_report`.

    Returns:
        Markdown string.
    """
    lines = ["## Data quality profile\n"]
    for ds_name, ds_report in report.get("datasets", {}).items():
        lines.append(f"### {ds_name}")
        lines.append(f"- Source: {ds_report.get('source', 'N/A')}")
        lines.append(f"- Rows: {ds_report.get('n_rows', 'N/A'):,}")
        if "n_kommuner" in ds_report:
            lines.append(f"- Municipalities: {ds_report['n_kommuner']}")
        if "year_range" in ds_report and ds_report["year_range"]:
            yr = ds_report["year_range"]
            lines.append(f"- Year range: {yr[0]}–{yr[1]}")
        if "merger_adjusted_rows" in ds_report:
            lines.append(f"- Merger-adjusted rows: {ds_report['merger_adjusted_rows']}")
        if "missing_rates" in ds_report:
            high_missing = {
                k: v
                for k, v in ds_report["missing_rates"].items()
                if v > 0.05
            }
            if high_missing:
                items = ", ".join(f"`{k}`: {v:.1%}" for k, v in high_missing.items())
                lines.append(f"- High missing rate (>5%): {items}")
        lines.append("")
    return "\n".join(lines)
