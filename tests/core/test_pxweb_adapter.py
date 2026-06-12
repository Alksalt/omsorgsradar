"""PxWeb adapter — JSON-stat2 parsing + cache behavior, fully offline."""

import json
from pathlib import Path

from omsorgsradar.core.adapters.pxweb import PxWebAdapter, jsonstat2_to_df

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class TestJsonStat2:
    def test_fixture_parses_to_tidy_df(self) -> None:
        payload = json.loads(
            (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        assert "value" in df.columns
        assert len(df) == len(payload["value"])


class TestAdapterCache:
    def test_post_table_uses_cache_without_network(self, tmp_path: Path) -> None:
        # Pre-seed the cache; base_url is unreachable on purpose — a cache hit
        # must short-circuit before any HTTP call.
        payload = {"dimension": {}, "id": [], "size": [], "value": []}
        (tmp_path / "12209.json").write_text(json.dumps(payload), encoding="utf-8")
        adapter = PxWebAdapter(
            base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path
        )
        out = adapter.post_table("12209", query={"query": []})
        assert out == payload


class TestFetchOptions:
    def _payload(self) -> dict:
        return {
            "dimension": {
                "Region": {"category": {
                    "index": {"0301": 0, "1505": 1},
                    "label": {"0301": "Oslo", "1505": "Kristiansund"},
                }},
            },
            "id": ["Region"],
            "size": [2],
            "value": [10.0, 20.0],
        }

    def test_use_codes_and_labels(self, tmp_path: Path) -> None:
        (tmp_path / "t1.json").write_text(json.dumps(self._payload()), encoding="utf-8")
        adapter = PxWebAdapter(base_url="http://127.0.0.1:9/x", cache_dir=tmp_path)
        source = {"table": "ignored", "cache_key": "t1",
                  "use_codes": True, "label_columns": True}
        df = adapter.fetch(source)
        assert df["Region"].tolist() == ["0301", "1505"]
        assert df["Region_label"].tolist() == ["Oslo", "Kristiansund"]

    def test_default_fetch_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "t2.json").write_text(json.dumps(self._payload()), encoding="utf-8")
        adapter = PxWebAdapter(base_url="http://127.0.0.1:9/x", cache_dir=tmp_path)
        df = adapter.fetch({"table": "ignored", "cache_key": "t2"})
        assert df["Region"].tolist() == ["Oslo", "Kristiansund"]  # v1 label behavior
        assert "Region_label" not in df.columns
