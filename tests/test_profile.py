"""Tests for the profile module."""

import json
from pathlib import Path

import pandas as pd
import pytest

from omsorgsradar.profile import (
    _missing_rate,
    _outlier_iqr,
    _coverage_by_year,
    profile_kostra,
    profile_population,
    profile_all,
    quality_report_summary_md,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_kostra_processed() -> pd.DataFrame:
    """Load a minimal processed KOSTRA DataFrame for profiling tests."""
    from omsorgsradar.ingest import jsonstat2_to_df
    from omsorgsradar.kommune_mergers import normalize_knr_series

    payload = json.loads(
        (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
    )
    df = jsonstat2_to_df(payload)
    df = df.rename(columns={"Region": "region_label", "Tid": "aar"})
    df["knr_raw"] = df["region_label"].str.extract(r"^(\d{4})", expand=False).str.zfill(4)
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    return df


class TestMissingRate:
    def test_no_missing(self) -> None:
        s = pd.Series([1, 2, 3])
        assert _missing_rate(s) == 0.0

    def test_all_missing(self) -> None:
        s = pd.Series([None, None])
        assert _missing_rate(s) == 1.0

    def test_half_missing(self) -> None:
        s = pd.Series([1.0, None])
        assert abs(_missing_rate(s) - 0.5) < 1e-9


class TestOutlierIqr:
    def test_no_outliers(self) -> None:
        s = pd.Series([10.0, 11.0, 12.0, 10.5, 11.5])
        result = _outlier_iqr(s, k=3.0)
        assert result["n_outliers"] == 0

    def test_obvious_outlier_detected(self) -> None:
        s = pd.Series([10.0, 11.0, 12.0, 10.5, 1000.0])
        result = _outlier_iqr(s, k=3.0)
        assert result["n_outliers"] == 1

    def test_empty_series(self) -> None:
        result = _outlier_iqr(pd.Series([], dtype=float))
        assert result["n_outliers"] == 0


class TestCoverageByYear:
    def test_full_coverage(self) -> None:
        df = pd.DataFrame({"aar": [2022, 2023], "value": [1.0, 2.0]})
        result = _coverage_by_year(df)
        assert result == {"2022": 1.0, "2023": 1.0}

    def test_partial_coverage(self) -> None:
        df = pd.DataFrame({"aar": [2022, 2022], "value": [1.0, None]})
        result = _coverage_by_year(df)
        assert abs(result["2022"] - 0.5) < 1e-9


class TestProfileKostra:
    def test_returns_dict(self) -> None:
        df = _load_kostra_processed()
        result = profile_kostra(df)
        assert isinstance(result, dict)

    def test_has_required_keys(self) -> None:
        df = _load_kostra_processed()
        result = profile_kostra(df)
        assert "n_rows" in result
        assert "n_kommuner" in result
        assert "missing_rates" in result

    def test_row_count_correct(self) -> None:
        df = _load_kostra_processed()
        result = profile_kostra(df)
        assert result["n_rows"] == len(df)

    def test_merger_adjusted_rows_reported(self) -> None:
        df = _load_kostra_processed()
        result = profile_kostra(df)
        # Some rows may have been adjusted (or 0 if all current)
        assert "merger_adjusted_rows" in result
        assert result["merger_adjusted_rows"] >= 0


class TestProfileAll:
    def test_returns_nested_dict(self) -> None:
        df = _load_kostra_processed()
        result = profile_all({"kostra_pleie": df})
        assert "datasets" in result
        assert "kostra_pleie" in result["datasets"]

    def test_empty_datasets(self) -> None:
        result = profile_all({})
        assert result == {"datasets": {}}


class TestQualityReportSummaryMd:
    def test_returns_string(self) -> None:
        df = _load_kostra_processed()
        report = profile_all({"kostra_pleie": df})
        md = quality_report_summary_md(report)
        assert isinstance(md, str)
        assert "kostra_pleie" in md
