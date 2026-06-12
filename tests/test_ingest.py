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
