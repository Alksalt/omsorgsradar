"""KUHR / helserefusjon åpne data (Helsedirektoratet+NAV, NO) adapter.

API verified live 2026-06-12 (docs: github.com/navikt/Helserefusjon-apne-data):
GET {base}/takstbruk/agtakst/kommune/ar?fagomraade=LE&fomar=2023&tomar=2023
    [&takstkoder=2ad,…][&kommuner=1505,…][&praksistyper=FALE,…]
Accept: application/json ->
{"antall":4,"takstbruk":[{"ar":"2023","behandler_kommunenr":"1505",
 "sum_antall_takst":57602,"takstkode":"2ad","fagomraade":"LE",
 "praksis_type_kode":"FALE","samhandler_praksis_type":"Fastlege",
 "antall_regninger":57602,"sum_refusjon":4756525.0,
 "sum_egenandel_betalt_av_pasient":…,"sum_egenandel_dekket_av_folketrygden":…}]}
Geography = practitioner's municipality. No auth.
No geo_name column — KUHR exposes only practitioner kommune codes; names
are not in the API. Downstream join on geo_id if a name is needed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests

from ...kommune_mergers import normalize_knr_series
from ..geo import make_geo_id
from .cache import DEFAULT_TIMEOUT, JsonCache

logger = logging.getLogger(__name__)

MEASURE_COLUMNS = ["sum_antall_takst", "antall_regninger", "sum_refusjon",
                   "sum_egenandel_betalt_av_pasient",
                   "sum_egenandel_dekket_av_folketrygden"]
TIDY_COLUMNS = (["country", "geo_code", "geo_id", "knr_raw", "aar", "indicator",
                 "fagomraade", "takstkode", "praksis_type_kode",
                 "samhandler_praksis_type"] + MEASURE_COLUMNS + ["value"])
DEFAULT_VALUE_FIELD = "antall_regninger"


class KuhrAdapter:
    """Fetch KUHR takstbruk (billing/refusjon) data per kommune from helserefusjon.no.

    Args:
        base_url: API base URL.
        cache_dir: Directory for raw JSON cache. ``None`` disables caching.
        timeout: HTTP request timeout in seconds.
    """

    source_id = "kuhr"
    DEFAULT_BASE_URL = "https://opne-data-api.helserefusjon.no/v1"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout

    @staticmethod
    def _cache_key(source: Mapping[str, Any]) -> str:
        """Build a safe, deterministic cache key from source config.

        Args:
            source: Source configuration mapping.

        Returns:
            Cache key string like ``kuhr_LE_2023_2023_t2ad_k1505``.
        """
        parts = ["kuhr", str(source["fagomraade"]),
                 str(source["fomar"]), str(source["tomar"])]
        for prefix, field in (("t", "takstkoder"), ("k", "kommuner"),
                              ("p", "praksistyper")):
            vals = source.get(field)
            if vals:
                parts.append(prefix + "-".join(str(v) for v in vals))
        return "_".join(parts)

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        """Fetch takstbruk data for the given source config, returning a tidy DataFrame.

        Loads from disk cache if available; otherwise GETs from the API and
        caches the raw JSON. Applies kommune merger normalization so pre-2020
        municipality codes land on their post-merger equivalents.

        Args:
            source: Source config dict with keys:
                - ``fagomraade`` (str): e.g. ``"LE"`` for fastlege.
                - ``fomar`` (int): first year (inclusive).
                - ``tomar`` (int): last year (inclusive).
                - ``kommuner`` (list[str], optional): filter to these kommune codes.
                - ``takstkoder`` (list[str], optional): filter to these takst codes.
                - ``praksistyper`` (list[str], optional): filter to these practice types.
                - ``value_field`` (str, optional): which measure column to use as
                  ``value``; defaults to ``"antall_regninger"``.

        Returns:
            Tidy DataFrame with columns defined by ``TIDY_COLUMNS``. Empty
            DataFrame (same schema) if the API returns no rows.

        Raises:
            ValueError: if ``value_field`` is not a known measure column.
            requests.HTTPError: on non-2xx API responses.
        """
        key = self._cache_key(source)
        payload = self.cache.load(key)
        if payload is None:
            params: dict[str, str] = {
                "fagomraade": str(source["fagomraade"]),
                "fomar": str(source["fomar"]),
                "tomar": str(source["tomar"]),
            }
            for field in ("takstkoder", "kommuner", "praksistyper"):
                vals = source.get(field)
                if vals:
                    params[field] = ",".join(str(v) for v in vals)
            url = f"{self.base_url}/takstbruk/agtakst/kommune/ar"
            logger.info("GET %s %s", url, params)
            resp = requests.get(url, params=params,
                                headers={"Accept": "application/json"},
                                timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            self.cache.save(key, payload)

        rows = payload.get("takstbruk", [])
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=TIDY_COLUMNS)
        df["knr_raw"] = df["behandler_kommunenr"].astype(str).str.strip().str.zfill(4)
        df["geo_code"] = normalize_knr_series(df["knr_raw"])
        df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("NO", c))
        df["aar"] = pd.to_numeric(df["ar"], errors="coerce").astype("Int64")
        df["indicator"] = df["fagomraade"].astype(str) + "_" + df["takstkode"].astype(str)
        df["country"] = "NO"
        for col in MEASURE_COLUMNS:
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        value_field = str(source.get("value_field", DEFAULT_VALUE_FIELD))
        if value_field not in MEASURE_COLUMNS:
            raise ValueError(
                f"kuhr source '{source.get('id')}': unknown value_field "
                f"'{value_field}' (known: {MEASURE_COLUMNS})"
            )
        df["value"] = df[value_field]
        logger.info("KUHR %s: %d rows, %d kommuner, years %s",
                    source["fagomraade"], len(df), df["geo_id"].nunique(),
                    sorted(df["aar"].dropna().unique().tolist()))
        return df[TIDY_COLUMNS]
