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
