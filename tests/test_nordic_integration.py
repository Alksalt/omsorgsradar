"""Fixture-driven ingest+profile run across sotkanet + kuhr + csv — no network.

Caches are pre-seeded under the exact keys the adapters compute, so any HTTP
attempt would hit an unreachable host and fail the test.
"""

import json
import shutil
from pathlib import Path

import duckdb

from omsorgsradar.pipeline import run_pipeline

FIXTURE_DIR = Path(__file__).parent / "fixtures"

ANALYSIS_TOML = """\
[analysis]
name = "nordisk-test"
question = "integrasjonstest"

[stages]
list = ["ingest", "profile"]

[[sources]]
adapter = "sotkanet"
id = "fi_test"
indicators = [127]
years = [2023]

[[sources]]
adapter = "kuhr"
id = "no_kuhr"
fagomraade = "LE"
fomar = 2023
tomar = 2023
kommuner = ["1505"]
takstkoder = ["2ad"]

[[sources]]
adapter = "csv"
id = "se_csv"
path = "se_data.csv"
[sources.rename]
kommun = "geo_code"
ar = "aar"
varde = "value"
[sources.provenance]
institution = "Socialstyrelsen (Sverige)"
url = "https://www.socialstyrelsen.se/statistik-och-data/oppna-data/"
"""


def test_nordic_ingest_profile_offline(tmp_path: Path) -> None:
    adir = tmp_path / "analyses" / "nordisk-test"
    adir.mkdir(parents=True)
    (adir / "analysis.toml").write_text(ANALYSIS_TOML, encoding="utf-8")
    (adir / "se_data.csv").write_text(
        "kommun,ar,varde\n0180,2023,12.5\n1480,2023,9.0\n", encoding="utf-8"
    )

    data_dir = tmp_path / "data"
    cache = data_dir / "cache"
    cache.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "sotkanet_regions_fixture.json",
                cache / "sotkanet_regions.json")
    shutil.copy(FIXTURE_DIR / "sotkanet_127_fixture.json",
                cache / "sotkanet_127_2023_2023_total.json")
    shutil.copy(FIXTURE_DIR / "kuhr_le_1505_fixture.json",
                cache / "kuhr_LE_2023_2023_t2ad_k1505.json")

    run_pipeline(
        adir,
        data_dir=data_dir,
        reports_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
    )

    quality = json.loads((data_dir / "quality_profile.json").read_text(encoding="utf-8"))
    for ds in ("fi_test", "no_kuhr", "se_csv"):
        verdict = quality["datasets"][ds]["realness"]["verdict"]
        assert verdict in ("PASS", "WARN"), f"{ds}: {verdict}"

    con = duckdb.connect(str(data_dir / "nordisk-test.duckdb"), read_only=True)
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()
    assert {"fi_test", "no_kuhr", "se_csv"} <= tables

    assert quality["datasets"]["fi_test"]["n_geo"] == 5  # the five fixture kuntas
