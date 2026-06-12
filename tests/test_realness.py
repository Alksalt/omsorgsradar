"""Realness gates — the 5 Kaggle-fabrication triage checks as code."""

import numpy as np
import pandas as pd
import pytest

from omsorgsradar.realness import (
    GateCheck,
    check_distribution,
    check_duplicates,
    check_missingness,
    resolve_provenance,
    run_realness,
)

SSB_SOURCE = {"id": "kostra_pleie", "adapter": "pxweb",
              "base_url": "https://data.ssb.no/api/v0/no/table", "table": "12209"}


def realistic_df(n: int = 6000) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "geo_id": [f"NO-{i % 350:04d}" for i in range(n)],
        "aar": 2015 + (np.arange(n) % 10),
        "value": rng.normal(50, 10, n),
    })
    df.loc[df.sample(frac=0.03, random_state=1).index, "value"] = np.nan
    return df


def fabricated_df(n: int = 10_000) -> pd.DataFrame:
    base = pd.DataFrame({
        "geo_id": [f"NO-{i % 70:04d}" for i in range(n // 2)],
        "aar": 2020,
        "value": np.arange(n // 2) % 100,  # no missing at all
    })
    return pd.concat([base, base], ignore_index=True)  # 50% exact duplicates


class TestProvenance:
    def test_known_host_resolves(self) -> None:
        prov = resolve_provenance(SSB_SOURCE)
        assert prov is not None and "SSB" in prov["institution"]

    def test_explicit_provenance_wins(self) -> None:
        prov = resolve_provenance({"provenance": {"institution": "THL",
                                                  "url": "https://sotkanet.fi"}})
        assert prov == {"institution": "THL", "url": "https://sotkanet.fi"}

    def test_unknown_host_no_provenance_is_none(self) -> None:
        assert resolve_provenance({"base_url": "https://evil.example.com"}) is None

    def test_adapter_default_provenance_when_base_url_omitted(self) -> None:
        # Nordic sources usually omit base_url (adapter default) — provenance
        # must resolve from the adapter name, not FAIL.
        for adapter, marker in (("sotkanet", "THL"), ("kuhr", "Helsedirektoratet"),
                                ("socialstyrelsen", "Socialstyrelsen")):
            prov = resolve_provenance({"id": "x", "adapter": adapter})
            assert prov is not None and marker in prov["institution"], adapter


class TestChecks:
    def test_duplicates_fail_above_one_percent(self) -> None:
        assert check_duplicates(fabricated_df()).status == "FAIL"
        assert check_duplicates(realistic_df()).status == "PASS"

    def test_missingness_warns_on_implausible_perfection(self) -> None:
        assert check_missingness(fabricated_df()).status == "WARN"
        assert check_missingness(realistic_df()).status == "PASS"
        all_nan = realistic_df().assign(value=np.nan)
        assert check_missingness(all_nan).status == "FAIL"

    def test_distribution_zero_variance_fails(self) -> None:
        flat = realistic_df().assign(value=7.0)
        assert check_distribution(flat).status == "FAIL"
        assert check_distribution(realistic_df()).status == "PASS"

    def test_empty_df_skips(self) -> None:
        empty = pd.DataFrame()
        for check in (check_duplicates, check_missingness, check_distribution):
            assert check(empty).status == "SKIP"


class TestVerdict:
    def test_fabricated_dataset_fails_overall(self) -> None:
        report = run_realness(fabricated_df(), SSB_SOURCE)
        assert report["verdict"] == "FAIL"
        by_name = {c["name"]: c["status"] for c in report["checks"]}
        assert by_name["duplicates"] == "FAIL"
        assert by_name["missingness"] == "WARN"

    def test_realistic_known_source_passes(self) -> None:
        report = run_realness(realistic_df(), SSB_SOURCE)
        assert report["verdict"] == "PASS"
        assert {c["name"] for c in report["checks"]} == {
            "provenance", "institution", "duplicates", "missingness", "distribution"
        }

    def test_no_provenance_fails(self) -> None:
        report = run_realness(realistic_df(), {"id": "mystery"})
        assert report["verdict"] == "FAIL"

    def test_empty_df_verdict_skip_never_blocks(self) -> None:
        report = run_realness(pd.DataFrame(), SSB_SOURCE)
        assert report["verdict"] in ("PASS", "SKIP")  # empty data must not gate
