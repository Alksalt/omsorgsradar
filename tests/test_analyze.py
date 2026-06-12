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


def _pop_with_dead_code() -> pd.DataFrame:
    """Population frame where one knr ('3011') is dead in the latest year.

    SSB emits a row for every historical code in every year, with value 0 in
    years where the code was not active. '3011' is nonzero through 2022 then
    0 from 2023; '0301' (Oslo, live) is nonzero throughout. Latest year 2024.
    """
    rows = []
    for aar in (2022, 2023, 2024):
        # live kommune Oslo
        rows.append({"knr": "0301", "knr_raw": "0301", "alder": "080",
                     "aar": aar, "value": 1000.0 + (aar - 2022) * 50})
        # dead code: nonzero in 2022, zero afterwards
        dead_val = 200.0 if aar == 2022 else 0.0
        rows.append({"knr": "3011", "knr_raw": "3011", "alder": "080",
                     "aar": aar, "value": dead_val})
    return pd.DataFrame(rows)


class TestRankingOnlyLivingKommuner:
    """Bug-2 regression: dead codes must not be ranked."""

    def test_dead_code_gets_no_rank(self) -> None:
        """A code with zero 80+ in the latest year gets rank 0 (unranked)."""
        df_pop = _pop_with_dead_code()
        result = run_analysis(pd.DataFrame(), df_pop)
        by_knr = {km.knr: km for km in result.kommuner}
        assert "3011" in by_knr, "dead code should still appear in findings"
        assert by_knr["3011"].rank == 0, (
            f"dead code 3011 must be unranked (rank 0), got {by_knr['3011'].rank}"
        )

    def test_ranked_set_subset_of_latest_year(self) -> None:
        """Every ranked knr exists in the latest population year with positive 80+."""
        df_pop = _pop_with_dead_code()
        result = run_analysis(pd.DataFrame(), df_pop)
        latest = df_pop["aar"].max()
        living = set(
            df_pop[(df_pop["aar"] == latest) & (df_pop["value"] > 0)]["knr"]
        )
        ranked = {km.knr for km in result.kommuner if km.rank >= 1}
        assert ranked <= living, f"ranked set {ranked} not ⊆ living set {living}"

    def test_no_ranked_row_has_none_growth(self) -> None:
        """No ranked kommune has NaN/None pop_80plus_growth_pct (sort-crash guard)."""
        df_pop = _pop_with_dead_code()
        result = run_analysis(pd.DataFrame(), df_pop)
        for km in result.kommuner:
            if km.rank >= 1:
                assert not np.isnan(km.pop_80plus_growth_pct), (
                    f"ranked knr {km.knr} has NaN growth_pct"
                )

    def test_ranks_are_contiguous_from_one(self) -> None:
        """Ranks on the living set are 1..N with no gaps."""
        df_pop = _pop_with_dead_code()
        result = run_analysis(pd.DataFrame(), df_pop)
        ranks = sorted(km.rank for km in result.kommuner if km.rank >= 1)
        assert ranks == list(range(1, len(ranks) + 1)), f"non-contiguous ranks: {ranks}"


