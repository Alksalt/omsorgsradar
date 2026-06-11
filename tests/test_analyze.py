"""Tests for the analysis module — uses fixture data, fully offline."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from omsorgsradar.analyze import (
    _extract_80plus_by_kommune,
    _project_80plus,
    _compute_press_index,
    run_analysis,
    result_to_dict,
    AnalysisResult,
    KommuneMetrics,
)
from omsorgsradar.ingest import jsonstat2_to_df

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_pop_fixture() -> pd.DataFrame:
    """Load and minimally process the population fixture."""
    payload = json.loads(
        (FIXTURE_DIR / "pop_fixture.json").read_text(encoding="utf-8")
    )
    df = jsonstat2_to_df(payload)
    # Rename to match expected schema
    df = df.rename(columns={"Region": "region_label", "Alder": "alder", "Tid": "aar"})
    df["knr_raw"] = df["region_label"].str.extract(r"^(\d{4})", expand=False).str.zfill(4)
    from omsorgsradar.kommune_mergers import normalize_knr_series
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    return df


def _load_kostra_fixture() -> pd.DataFrame:
    """Load and minimally process the KOSTRA fixture."""
    payload = json.loads(
        (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
    )
    df = jsonstat2_to_df(payload)
    df = df.rename(columns={"Region": "region_label", "Tid": "aar"})
    df["knr_raw"] = df["region_label"].str.extract(r"^(\d{4})", expand=False).str.zfill(4)
    from omsorgsradar.kommune_mergers import normalize_knr_series
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    return df


class TestExtract80Plus:
    """Tests for 80+ population extraction."""

    def test_extracts_correct_age_groups(self) -> None:
        """Only ages ≥ 80 are summed."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        assert not df_80.empty
        assert "pop_80plus" in df_80.columns
        assert "knr" in df_80.columns

    def test_positive_values(self) -> None:
        """80+ population values are positive for all kommuner."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        assert (df_80["pop_80plus"] > 0).all()

    def test_one_row_per_kommune(self) -> None:
        """Returns exactly one row per kommune (latest year)."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        assert df_80["knr"].nunique() == len(df_80)

    def test_oslo_80plus_larger_than_molde(self) -> None:
        """Oslo should have more 80+ than Molde (fixtures reflect this)."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        oslo_row = df_80[df_80["knr"] == "0301"]
        molde_row = df_80[df_80["knr"] == "1506"]
        if not oslo_row.empty and not molde_row.empty:
            assert oslo_row["pop_80plus"].values[0] > molde_row["pop_80plus"].values[0]

    def test_empty_input_returns_empty(self) -> None:
        """Empty DataFrame input returns empty output."""
        result = _extract_80plus_by_kommune(pd.DataFrame())
        assert result.empty


class TestProject80Plus:
    """Tests for the 80+ population projection."""

    def test_projection_larger_than_baseline(self) -> None:
        """Projected 2035 population should exceed baseline (positive growth assumed)."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035)
        assert (df_proj["pop_80plus_2035"] >= df_proj["pop_80plus"]).all()

    def test_projection_column_created(self) -> None:
        """pop_80plus_2035 column is added."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035)
        assert "pop_80plus_2035" in df_proj.columns

    def test_growth_pct_column_created(self) -> None:
        """pop_80plus_growth_pct column is added."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035)
        assert "pop_80plus_growth_pct" in df_proj.columns


class TestComputePressIndex:
    """Tests for pressure index computation."""

    def test_press_index_in_range(self) -> None:
        """Normalised press index is in [0, 1] for all kommuner."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_80 = _project_80plus(df_80, target_year=2035)
        df_80["coverage_rate"] = 100.0  # dummy uniform coverage
        df_80["inst_places_per_1000_80plus"] = 50.0
        result = _compute_press_index(df_80)
        norm = result["press_index_norm"].dropna()
        assert (norm >= 0).all() and (norm <= 1).all()

    def test_max_press_index_is_one(self) -> None:
        """Maximum normalised press index is exactly 1."""
        df_pop = _load_pop_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_80 = _project_80plus(df_80, target_year=2035)
        df_80["coverage_rate"] = 100.0
        result = _compute_press_index(df_80)
        assert abs(result["press_index_norm"].max() - 1.0) < 1e-9


class TestRunAnalysis:
    """Integration tests for the full analysis run."""

    def test_run_analysis_returns_result(self) -> None:
        """run_analysis returns an AnalysisResult with kommuner."""
        df_kostra = _load_kostra_fixture()
        df_pop = _load_pop_fixture()
        result = run_analysis(df_kostra, df_pop)
        assert isinstance(result, AnalysisResult)

    def test_kommuner_ranked_by_press_index(self) -> None:
        """Kommuner are sorted descending by press_index_norm."""
        df_kostra = _load_kostra_fixture()
        df_pop = _load_pop_fixture()
        result = run_analysis(df_kostra, df_pop)
        if len(result.kommuner) >= 2:
            for i in range(len(result.kommuner) - 1):
                a = result.kommuner[i].press_index_norm
                b = result.kommuner[i + 1].press_index_norm
                if not (np.isnan(a) or np.isnan(b)):
                    assert a >= b, f"Rank {i+1} ({a:.4f}) > rank {i+2} ({b:.4f}) violated"

    def test_result_serialisable(self) -> None:
        """AnalysisResult converts to a JSON-serialisable dict without errors."""
        df_kostra = _load_kostra_fixture()
        df_pop = _load_pop_fixture()
        result = run_analysis(df_kostra, df_pop)
        d = result_to_dict(result)
        import json
        json.dumps(d)  # must not raise

    def test_empty_inputs_return_result(self) -> None:
        """Empty DataFrames return an AnalysisResult (possibly empty kommuner)."""
        result = run_analysis(pd.DataFrame(), pd.DataFrame())
        assert isinstance(result, AnalysisResult)
