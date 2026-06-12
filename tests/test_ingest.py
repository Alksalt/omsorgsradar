"""Tests for the ingest module — offline, using fixture JSON."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from omsorgsradar.ingest import _FETCHERS, jsonstat2_to_df, run_ingest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestJsonStat2ToDf:
    """Tests for the JSON-stat2 parser."""

    def test_kostra_fixture_parses(self) -> None:
        """The SSB 12209 fixture is parsed without error."""
        payload = json.loads(
            (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_kostra_fixture_column_count(self) -> None:
        """Parsed DataFrame has one column per dimension plus value."""
        payload = json.loads(
            (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        # dimensions: Region, ContentsCode, Tid + value = 4 columns
        assert "value" in df.columns
        assert len(df.columns) == 4

    def test_kostra_fixture_row_count(self) -> None:
        """Row count equals product of dimension sizes."""
        payload = json.loads(
            (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
        )
        # 3 regions × 2 contents × 3 years = 18
        df = jsonstat2_to_df(payload)
        assert len(df) == 18

    def test_kostra_fixture_values(self) -> None:
        """First few values match the fixture."""
        payload = json.loads(
            (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        values = df["value"].tolist()
        assert values[0] == 5000
        assert values[1] == 5100

    def test_population_fixture_parses(self) -> None:
        """The population fixture is parsed without error."""
        payload = json.loads(
            (FIXTURE_DIR / "pop_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_population_fixture_has_age_column(self) -> None:
        """Population fixture contains an Alder column."""
        payload = json.loads(
            (FIXTURE_DIR / "pop_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        assert "Alder" in df.columns

    def test_population_fixture_row_count(self) -> None:
        """Population row count: 3 regions × 1 sex × 4 ages × 2 years = 24."""
        payload = json.loads(
            (FIXTURE_DIR / "pop_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        assert len(df) == 24

    def test_missing_value_key_raises(self) -> None:
        """A payload without 'value' key raises KeyError."""
        bad_payload = {"id": ["A"], "size": [2], "dimension": {}}
        with pytest.raises(KeyError):
            jsonstat2_to_df(bad_payload)


class TestPopulationProjections:
    """Finding 3: the projection fetch must produce a real national 80+ ×
    main-alternative frame (SSB table 13599), driving the SSB-projection growth
    cited in the report. Offline against committed fixtures — no network."""

    def _meta(self) -> dict:
        return json.loads(
            (FIXTURE_DIR / "ssb_13599_meta_fixture.json").read_text(encoding="utf-8")
        )

    def _payload(self) -> dict:
        return json.loads(
            (FIXTURE_DIR / "ssb_13599_proj_fixture.json").read_text(encoding="utf-8")
        )

    def test_fetch_returns_national_80plus_per_year(self) -> None:
        """fetch_population_projections returns a NATIONAL 80+ frame with the
        known SSB main-alternative totals (2025/2026/2035)."""
        from omsorgsradar.ingest import fetch_population_projections

        with patch("omsorgsradar.ingest._discover_ssb_table", return_value=self._meta()), \
             patch(
                 "omsorgsradar.ingest.PxWebAdapter.post_table",
                 return_value=self._payload(),
             ):
            df = fetch_population_projections(
                base_url="https://data.ssb.no/api/v0/no/table", table_id="13599"
            )
        assert set(df["knr"].unique()) == {"NATIONAL"}
        by_year = df.groupby("aar")["value"].sum()
        # Known values fetched live 2026-06-12 (table 13599, MMM, 80+):
        assert by_year.loc[2025] == 272848
        assert by_year.loc[2026] == 288360
        assert by_year.loc[2035] == 422314

    def test_ssb_projection_growth_known_value(self) -> None:
        """_ssb_projection_growth gives the known ~46% (2026→2035) — materially
        above the ~31% trend method, supporting the report's comparative claim."""
        from omsorgsradar.analyze import _ssb_projection_growth
        from omsorgsradar.ingest import fetch_population_projections

        with patch("omsorgsradar.ingest._discover_ssb_table", return_value=self._meta()), \
             patch(
                 "omsorgsradar.ingest.PxWebAdapter.post_table",
                 return_value=self._payload(),
             ):
            df = fetch_population_projections(
                base_url="https://data.ssb.no/api/v0/no/table", table_id="13599"
            )
        growth, base = _ssb_projection_growth(df, baseline_year=2026, target_year=2035)
        assert base == 2026
        assert 46.0 <= growth <= 47.0, f"expected ~46.45%, got {growth:.2f}%"

    def test_growth_empty_frame_is_nan(self) -> None:
        from omsorgsradar.analyze import _ssb_projection_growth
        import numpy as np

        growth, base = _ssb_projection_growth(pd.DataFrame(), 2026, 2035)
        assert np.isnan(growth) and base == 0

    def test_fetch_table_without_age_returns_empty(self) -> None:
        """A table lacking an age dimension (e.g. the old 12880 macro table)
        yields an empty frame, not a bogus row — the analysis then falls back to
        the default national rate."""
        from omsorgsradar.ingest import fetch_population_projections

        macro_meta = {
            "title": "12880: Makroøkonomiske hovedstørrelser",
            "variables": [
                {"code": "ContentsCode", "values": ["KonsumHushold"], "valueTexts": ["x"]},
                {"code": "Tid", "values": ["2027", "2028", "2029"],
                 "valueTexts": ["2027", "2028", "2029"]},
            ],
        }
        with patch("omsorgsradar.ingest._discover_ssb_table", return_value=macro_meta):
            df = fetch_population_projections(
                base_url="https://data.ssb.no/api/v0/no/table", table_id="12880"
            )
        assert df.empty
        assert list(df.columns) == ["knr", "alder", "aar", "value"]


