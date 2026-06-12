"""Dataset realness gates — the Kaggle-fabrication triage checks as code.

Background (wiki tech/agentic-healthcare-analysis-workflow-2026, Retraction
Watch 2026-05): 124 papers were built on fabricated Kaggle health datasets —
thousands of exact duplicates, implausibly few missing values, no traceable
institution. These five checks run in the profile stage on every dataset,
the verdict is published in quality_profile.json, and a FAIL aborts the
pipeline before analysis (DECISIONS.md).

Checks: provenance (URL/DOI), named institution, exact-duplicate rate,
missingness plausibility, distribution sanity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping
from urllib.parse import urlparse

import pandas as pd

# Thresholds (research-derived defaults; override per analysis via
# [params.realness] once a real case demands it — YAGNI until then).
DUPLICATE_FAIL_RATE = 0.01      # >1% exact duplicate rows
ALL_MISSING_FAIL_RATE = 0.95    # value column effectively empty
PERFECT_DATA_MIN_ROWS = 5000    # 0 missing at this size is suspicious
ZERO_VARIANCE_MIN_ROWS = 100

KNOWN_HOSTS: dict[str, str] = {
    "data.ssb.no": "Statistisk sentralbyrå (SSB)",
    "statistikk-data.fhi.no": "Folkehelseinstituttet (FHI)",
    "sotkanet.fi": "Terveyden ja hyvinvoinnin laitos (THL)",
    "sdb.socialstyrelsen.se": "Socialstyrelsen (Sverige)",
    "opne-data-api.helserefusjon.no": "Helsedirektoratet / NAV (helserefusjon, KUHR)",
}

# Fallback when a source omits base_url (the adapter supplies its default URL):
ADAPTER_PROVENANCE: dict[str, dict[str, str]] = {
    "sotkanet": {"institution": "Terveyden ja hyvinvoinnin laitos (THL)",
                 "url": "https://sotkanet.fi/rest/1.1"},
    "socialstyrelsen": {"institution": "Socialstyrelsen (Sverige)",
                        "url": "https://sdb.socialstyrelsen.se/api/v1/sv"},
    "kuhr": {"institution": "Helsedirektoratet / NAV (helserefusjon, KUHR)",
             "url": "https://opne-data-api.helserefusjon.no/v1"},
}


@dataclass(frozen=True)
class GateCheck:
    name: str
    status: str  # PASS | WARN | FAIL | SKIP
    detail: str


def resolve_provenance(source: Mapping[str, Any]) -> dict[str, str] | None:
    """Explicit [sources.provenance] wins; else a known API host; else the
    adapter's default endpoint (sources usually omit base_url)."""
    prov = source.get("provenance")
    if isinstance(prov, Mapping) and prov.get("institution") and prov.get("url"):
        return {"institution": str(prov["institution"]), "url": str(prov["url"])}
    base = str(source.get("base_url", ""))
    host = urlparse(base).netloc.lower()
    for known, institution in KNOWN_HOSTS.items():
        if host == known or host.endswith("." + known):
            return {"institution": institution, "url": base}
    if not base:
        return ADAPTER_PROVENANCE.get(str(source.get("adapter", "")))
    return None


def check_provenance(source: Mapping[str, Any]) -> GateCheck:
    prov = resolve_provenance(source)
    if prov is None:
        return GateCheck("provenance", "FAIL",
                         "no resolvable provenance — add [sources.provenance] "
                         "institution+url or use a known open-data host")
    return GateCheck("provenance", "PASS", f"url: {prov['url']}")


def check_institution(source: Mapping[str, Any]) -> GateCheck:
    prov = resolve_provenance(source)
    if prov is None:
        return GateCheck("institution", "FAIL", "no named institution")
    return GateCheck("institution", "PASS", prov["institution"])


def check_duplicates(df: pd.DataFrame) -> GateCheck:
    if df.empty:
        return GateCheck("duplicates", "SKIP", "empty dataset")
    rate = float(df.duplicated().mean())
    if rate > DUPLICATE_FAIL_RATE:
        return GateCheck("duplicates", "FAIL",
                         f"{rate:.1%} exact duplicate rows (limit {DUPLICATE_FAIL_RATE:.0%})")
    return GateCheck("duplicates", "PASS", f"{rate:.2%} exact duplicate rows")


def check_missingness(df: pd.DataFrame) -> GateCheck:
    if df.empty or "value" not in df.columns:
        return GateCheck("missingness", "SKIP", "empty dataset or no value column")
    rate = float(df["value"].isna().mean())
    if rate >= ALL_MISSING_FAIL_RATE:
        return GateCheck("missingness", "FAIL",
                         f"value column {rate:.0%} missing — no usable data")
    if rate == 0.0 and len(df) >= PERFECT_DATA_MIN_ROWS:
        return GateCheck("missingness", "WARN",
                         f"0 missing values in {len(df):,} rows — implausibly "
                         "perfect for real-world data (fabrication signature)")
    return GateCheck("missingness", "PASS", f"{rate:.1%} missing in value column")


def check_distribution(df: pd.DataFrame) -> GateCheck:
    if df.empty or "value" not in df.columns:
        return GateCheck("distribution", "SKIP", "empty dataset or no value column")
    clean = pd.to_numeric(df["value"], errors="coerce").dropna()
    if clean.empty:
        return GateCheck("distribution", "SKIP", "no numeric values")
    if len(clean) >= ZERO_VARIANCE_MIN_ROWS and clean.nunique() == 1:
        return GateCheck("distribution", "FAIL",
                         f"zero variance: all {len(clean):,} values == {clean.iloc[0]}")
    return GateCheck(
        "distribution", "PASS",
        f"min={clean.min():.4g} median={clean.median():.4g} max={clean.max():.4g}",
    )


def run_realness(df: pd.DataFrame, source: Mapping[str, Any]) -> dict[str, Any]:
    """All five gates; verdict FAIL > WARN > PASS; all-SKIP data never gates."""
    checks = [
        check_provenance(source),
        check_institution(source),
        check_duplicates(df),
        check_missingness(df),
        check_distribution(df),
    ]
    statuses = {c.status for c in checks}
    if "FAIL" in statuses:
        verdict = "FAIL"
    elif "WARN" in statuses:
        verdict = "WARN"
    elif statuses == {"SKIP"}:
        verdict = "SKIP"
    else:
        verdict = "PASS"
    return {"verdict": verdict, "checks": [asdict(c) for c in checks]}
