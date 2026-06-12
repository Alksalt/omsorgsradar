"""KUHR (helserefusjon åpne data) adapter — offline via pre-seeded cache."""

import shutil
from pathlib import Path

import pytest

from omsorgsradar.core.adapters.kuhr import KuhrAdapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

# Paste literals printed by the capture script (Task 5 / Step 1):
FALE_ANTALL_REGNINGER = 57602   # <- replace
FALE_SUM_REFUSJON = 4756525.0     # <- replace

SOURCE = {"adapter": "kuhr", "id": "no_kuhr", "fagomraade": "LE",
          "fomar": 2023, "tomar": 2023, "kommuner": ["1505"], "takstkoder": ["2ad"]}


def seeded_adapter(tmp_path: Path) -> KuhrAdapter:
    shutil.copy(FIXTURE_DIR / "kuhr_le_1505_fixture.json",
                tmp_path / "kuhr_LE_2023_2023_t2ad_k1505.json")
    return KuhrAdapter(base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path)


class TestFetch:
    def test_tidy_known_values(self, tmp_path: Path) -> None:
        df = seeded_adapter(tmp_path).fetch(SOURCE)
        assert set(df["country"]) == {"NO"}
        assert set(df["geo_id"]) == {"NO-1505"}      # Kristiansund, post-merger stable
        assert set(df["aar"]) == {2023}
        assert set(df["indicator"]) == {"LE_2ad"}
        fale = df[df["praksis_type_kode"] == "FALE"]
        assert len(fale) == 1
        assert fale.iloc[0]["antall_regninger"] == FALE_ANTALL_REGNINGER
        assert fale.iloc[0]["sum_refusjon"] == FALE_SUM_REFUSJON
        assert fale.iloc[0]["value"] == FALE_ANTALL_REGNINGER  # default value_field

    def test_value_field_override(self, tmp_path: Path) -> None:
        src = dict(SOURCE, value_field="sum_refusjon")
        df = seeded_adapter(tmp_path).fetch(src)
        fale = df[df["praksis_type_kode"] == "FALE"]
        assert fale.iloc[0]["value"] == FALE_SUM_REFUSJON

    def test_merger_normalization(self, tmp_path: Path) -> None:
        import json
        ad = seeded_adapter(tmp_path)
        payload = json.loads(
            (FIXTURE_DIR / "kuhr_le_1505_fixture.json").read_text(encoding="utf-8")
        )
        payload["takstbruk"][0]["behandler_kommunenr"] = "0220"  # gamle Asker
        (tmp_path / "kuhr_LE_2023_2023_t2ad_k1505.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        df = ad.fetch(SOURCE)
        assert "NO-3025" in set(df["geo_id"])  # 0220 -> 3025 (Asker, 2020-merger)


@pytest.mark.live
class TestLive:
    def test_live_fagomraader_contains_lege(self) -> None:
        import requests
        data = requests.get("https://opne-data-api.helserefusjon.no/v1/fagomraader",
                            headers={"Accept": "application/json"}, timeout=60).json()
        assert "LE" in {f["fagomraadekode"] for f in data["fagomraader"]}