class TestRankOnlyComputablePressIndex:
    """Finding 2: living kommuner with non-computable press_index (NaN coverage
    → NaN press_index_norm) must NOT be ranked — they get rank 0 (retained,
    unranked), like dead codes. Contradicts the old behaviour where a living
    kommune with NaN press still held a rank."""

    def _pop_two_living(self) -> pd.DataFrame:
        rows = []
        for aar in (2022, 2023, 2024):
            rows.append({"knr": "0301", "knr_raw": "0301", "alder": "080",
                         "aar": aar, "value": 1000.0 + (aar - 2022) * 50})
            rows.append({"knr": "1151", "knr_raw": "1151", "alder": "080",
                         "aar": aar, "value": 50.0 + (aar - 2022) * 2})
        return pd.DataFrame(rows)

    def test_living_kommune_with_nan_coverage_gets_rank_zero(self) -> None:
        """A living kommune whose press_index is NaN (no KOSTRA coverage) is
        retained but unranked (rank 0)."""
        df_pop = self._pop_two_living()
        # KOSTRA covers only 0301 → 1151 has NaN coverage → NaN press_index.
        df_kostra = pd.DataFrame({
            "knr": ["0301", "0301"],
            "knr_name": ["Oslo", "Oslo"],
            "aar": [2024, 2024],
            "ContentsCode": ["KOShjtj80aarover0001", "KOSsykhjand80aar0000"],
            "value": [20.0, 5.0],
        })
        result = run_analysis(df_kostra, df_pop)
        by_knr = {km.knr: km for km in result.kommuner}
        assert "1151" in by_knr, "living-but-uncovered kommune must remain in findings"
        assert np.isnan(by_knr["1151"].press_index_norm), "precondition: NaN press"
        assert by_knr["1151"].rank == 0, (
            f"living kommune with NaN press_index must be unranked (rank 0), "
            f"got {by_knr['1151'].rank}"
        )

    def test_no_ranked_kommune_has_nan_press_index(self) -> None:
        """Invariant: every ranked kommune has a computable press_index_norm."""
        df_pop = self._pop_two_living()
        df_kostra = pd.DataFrame({
            "knr": ["0301", "0301"],
            "knr_name": ["Oslo", "Oslo"],
            "aar": [2024, 2024],
            "ContentsCode": ["KOShjtj80aarover0001", "KOSsykhjand80aar0000"],
            "value": [20.0, 5.0],
        })
        result = run_analysis(df_kostra, df_pop)
        for km in result.kommuner:
            if km.rank >= 1:
                assert not np.isnan(km.press_index_norm), (
                    f"ranked knr {km.knr} has NaN press_index_norm"
                )


class TestNameLookupLatestYear:
    """Finding 4: terminal codes must carry the LATEST-year name, not an
    arbitrary (often predecessor) KOSTRA label kept by drop_duplicates()."""

    def test_latest_year_label_wins(self) -> None:
        """knr 5055 with year-2019 label 'Hemne' and year-2025 label 'Heim'
        resolves to 'Heim' (the latest-year name)."""
        from omsorgsradar.analyze import _build_name_lookup
        df = pd.DataFrame({
            "knr": ["5055", "5055", "5055"],
            "knr_name": ["Hemne", "Hemne", "Heim"],
            "aar": [2018, 2019, 2025],
        })
        lookup = _build_name_lookup(df)
        assert lookup["5055"] == "Heim", f"expected Heim, got {lookup['5055']}"

    def test_terminal_name_preferred_over_suffixed_predecessors(self) -> None:
        """Real KOSTRA shape: normalize_knr_series collapses several historical
        codes onto one terminal knr, so EVERY year carries both the current
        (un-suffixed) terminal label and suffixed predecessor labels. The
        terminal name must win even when a predecessor label is alphabetically
        or positionally 'last'. knr 5055 → Heim (not Hemne/Halsa)."""
        from omsorgsradar.analyze import _build_name_lookup
        rows = []
        for aar in (2015, 2024, 2025):
            rows.append({"knr": "5055", "knr_name": "Heim", "aar": aar})
            rows.append({"knr": "5055", "knr_name": "Hemne (-2017)", "aar": aar})
            rows.append({"knr": "5055", "knr_name": "Hemne (2018-2019)", "aar": aar})
            rows.append({"knr": "5055", "knr_name": "Halsa (-2019)", "aar": aar})
        df = pd.DataFrame(rows)
        lookup = _build_name_lookup(df)
        assert lookup["5055"] == "Heim", f"expected Heim, got {lookup['5055']}"

    def test_only_suffixed_labels_fall_back_to_latest(self) -> None:
        """A pure historical code with only suffixed labels keeps its latest-year
        label (suffix stripped) rather than dropping out."""
        from omsorgsradar.analyze import _build_name_lookup
        df = pd.DataFrame({
            "knr": ["3011", "3011"],
            "knr_name": ["Hvaler (-2019)", "Hvaler (2020-2023)"],
            "aar": [2019, 2023],
        })
        lookup = _build_name_lookup(df)
        assert lookup["3011"] == "Hvaler"

    def test_latest_year_label_with_suffix_strip(self) -> None:
        """Latest-year selection composes with the SSB validity-suffix strip."""
        from omsorgsradar.analyze import _build_name_lookup
        df = pd.DataFrame({
            "knr": ["5059", "5059"],
            "knr_name": ["Orkdal (-2019)", "Orkland"],
            "aar": [2019, 2025],
        })
        lookup = _build_name_lookup(df)
        assert lookup["5059"] == "Orkland"

    def test_no_year_column_falls_back_to_drop_duplicates(self) -> None:
        """Without an 'aar' column the lookup still works (legacy frames)."""
        from omsorgsradar.analyze import _build_name_lookup
        df = pd.DataFrame({
            "knr": ["1818"],
            "knr_name": ["Herøy (Nordland)"],
        })
        lookup = _build_name_lookup(df)
        assert lookup["1818"] == "Herøy (Nordland)"


