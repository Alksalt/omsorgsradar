"""Shared adapter cache: round-trip, miss, and key sanitization."""

from pathlib import Path

import pytest

from omsorgsradar.core.adapters.cache import CacheKeyError, JsonCache


class TestJsonCache:
    def test_round_trip(self, tmp_path: Path) -> None:
        cache = JsonCache(tmp_path)
        cache.save("sotkanet_127_2023_2023_total", {"a": [1, 2]})
        assert cache.load("sotkanet_127_2023_2023_total") == {"a": [1, 2]}
        assert (tmp_path / "sotkanet_127_2023_2023_total.json").exists()

    def test_miss_returns_none(self, tmp_path: Path) -> None:
        assert JsonCache(tmp_path).load("absent") is None

    def test_none_dir_is_noop(self) -> None:
        cache = JsonCache(None)
        cache.save("k", {"x": 1})  # must not raise
        assert cache.load("k") is None

    @pytest.mark.parametrize("bad", ["a/b", "../etc", "a..b", "a b", "", "nøkkel", "trailing\n"])
    def test_bad_keys_rejected(self, tmp_path: Path, bad: str) -> None:
        with pytest.raises(CacheKeyError):
            JsonCache(tmp_path).save(bad, {})
        with pytest.raises(CacheKeyError):
            JsonCache(tmp_path).load(bad)