class TestRunIngestOffline:
    """Offline tests for run_ingest orchestration and _FETCHERS dispatch."""

    def test_unknown_source_id_raises(self, tmp_path: Path) -> None:
        sources = [{"id": "nonexistent_source", "base_url": "http://x", "table": "0"}]
        with pytest.raises(ValueError, match="unknown adapter"):
            run_ingest(sources, db_path=tmp_path / "test.duckdb")

    def test_fetchers_dispatch_by_id(self, tmp_path: Path) -> None:
        import pandas as pd

        sentinel = pd.DataFrame({"knr": ["0301"], "aar": [2024], "value": [1.0]})

        for sid in ("kostra_pleie", "befolkning", "framskrivinger", "fhi_nokkel"):
            with patch.dict(
                "omsorgsradar.ingest._FETCHERS",
                {sid: lambda s, cache_dir, _sid=sid: sentinel},
            ):
                result = run_ingest([{"id": sid}], db_path=tmp_path / f"{sid}.duckdb")
                assert sid in result
                assert not result[sid].empty

    def test_kostra_lambda_requires_base_url_and_table(self) -> None:
        fetcher = _FETCHERS["kostra_pleie"]
        with pytest.raises(KeyError):
            fetcher({"base_url": "http://x"}, None)  # missing "table"

    def test_fhi_nokkel_lambda_requires_source_key(self) -> None:
        fetcher = _FETCHERS["fhi_nokkel"]
        with pytest.raises(KeyError):
            fetcher({"base_url": "http://x"}, None)  # missing "source"


class TestCanonicalSourcesMatchFetchers:
    """Every [[sources]] block in the canonical analysis.toml must carry the
    keys its _FETCHERS lambda accesses — catches config/dispatch drift offline."""

    REQUIRED_KEYS = {
        "kostra_pleie": {"base_url", "table", "var_map"},
        "befolkning": {"base_url", "table"},
        "framskrivinger": {"base_url", "table"},
        "fhi_nokkel": {"base_url", "source"},
    }

    def test_canonical_sources_have_required_keys(self) -> None:
        from omsorgsradar.core.config import load_run_config

        repo_root = Path(__file__).resolve().parents[1]
        cfg = load_run_config(
            repo_root / "analyses" / "omsorgsradar", repo_root / "workflow.toml"
        )
        for src in cfg.sources:
            sid = src["id"]
            assert sid in _FETCHERS, f"source id '{sid}' has no fetcher"
            missing = self.REQUIRED_KEYS[sid] - set(src)
            assert not missing, f"source '{sid}' missing keys: {missing}"
