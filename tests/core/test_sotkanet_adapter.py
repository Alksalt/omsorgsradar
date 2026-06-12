"""Sotkanet adapter — offline via pre-seeded cache + real trimmed fixtures."""

import json
import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.sotkanet import SotkanetAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Paste the value printed by the fixture-capture script (Task 3 / Step 2):
HELSINKI_127_2023 = 674500  # <- Helsinki indicator-127 (population) 2023


def seeded_adapter(tmp_path: Path) -> SotkanetAdapter:
    """Unreachable base_url + pre-seeded cache: any HTTP attempt would fail."""
    shutil.copy(FIXTURE_DIR / "sotkanet_regions_fixture.json",
                tmp_path / "sotkanet_regions.json")
    shutil.copy(FIXTURE_DIR / "sotkanet_127_fixture.json",
                tmp_path / "sotkanet_127_2023_2023_total.json")
    return SotkanetAdapter(base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path)


class TestMunicipalities:
    def test_kunta_only(self, tmp_path: Path) -> None:
        kunta = seeded_adapter(tmp_path).municipalities()
        assert len(kunta) == 5  # MAAKUNTA fixture entries excluded
        assert ("091", "Helsinki") in kunta.values()


class TestFetch:
    def test_tidy_known_value(self, tmp_path: Path) -> None:
        source = {"adapter": "sotkanet", "id": "fi_test",
                  "indicators": [127], "years": [2023]}
        df = seeded_adapter(tmp_path).fetch(source)
        assert list(df.columns) == ["country", "geo_code", "geo_id", "geo_name",
                                    "aar", "indicator", "gender", "value"]
        assert set(df["country"]) == {"FI"}
        hki = df[df["geo_id"] == "FI-091"]
        assert len(hki) == 1
        assert hki.iloc[0]["geo_name"] == "Helsinki"
        assert hki.iloc[0]["aar"] == 2023
        assert hki.iloc[0]["value"] == HELSINKI_127_2023

    def test_empty_indicator_gives_empty_tidy_df(self, tmp_path: Path) -> None:
        ad = seeded_adapter(tmp_path)
        (tmp_path / "sotkanet_999_2023_2023_total.json").write_text("[]")
        df = ad.fetch({"adapter": "sotkanet", "id": "x",
                       "indicators": [999], "years": [2023]})
        assert df.empty and "geo_id" in df.columns


@pytest.mark.live
class TestLive:
    def test_live_fetch_has_many_kunta(self) -> None:
        ad = SotkanetAdapter()
        df = ad.fetch({"adapter": "sotkanet", "id": "live",
                       "indicators": [127], "years": [2023]})
        assert df["geo_id"].nunique() > 250  # ~290 Finnish municipalities