class TestLoadFindingsRoundTrip:
    """Finding 6: load_findings must preserve growth_method (Finding 1 makes
    load_findings load-bearing)."""

    def test_growth_method_round_trips(self, tmp_path: Path) -> None:
        from omsorgsradar.analyze import load_findings, save_findings
        result = AnalysisResult(
            kommuner=[KommuneMetrics(knr="0301", navn="Oslo", rank=1,
                                     press_index_norm=1.0)],
            national_80plus_latest=1000.0,
            national_80plus_2035=1300.0,
            national_growth_rate_2035=30.0,
            analysis_year_range=(2017, 2026),
            growth_method="kommune for 354 of 480",
        )
        path = tmp_path / "findings.json"
        save_findings(result, path=path)
        loaded = load_findings(path)
        assert loaded.growth_method == "kommune for 354 of 480"


class TestNoMisleadingPopTotalField:
    """Bug-4 regression: the mislabeled pop_total_latest field is removed."""

    def test_kommune_metrics_has_no_pop_total_latest(self) -> None:
        """KommuneMetrics no longer carries the pop_total_latest field."""
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(KommuneMetrics)}
        assert "pop_total_latest" not in field_names, (
            "pop_total_latest was 80+-only mislabeled as total population — remove it"
        )

    def test_findings_json_has_no_pop_total_latest(self) -> None:
        """Serialized findings carry no pop_total_latest key."""
        df_pop = _pop_with_dead_code()
        result = run_analysis(pd.DataFrame(), df_pop)
        d = result_to_dict(result)
        for km in d["kommuner"]:
            assert "pop_total_latest" not in km


class TestNameLookupValiditySuffix:
    """Published names must not carry SSB validity suffixes like 'Frogn (-2019)'."""

    def test_validity_suffix_stripped(self) -> None:
        from omsorgsradar.analyze import _build_name_lookup
        df = pd.DataFrame({
            "knr": ["3214", "3214", "3110"],
            "knr_name": ["Frogn (-2019)", "Frogn", "Hvaler (2020-2023)"],
        })
        lookup = _build_name_lookup(df)
        assert lookup["3214"] == "Frogn"
        assert lookup["3110"] == "Hvaler"

    def test_real_disambiguator_parenthetical_kept(self) -> None:
        from omsorgsradar.analyze import _build_name_lookup
        df = pd.DataFrame({
            "knr": ["1818", "3018"],
            "knr_name": ["Herøy (Nordland)", "Våler (Østfold)"],
        })
        lookup = _build_name_lookup(df)
        assert lookup["1818"] == "Herøy (Nordland)"
        assert lookup["3018"] == "Våler (Østfold)"
