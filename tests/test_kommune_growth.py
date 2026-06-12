"""Tests for per-kommune 80+ growth rates — TDD for G7-A.

All tests are OFFLINE; no network calls.

Fixture: tests/fixtures/ssb_07459_kommune_hist_fixture.json
  - 3 municipalities: 0301 Oslo, 1103 Stavanger, 1804 Bodø
  - 2 years: 2017, 2024 (7 years apart)
  - Both sexes, all 80+ age classes
  - Known 80+ totals:
      0301 Oslo:     2017=20949, 2024=22988  CAGR ~1.34%
      1103 Stavanger: 2017=4523,  2024=5408   CAGR ~2.59%
      1804 Bodø:      2017=1791,  2024=2424   CAGR ~4.42%
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from omsorgsradar.analyze import (
    _extract_80plus_by_kommune,
    _project_80plus,
    run_analysis,
    AnalysisResult,
    KommuneMetrics,
)
from omsorgsradar.ingest import jsonstat2_to_df
from omsorgsradar.kommune_mergers import normalize_knr_series
from omsorgsradar.verify import Claim, Verifier

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Known values from the fixture
OSLO_KNR = "0301"
STAVANGER_KNR = "1103"
BODO_KNR = "1804"


def _load_hist_fixture() -> pd.DataFrame:
    """Load the multi-year historical population fixture as a tidy DataFrame."""
    payload = json.loads(
        (FIXTURE_DIR / "ssb_07459_kommune_hist_fixture.json").read_text(encoding="utf-8")
    )
    df = jsonstat2_to_df(payload, use_codes=True)
    # Map columns to expected schema
    df = df.rename(columns={"Region": "knr_raw", "Tid": "aar", "Alder": "alder_code"})
    # Build age labels (passthrough — _extract_80plus_by_kommune parses age_int from alder)
    df["alder"] = df["alder_code"]  # numeric codes like "080"
    df["knr_raw"] = df["knr_raw"].astype(str).str.strip().str.zfill(4)
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    # Sum both sexes per knr/alder/aar
    df = df.groupby(["knr_raw", "knr", "alder", "aar"], as_index=False)["value"].sum()
    return df


def _build_df_80_fixture() -> pd.DataFrame:
    """Build the earliest/latest 80+ totals per kommune from fixture."""
    df_pop = _load_hist_fixture()
    df_80 = _extract_80plus_by_kommune(df_pop)
    return df_80


# ──────────────────────────────────────────────────────────────────────────────
# A2 — Fixture known-value ingest tests
# ──────────────────────────────────────────────────────────────────────────────

class TestKommuneHistFixture:
    """Known-value assertions against the historical population fixture."""

    def test_fixture_loads_without_error(self) -> None:
        df = _load_hist_fixture()
        assert isinstance(df, pd.DataFrame)
        assert not df.empty

    def test_fixture_has_three_municipalities(self) -> None:
        df = _load_hist_fixture()
        assert df["knr"].nunique() == 3

    def test_fixture_has_two_years(self) -> None:
        df = _load_hist_fixture()
        years = sorted(df["aar"].unique())
        assert 2017 in years
        assert 2024 in years

    def test_oslo_2017_80plus_total(self) -> None:
        """Oslo 80+ total for 2017 matches known value 20949."""
        df = _load_hist_fixture()
        oslo_2017 = df[(df["knr"] == OSLO_KNR) & (df["aar"] == 2017)]["value"].sum()
        assert abs(oslo_2017 - 20949) < 5, f"Expected ~20949, got {oslo_2017}"

    def test_oslo_2024_80plus_total(self) -> None:
        """Oslo 80+ total for 2024 matches known value 22988."""
        df = _load_hist_fixture()
        oslo_2024 = df[(df["knr"] == OSLO_KNR) & (df["aar"] == 2024)]["value"].sum()
        assert abs(oslo_2024 - 22988) < 5, f"Expected ~22988, got {oslo_2024}"

    def test_bodo_2024_larger_than_2017(self) -> None:
        """Bodø 80+ grows from 2017 to 2024 (known: 1791 -> 2424)."""
        df = _load_hist_fixture()
        p2017 = df[(df["knr"] == BODO_KNR) & (df["aar"] == 2017)]["value"].sum()
        p2024 = df[(df["knr"] == BODO_KNR) & (df["aar"] == 2024)]["value"].sum()
        assert p2024 > p2017

    def test_stavanger_2024_value(self) -> None:
        """Stavanger 80+ total for 2024 matches known value 5408."""
        df = _load_hist_fixture()
        stav_2024 = df[(df["knr"] == STAVANGER_KNR) & (df["aar"] == 2024)]["value"].sum()
        assert abs(stav_2024 - 5408) < 5, f"Expected ~5408, got {stav_2024}"


# ──────────────────────────────────────────────────────────────────────────────
# A3 — Per-kommune growth in analyze.py
# ──────────────────────────────────────────────────────────────────────────────

class TestPerKommuneGrowth:
    """Per-kommune growth rates differ; fallback chain works."""

    def test_growth_source_column_present(self) -> None:
        """_project_80plus adds a growth_source column."""
        df_pop = _load_hist_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035, df_pop_all_years=df_pop)
        assert "growth_source" in df_proj.columns, (
            "_project_80plus must emit 'growth_source' column"
        )

    def test_distinct_growth_pct_across_kommuner(self) -> None:
        """3 kommuner with distinct observed CAGRs produce distinct growth_pct values."""
        df_pop = _load_hist_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035, df_pop_all_years=df_pop)
        # All 3 have data from 2017 and 2024 → should get kommune-level rates
        growth_vals = df_proj["pop_80plus_growth_pct"].dropna().tolist()
        assert len(growth_vals) >= 2, "Need at least 2 growth values to test distinctness"
        # At least two distinct values (Oslo ~15.7%, Stavanger ~32.4%, Bodø ~60.9% to 2035)
        unique_vals = set(round(v, 4) for v in growth_vals)
        assert len(unique_vals) >= 2, (
            f"All kommuner have identical growth_pct={growth_vals[0]:.4f}; "
            "expected distinct rates per kommune"
        )

    def test_oslo_has_lower_growth_than_bodo(self) -> None:
        """Oslo (slow grower) has lower projected growth_pct than Bodø (fast grower)."""
        df_pop = _load_hist_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035, df_pop_all_years=df_pop)
        oslo = df_proj[df_proj["knr"] == OSLO_KNR]["pop_80plus_growth_pct"].values
        bodo = df_proj[df_proj["knr"] == BODO_KNR]["pop_80plus_growth_pct"].values
        assert len(oslo) > 0 and len(bodo) > 0
        assert oslo[0] < bodo[0], (
            f"Expected Oslo ({oslo[0]:.1f}%) < Bodø ({bodo[0]:.1f}%)"
        )

    def test_fallback_to_national_rate_for_missing_kommune(self) -> None:
        """A kommune absent from population history falls back to national rate."""
        df_pop = _load_hist_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)

        # Add an extra kommune row with ONLY one year → cannot compute CAGR → fallback
        extra_row = pd.DataFrame({
            "knr": ["9999"],
            "aar": [2024],
            "pop_80plus": [500.0],
        })
        df_80_with_extra = pd.concat([df_80, extra_row], ignore_index=True)

        # df_pop only has 3 municipalities, 9999 has no history → fallback
        df_proj = _project_80plus(df_80_with_extra, target_year=2035, df_pop_all_years=df_pop)
        extra = df_proj[df_proj["knr"] == "9999"]
        assert len(extra) == 1
        # growth_source should be "national" or "default" (not "kommune")
        assert extra["growth_source"].values[0] in ("national", "default"), (
            f"Expected fallback source for missing kommune, got: {extra['growth_source'].values[0]}"
        )

    def test_growth_source_is_kommune_for_fixture_municipalities(self) -> None:
        """Municipalities with 2+ years of data have growth_source='kommune'."""
        df_pop = _load_hist_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035, df_pop_all_years=df_pop)
        for knr in [OSLO_KNR, STAVANGER_KNR, BODO_KNR]:
            row = df_proj[df_proj["knr"] == knr]
            if not row.empty:
                src = row["growth_source"].values[0]
                assert src == "kommune", (
                    f"Expected growth_source='kommune' for {knr}, got '{src}'"
                )

    def test_pop_80plus_2035_positive(self) -> None:
        """All projected 2035 populations are positive."""
        df_pop = _load_hist_fixture()
        df_80 = _extract_80plus_by_kommune(df_pop)
        df_proj = _project_80plus(df_80, target_year=2035, df_pop_all_years=df_pop)
        assert (df_proj["pop_80plus_2035"] > 0).all()


# ──────────────────────────────────────────────────────────────────────────────
# A4 — Verifier catches corrupt per-kommune growth
# ──────────────────────────────────────────────────────────────────────────────

class TestVerifierPerKommuneGrowth:
    """Verifier recomputes per-kommune growth and catches planted faults."""

    def _make_result_with_growth(self) -> AnalysisResult:
        """Build a synthetic AnalysisResult with distinct growth sources."""
        kommuner = [
            KommuneMetrics(
                knr="0301",
                navn="Oslo",
                pop_80plus_latest=22988.0,
                pop_80plus_projected_2035=25000.0,
                pop_80plus_growth_pct=8.75,  # ~1.34% CAGR × 11 years
                coverage_rate=85.0,
                inst_places_per_1000_80plus=50.0,
                press_index_raw=0.2,
                press_index_norm=0.2,
                rank=2,
                latest_kostra_year=2024,
                latest_pop_year=2024,
                growth_source="kommune",
            ),
            KommuneMetrics(
                knr="1804",
                navn="Bodø",
                pop_80plus_latest=2424.0,
                pop_80plus_projected_2035=3700.0,
                pop_80plus_growth_pct=52.6,  # ~4.42% CAGR × 11 years
                coverage_rate=60.0,
                inst_places_per_1000_80plus=30.0,
                press_index_raw=1.0,
                press_index_norm=1.0,
                rank=1,
                latest_kostra_year=2024,
                latest_pop_year=2024,
                growth_source="kommune",
            ),
        ]
        return AnalysisResult(
            kommuner=kommuner,
            national_80plus_latest=25000.0,
            national_80plus_2035=30000.0,
            national_growth_rate_2035=20.0,
            analysis_year_range=(2017, 2024),
        )

    def test_correct_growth_pct_claim_passes(self) -> None:
        """A correct per-kommune growth claim passes verification."""
        result = self._make_result_with_growth()
        verifier = Verifier(result)
        claim = Claim(
            claim_type="kommune_growth_pct",
            claimed_value=52.6,
            parameters={"knr": "1804"},
        )
        cr = verifier.verify_claim(claim)
        assert cr.passes, f"Expected PASS, got: {cr.message}"

    def test_corrupted_growth_pct_fails(self) -> None:
        """A corrupt per-kommune growth claim (planted fault) fails verification."""
        result = self._make_result_with_growth()
        verifier = Verifier(result)
        # Plant fault: claim Bodø grew only 5% when it actually grew 52.6%
        corrupt_claim = Claim(
            claim_type="kommune_growth_pct",
            claimed_value=5.0,
            parameters={"knr": "1804"},
        )
        cr = verifier.verify_claim(corrupt_claim)
        assert not cr.passes, "Verifier should FAIL on planted corrupt growth_pct"

    def test_unknown_knr_in_growth_claim_fails(self) -> None:
        """A growth_pct claim for a non-existent kommune fails."""
        result = self._make_result_with_growth()
        verifier = Verifier(result)
        claim = Claim(
            claim_type="kommune_growth_pct",
            claimed_value=30.0,
            parameters={"knr": "9999"},
        )
        cr = verifier.verify_claim(claim)
        assert not cr.passes


# ──────────────────────────────────────────────────────────────────────────────
# A3 continuation — AnalysisResult.growth_method field
# ──────────────────────────────────────────────────────────────────────────────

class TestGrowthMethodField:
    """AnalysisResult carries growth_method describing what path dominated."""

    def test_run_analysis_has_growth_method(self) -> None:
        """run_analysis result has a growth_method attribute."""
        # Build minimal fixtures
        df_pop = _load_hist_fixture()
        # No KOSTRA data — run_analysis with empty KOSTRA
        result = run_analysis(pd.DataFrame(), df_pop)
        assert hasattr(result, "growth_method"), (
            "AnalysisResult must have 'growth_method' attribute"
        )

    def test_growth_method_is_string(self) -> None:
        """growth_method is a non-empty string."""
        df_pop = _load_hist_fixture()
        result = run_analysis(pd.DataFrame(), df_pop)
        assert isinstance(result.growth_method, str)
        assert len(result.growth_method) > 0
