"""Startup security gate: base_url hosts must be allowlisted."""

import pytest

from omsorgsradar.core.adapters import ALLOWED_BASE_URL_HOSTS, validate_source_host
from omsorgsradar.core.config import ConfigError


class TestValidateSourceHost:
    def test_all_shipping_hosts_allowlisted(self) -> None:
        for host in ("data.ssb.no", "statistikk-data.fhi.no", "sotkanet.fi",
                     "sdb.socialstyrelsen.se", "opne-data-api.helserefusjon.no",
                     "api.kolada.se", "api.scb.se"):
            assert host in ALLOWED_BASE_URL_HOSTS, host

    def test_known_host_passes(self) -> None:
        validate_source_host({"id": "x", "adapter": "pxweb",
                              "base_url": "https://data.ssb.no/api/v0/no/table"})

    def test_subdomain_of_known_host_passes(self) -> None:
        validate_source_host({"id": "x", "base_url": "https://api.sotkanet.fi/rest"})

    def test_no_base_url_passes(self) -> None:
        validate_source_host({"id": "x", "adapter": "sotkanet"})  # adapter default

    def test_unknown_host_rejected_naming_it(self) -> None:
        with pytest.raises(ConfigError, match="evil.example.com.*not allowlisted"):
            validate_source_host({"id": "x", "base_url": "https://evil.example.com/api"})

    def test_lookalike_host_rejected(self) -> None:
        # suffix match must be on dot boundaries: notdata.ssb.no.evil.com etc.
        with pytest.raises(ConfigError):
            validate_source_host({"id": "x", "base_url": "https://data.ssb.no.evil.com/x"})

    def test_extra_hosts_extend_allowlist(self) -> None:
        src = {"id": "x", "base_url": "https://api.statbank.dk/v1"}
        with pytest.raises(ConfigError):
            validate_source_host(src)
        validate_source_host(src, extra_hosts=frozenset({"api.statbank.dk"}))


class TestPipelineStartupGate:
    def test_run_pipeline_rejects_unknown_host_before_any_stage(self, tmp_path) -> None:
        from omsorgsradar.pipeline import run_pipeline

        adir = tmp_path / "analyses" / "evil"
        adir.mkdir(parents=True)
        (adir / "analysis.toml").write_text(
            '[analysis]\nname = "evil"\n[stages]\nlist = ["ingest"]\n'
            '[[sources]]\nadapter = "pxweb"\nid = "bad"\n'
            'base_url = "https://evil.example.com/api"\ntable = "1"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="not allowlisted"):
            run_pipeline(adir, data_dir=tmp_path / "d",
                         reports_dir=tmp_path / "r", runs_dir=tmp_path / "runs")
        assert not list((tmp_path / "runs").glob("*")), "no journal before validation"
