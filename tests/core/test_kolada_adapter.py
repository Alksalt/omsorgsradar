"""Kolada (SE municipal KPI) adapter — offline via pre-seeded cache."""

import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.kolada import KoladaAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Paste literal printed by the capture script (Task 2 / Step 1):
STHLM_N21704_2023 = 21.88749  # Stockholm N21704 2023 (gender T)


def seeded_adapter(tmp_path: Path) -> KoladaAdapter:
    shutil.copy(FIXTURE_DIR / "kolada_municipalities_fixture.json",
                tmp_path / "kolada_municipalities.json")
    shutil.copy(FIXTURE_DIR / "kolada_n21704_fixture.json",
                tmp_path / "kolada_N21704_2023.json")
    return KoladaAdapter(base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path)


class TestMunicipalities:
    def test_kommun_type_only(self, tmp_path: Path) -> None:
        kommun = seeded_adapter(tmp_path).municipalities()
        assert len(kommun) == 5            # the two type-L entries are excluded
        assert kommun["0180"] == "Stockholm"


class TestFetch:
    SOURCE = {"adapter": "kolada", "id": "se_hemtjanst",
              "kpi": "N21704", "years": [2023]}

    def test_tidy_known_value(self, tmp_path: Path) -> None:
        df = seeded_adapter(tmp_path).fetch(self.SOURCE)
        assert list(df.columns) == ["country", "geo_code", "geo_id", "geo_name",
                                    "aar", "indicator", "gender", "value"]
        assert set(df["country"]) == {"SE"}
        assert set(df["gender"]) == {"T"}
        assert set(df["indicator"]) == {"kolada_N21704"}
        sthlm = df[df["geo_id"] == "SE-0180"]
        assert len(sthlm) == 1
        assert sthlm.iloc[0]["geo_name"] == "Stockholm"
        assert sthlm.iloc[0]["aar"] == 2023
        assert sthlm.iloc[0]["value"] == STHLM_N21704_2023

    def test_missing_year_gives_empty_tidy_df(self, tmp_path: Path) -> None:
        ad = seeded_adapter(tmp_path)
        (tmp_path / "kolada_N21704_1999.json").write_text('{"values": []}')
        df = ad.fetch({"adapter": "kolada", "id": "x", "kpi": "N21704", "years": [1999]})
        assert df.empty and "geo_id" in df.columns


class TestRegistry:
    def test_kolada_registered_with_required_fields(self, tmp_path: Path) -> None:
        from omsorgsradar.core.adapters import (
            REQUIRED_SOURCE_FIELDS, make_adapter, validate_source,
        )
        from omsorgsradar.core.config import ConfigError

        assert REQUIRED_SOURCE_FIELDS["kolada"] == ("kpi", "years")
        with pytest.raises(ConfigError, match="missing required"):
            validate_source({"id": "x", "adapter": "kolada"})
        ad = make_adapter({"id": "x", "adapter": "kolada",
                           "kpi": "N21704", "years": [2023]}, cache_dir=tmp_path)
        assert ad.source_id == "kolada"

    def test_kolada_provenance_resolves(self) -> None:
        from omsorgsradar.realness import resolve_provenance
        prov = resolve_provenance({"id": "x", "adapter": "kolada"})
        assert prov is not None and "Kolada" in prov["institution"]

    def test_scb_host_provenance_resolves(self) -> None:
        from omsorgsradar.realness import resolve_provenance
        prov = resolve_provenance({
            "id": "x", "adapter": "pxweb",
            "base_url": "https://api.scb.se/OV0104/v1/doris/sv/ssd/START/BE/BE0101/BE0101A",
        })
        assert prov is not None and "SCB" in prov["institution"]


class TestPagination:
    def test_cross_host_next_url_refused(self, tmp_path, monkeypatch) -> None:
        """A next_url pointing at a foreign host is never followed."""

        class FakeResp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return {"values": [], "next_url": "https://attacker.example/x"}

        monkeypatch.setattr(
            "omsorgsradar.core.adapters.kolada.requests.get",
            lambda url, headers=None, timeout=None: FakeResp(),
        )
        ad = KoladaAdapter(cache_dir=None)
        with pytest.raises(RuntimeError, match="cross-host"):
            ad.municipalities()


@pytest.mark.live
class TestLive:
    def test_live_n21704_has_many_kommuner(self) -> None:
        df = KoladaAdapter().fetch({"adapter": "kolada", "id": "live",
                                    "kpi": "N21704", "years": [2023]})
        assert df["geo_id"].nunique() > 250   # 290 Swedish kommuner
