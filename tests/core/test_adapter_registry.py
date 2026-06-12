"""Adapter registry: validation errors name the offending key; dispatch works."""

from pathlib import Path

import pytest

from omsorgsradar.core.adapters import (
    LEGACY_SOURCE_IDS,
    REQUIRED_SOURCE_FIELDS,
    make_adapter,
    validate_source,
)
from omsorgsradar.core.config import ConfigError


class TestValidateSource:
    def test_legacy_ids_skip_validation(self) -> None:
        for sid in LEGACY_SOURCE_IDS:
            validate_source({"id": sid, "adapter": "whatever"})  # no raise

    def test_unknown_adapter_names_it(self) -> None:
        with pytest.raises(ConfigError, match="unknown adapter 'nope'"):
            validate_source({"id": "x", "adapter": "nope"})

    @pytest.mark.parametrize("adapter", sorted(REQUIRED_SOURCE_FIELDS))
    def test_missing_required_fields_named(self, adapter: str) -> None:
        with pytest.raises(ConfigError, match="missing required"):
            validate_source({"id": "x", "adapter": adapter})

    def test_csv_requires_full_provenance(self) -> None:
        with pytest.raises(ConfigError, match="provenance"):
            validate_source({"id": "x", "adapter": "csv", "path": "f.csv",
                             "provenance": {"institution": "T"}})  # url missing


class TestMakeAdapter:
    def test_each_adapter_constructs(self, tmp_path: Path) -> None:
        sources = [
            {"id": "a", "adapter": "pxweb",
             "base_url": "https://data.ssb.no/api/v0/no/table", "table": "12209"},
            {"id": "b", "adapter": "sotkanet", "indicators": [127], "years": [2023]},
            {"id": "c", "adapter": "socialstyrelsen", "amne": "amning", "matt": 1},
            {"id": "d", "adapter": "kuhr", "fagomraade": "LE",
             "fomar": 2023, "tomar": 2023},
            {"id": "e", "adapter": "csv", "path": "f.csv",
             "provenance": {"institution": "T", "url": "https://x"}},
        ]
        for src in sources:
            adapter = make_adapter(src, cache_dir=tmp_path, base_dir=tmp_path)
            assert adapter.source_id == src["adapter"]

    def test_fetchers_and_legacy_ids_agree(self) -> None:
        from omsorgsradar.ingest import _FETCHERS
        assert set(_FETCHERS) == set(LEGACY_SOURCE_IDS)

    def test_make_adapter_enforces_host_allowlist(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not allowlisted"):
            make_adapter(
                {"id": "x", "adapter": "pxweb",
                 "base_url": "https://evil.example.com", "table": "1"},
                cache_dir=tmp_path,
            )

    def test_make_adapter_extra_hosts_honored(self, tmp_path: Path) -> None:
        ad = make_adapter(
            {"id": "x", "adapter": "pxweb",
             "base_url": "https://api.statbank.dk/v1", "table": "1"},
            cache_dir=tmp_path,
            extra_hosts=frozenset({"api.statbank.dk"}),
        )
        assert ad.source_id == "pxweb"


class TestConfigSchema:
    def test_source_id_pattern_locked(self, tmp_path: Path) -> None:
        from omsorgsradar.core.config import load_analysis_config
        (tmp_path / "analysis.toml").write_text(
            '[analysis]\nname = "t"\n[stages]\nlist = ["ingest"]\n'
            '[[sources]]\nadapter = "csv"\nid = "Bad-Id"\npath = "f.csv"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="id"):
            load_analysis_config(tmp_path / "analysis.toml")
