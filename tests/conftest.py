"""Shared fixtures: fixture-built datasets for offline pipeline runs."""

import json
from pathlib import Path

import pandas as pd
import pytest

from omsorgsradar.core.adapters.pxweb import jsonstat2_to_df
from omsorgsradar.kommune_mergers import normalize_knr_series

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _prep(payload: dict, *, has_alder: bool) -> pd.DataFrame:
    df = jsonstat2_to_df(payload)
    rename = {"Region": "region_label", "Tid": "aar"}
    if has_alder:
        rename["Alder"] = "alder"
    df = df.rename(columns=rename)
    df["knr_raw"] = (
        df["region_label"].str.extract(r"^(\d{4})", expand=False).str.zfill(4)
    )
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    return df


@pytest.fixture()
def fixture_datasets() -> dict[str, pd.DataFrame]:
    kostra = json.loads(
        (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
    )
    pop = json.loads((FIXTURE_DIR / "pop_fixture.json").read_text(encoding="utf-8"))
    return {
        "kostra_pleie": _prep(kostra, has_alder=False),
        "befolkning": _prep(pop, has_alder=True),
        "framskrivinger": pd.DataFrame(),
        "fhi_nokkel": pd.DataFrame(),
    }
