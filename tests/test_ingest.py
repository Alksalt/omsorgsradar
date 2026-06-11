"""Tests for the ingest module — offline, using fixture JSON."""

import json
from pathlib import Path

import pandas as pd
import pytest

from omsorgsradar.ingest import jsonstat2_to_df

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
