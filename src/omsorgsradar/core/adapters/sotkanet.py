"""Sotkanet (THL, Finland) REST adapter.

API shapes verified live 2026-06-12:
- data:    GET {base}/json?indicator=<id>&years=<y>…&genders=total
           -> [{"indicator":127,"region":52,"year":2023,"gender":"total","value":9646}, …]
- regions: GET {base}/regions -> [{"id":…,"code":"091","category":"KUNTA",
           "title":{"fi":"Helsinki",…}}, …]  ("region" in data rows = internal "id")
License CC BY 4.0, no auth. ~3,700 indicators, municipality level.
Note: API returns 403 without a User-Agent header; DEFAULT_HEADERS supplies one.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests

from ..geo import make_geo_id
from .cache import DEFAULT_TIMEOUT, JsonCache
from .http import safe_request

logger = logging.getLogger(__name__)

TIDY_COLUMNS = ["country", "geo_code", "geo_id", "geo_name",
                "aar", "indicator", "gender", "value"]

# Sotkanet API returns 403 for requests with no User-Agent (verified 2026-06-12).
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "omsorgsradar/1.0 (research; github.com/Alksalt)",
}


class SotkanetAdapter:
    """Fetch Sotkanet indicator data for Finnish municipalities (KUNTA).

    Args:
        base_url: Root of the Sotkanet REST API.
        cache_dir: Directory for raw-JSON disk cache.  ``None`` disables caching.
        timeout: HTTP request timeout in seconds.
    """

    source_id = "sotkanet"
    DEFAULT_BASE_URL = "https://sotkanet.fi/rest/1.1"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout
        from urllib.parse import urlparse as _up
        host = (_up(base_url).hostname or "").lower()
        self._allowed_hosts: frozenset[str] = frozenset({host} if host else set())

    def _get_json(self, url: str, params: dict | None, cache_key: str) -> Any:
        """GET JSON with disk-cache short-circuit.

        Args:
            url: Full URL to GET.
            params: Optional query parameters.
            cache_key: Key used for the disk cache (must be safe per
                :class:`~omsorgsradar.core.adapters.cache.JsonCache`).

        Returns:
            Parsed JSON (list or dict).
        """
        cached = self.cache.load(cache_key)
        if cached is not None:
            return cached
        logger.info("GET %s", url)
        resp = safe_request(
            "GET", url,
            allowed_hosts=self._allowed_hosts,
            params=params,
            timeout=self.timeout,
            headers=DEFAULT_HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
        self.cache.save(cache_key, data)
        return data

    def municipalities(self) -> dict[int, tuple[str, str]]:
        """Return Sotkanet internal region id -> (3-digit kunta code, Finnish name).

        Only entries with ``category == "KUNTA"`` are included; supra-municipal
        regions (MAAKUNTA, ALUEHALLINTOVIRASTO, etc.) are excluded.

        Returns:
            Mapping from internal integer region id to ``(code, fi_name)`` tuple.
        """
        regions = self._get_json(
            f"{self.base_url}/regions", params=None, cache_key="sotkanet_regions"
        )
        return {
            r["id"]: (str(r["code"]).zfill(3), r.get("title", {}).get("fi", ""))
            for r in regions
            if r.get("category") == "KUNTA"
        }

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        """Fetch one or more Sotkanet indicators and return a tidy DataFrame.

        Args:
            source: Source config mapping with keys:
                - ``indicators``: list of integer indicator ids.
                - ``years``: list of years (int or str).
                - ``genders`` (optional): gender filter string, default ``"total"``.

        Returns:
            Tidy DataFrame with columns ``["country", "geo_code", "geo_id",
            "geo_name", "aar", "indicator", "gender", "value"]``.
            Rows are limited to Finnish municipalities (KUNTA).
            Returns an empty DataFrame (same columns) when no data is found.
        """
        years = sorted(int(y) for y in source["years"])
        gender = str(source.get("genders", "total"))
        kunta = self.municipalities()
        frames: list[pd.DataFrame] = []
        for ind in source["indicators"]:
            year_part = "-".join(str(y) for y in years)  # full list: no collision
            key = f"sotkanet_{ind}_{year_part}_{gender}"
            rows = self._get_json(
                f"{self.base_url}/json",
                params={"indicator": str(ind),
                        "years": [str(y) for y in years],
                        "genders": gender},
                cache_key=key,
            )
            df = pd.DataFrame(rows)
            if df.empty:
                logger.warning("Sotkanet indicator %s returned no rows", ind)
                continue
            df = df[df["region"].isin(kunta)].copy()
            df["geo_code"] = df["region"].map(lambda r: kunta[r][0])
            df["geo_name"] = df["region"].map(lambda r: kunta[r][1])
            df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("FI", c))
            df["aar"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
            df["indicator"] = str(ind)
            df["country"] = "FI"
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            frames.append(df[TIDY_COLUMNS])
        if not frames:
            return pd.DataFrame(columns=TIDY_COLUMNS)
        out = pd.concat(frames, ignore_index=True)
        logger.info("Sotkanet: %d rows, %d kunta, indicators %s",
                    len(out), out["geo_id"].nunique(), sorted(out["indicator"].unique()))
        return out
