"""Socialstyrelsen statistikdatabas adapter — offline cache + pagination unit.

Actual API shape (verified live 2026-06-12; spec in task differed):
- regionId is a string ("0180"), NOT an int
- ar is a string, often a 3-year range ("1995-1997"), NOT a single year int
- Path-based /region/…, /ar/… URL segments return 404; no server-side filtering
- varde uses Swedish decimal notation ("39,3"); suppressed = "X" or ".."
- nasta_sida links use http:// and must be followed as https://
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.socialstyrelsen import SocialstyrelsenAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
AMNE = "skadorochskadehandelserisverigeskommunerochlan"

# Literals from live fixture capture (Step 1 output, 2026-06-12):
# - Data collected from known pages for 5 kommuner (0180, 0580, 1280, 1480, 2480)
# - Each kommuner appears on a single page with one 3-year rolling window
N_FIXTURE_ROWS = 657           # total real rows across 5 kommuner
STHLM_FIRST_VARDE = "39,3"    # Stockholm (0180) first row varde, year 1995-1997
STHLM_FIRST_AAR = "1995-1997"  # corresponding year string


def seeded_adapter(tmp_path: Path) -> SocialstyrelsenAdapter:
    """Create adapter with fixture files pre-seeded into tmp cache dir."""
    shutil.copy(
        FIXTURE_DIR / "sst_skador_regions_fixture.json",
        tmp_path / f"sst_{AMNE}_regions.json",
    )
    shutil.copy(
        FIXTURE_DIR / "sst_skador_data_fixture.json",
        tmp_path / f"sst_{AMNE}_m1.json",
    )
    return SocialstyrelsenAdapter(
        base_url="http://127.0.0.1:9/unreachable",
        cache_dir=tmp_path,
    )


class TestFetch:
    def test_tidy_kommun_known_value(self, tmp_path: Path) -> None:
        """Adapter returns only kommuner rows with correct geo_id and value_raw."""
        source = {
            "adapter": "socialstyrelsen",
            "id": "se_test",
            "amne": AMNE,
            "matt": 1,
        }
        df = seeded_adapter(tmp_path).fetch(source)
        assert set(df["country"]) == {"SE"}
        assert set(df["geo_id"]) <= {
            "SE-0180", "SE-1480", "SE-1280", "SE-0580", "SE-2480"
        }
        assert len(df) == N_FIXTURE_ROWS

        sthlm = df[df["geo_id"] == "SE-0180"].reset_index(drop=True)
        assert sthlm.iloc[0]["geo_name"] == "Stockholm"
        assert sthlm.iloc[0]["aar"] == STHLM_FIRST_AAR
        assert sthlm.iloc[0]["value_raw"] == STHLM_FIRST_VARDE

    def test_value_swedish_decimal_converted(self, tmp_path: Path) -> None:
        """Swedish decimal strings (comma-separated) are parsed to float."""
        source = {"adapter": "socialstyrelsen", "id": "se_test",
                  "amne": AMNE, "matt": 1}
        df = seeded_adapter(tmp_path).fetch(source)
        sthlm = df[df["geo_id"] == "SE-0180"].reset_index(drop=True)
        # "39,3" -> 39.3
        assert abs(float(sthlm.iloc[0]["value"]) - 39.3) < 0.001

    def test_lan_and_riket_rows_dropped(self, tmp_path: Path) -> None:
        """Rows with 2-digit regionId (lan) or '00' (riket) are excluded."""
        ad = seeded_adapter(tmp_path)
        rows = json.loads(
            (tmp_path / f"sst_{AMNE}_m1.json").read_text(encoding="utf-8")
        )
        # Inject a riket row ("00") and a lan row ("01")
        rows.append({"vardformId": "SV", "typId": "1", "regionId": "00",
                     "alderId": 1, "konId": 1, "mattId": 1,
                     "ar": "1995-1997", "varde": "9999"})
        rows.append({"vardformId": "SV", "typId": "1", "regionId": "01",
                     "alderId": 1, "konId": 1, "mattId": 1,
                     "ar": "1995-1997", "varde": "9999"})
        (tmp_path / f"sst_{AMNE}_m1.json").write_text(
            json.dumps(rows), encoding="utf-8"
        )
        df = ad.fetch({"adapter": "socialstyrelsen", "id": "se_test",
                       "amne": AMNE, "matt": 1})
        # Still only our 5 kommuner rows
        assert len(df) == N_FIXTURE_ROWS
        assert "9999" not in df["value_raw"].values

    def test_year_filter_reduces_rows(self, tmp_path: Path) -> None:
        """years filter keeps only rows with matching ar string."""
        source = {"adapter": "socialstyrelsen", "id": "se_test",
                  "amne": AMNE, "matt": 1, "years": [STHLM_FIRST_AAR]}
        df = seeded_adapter(tmp_path).fetch(source)
        assert len(df) > 0
        assert set(df["aar"]) == {STHLM_FIRST_AAR}
        # Only Stockholm rows match this year window
        assert set(df["geo_id"]) == {"SE-0180"}

    def test_suppressed_value_becomes_nan(self, tmp_path: Path) -> None:
        """Suppressed varde values ('X', '..') produce NaN in value column."""
        ad = seeded_adapter(tmp_path)
        rows = json.loads(
            (tmp_path / f"sst_{AMNE}_m1.json").read_text(encoding="utf-8")
        )
        rows.append({"vardformId": "SV", "typId": "1", "regionId": "0180",
                     "alderId": 99, "konId": 1, "mattId": 1,
                     "ar": "1995-1997", "varde": "X"})
        rows.append({"vardformId": "SV", "typId": "1", "regionId": "0180",
                     "alderId": 98, "konId": 1, "mattId": 1,
                     "ar": "1995-1997", "varde": ".."})
        (tmp_path / f"sst_{AMNE}_m1.json").write_text(
            json.dumps(rows), encoding="utf-8"
        )
        df = ad.fetch({"adapter": "socialstyrelsen", "id": "se_test",
                       "amne": AMNE, "matt": 1})
        suppressed = df[df["value_raw"].isin(["X", ".."])]
        assert len(suppressed) == 2
        assert suppressed["value"].isna().all()


class TestPagination:
    def test_follows_nasta_sida_as_https(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """nasta_sida http:// links are rewritten to https:// before following."""
        pages = {
            "https://sdb.socialstyrelsen.se/p1": {
                "data": [{"vardformId": "SV", "typId": "1", "regionId": "0180",
                          "alderId": 1, "konId": 1, "mattId": 1,
                          "ar": "1995-1997", "varde": "39,3"}],
                "nasta_sida": "http://sdb.socialstyrelsen.se/p2",
            },
            "https://sdb.socialstyrelsen.se/p2": {
                "data": [{"vardformId": "SV", "typId": "1", "regionId": "0180",
                          "alderId": 2, "konId": 1, "mattId": 1,
                          "ar": "1995-1997", "varde": "55,1"}],
                "nasta_sida": None,
            },
        }
        calls: list[str] = []

        class FakeResp:
            status_code = 200

            def __init__(self, payload: dict) -> None:
                self._p = payload

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return self._p

        def fake_request(method: str, url: str, **kw) -> FakeResp:
            calls.append(url)
            return FakeResp(pages[url])

        monkeypatch.setattr(
            "omsorgsradar.core.adapters.http.requests.request", fake_request
        )
        ad = SocialstyrelsenAdapter(cache_dir=None)
        rows = ad._fetch_all_pages(
            "https://sdb.socialstyrelsen.se/p1", max_pages=10
        )
        assert [r["varde"] for r in rows] == ["39,3", "55,1"]
        assert calls == [
            "https://sdb.socialstyrelsen.se/p1",
            "https://sdb.socialstyrelsen.se/p2",  # http-> https rewritten
        ]

    def test_cross_host_nasta_sida_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A nasta_sida pointing at a foreign host is never followed."""

        class FakeResp:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return {"data": [], "nasta_sida": "http://attacker.example/x"}

        monkeypatch.setattr(
            "omsorgsradar.core.adapters.http.requests.request",
            lambda method, url, **kw: FakeResp(),
        )
        ad = SocialstyrelsenAdapter(cache_dir=None)
        with pytest.raises(RuntimeError, match="cross-host"):
            ad._fetch_all_pages("https://sdb.socialstyrelsen.se/p1", max_pages=5)

    def test_max_pages_exceeded_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RuntimeError is raised when max_pages is reached with pagination active."""

        class FakeResp:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return {
                    "data": [],
                    "nasta_sida": "http://sdb.socialstyrelsen.se/next",
                }

        monkeypatch.setattr(
            "omsorgsradar.core.adapters.http.requests.request",
            lambda method, url, **kw: FakeResp(),
        )
        ad = SocialstyrelsenAdapter(cache_dir=None)
        with pytest.raises(RuntimeError, match="max_pages"):
            ad._fetch_all_pages(
                "https://sdb.socialstyrelsen.se/p1", max_pages=3
            )


@pytest.mark.live
class TestLive:
    def test_live_topic_list_still_has_amne(self) -> None:
        """Confirm our fixture topic still appears in the live API topic list."""
        import requests

        topics = requests.get(
            "https://sdb.socialstyrelsen.se/api/v1/sv", timeout=60
        ).json()
        assert AMNE in {t["namn"] for t in topics}
