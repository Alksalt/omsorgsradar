"""Kolada (RKA, Sweden) municipal-KPI adapter — v3 REST API.

API verified live 2026-06-12:
- data: GET {base}/data/kpi/{kpi}/year/{year} ->
  {"values":[{"kpi":"N21704","period":2023,"municipality":"0180",
    "values":[{"gender":"T","value":16.8,"count":1,"status":"",…},
              {"gender":"M",…},{"gender":"K",…}]}, …]}
  municipality "0000" = riket; type "L" entries are regions.
- municipalities: GET {base}/municipality?per_page=500 (paginated via next_url) ->
  {"values":[{"id":"0180","title":"Stockholm","type":"K"}, …]}

Data origin: Socialstyrelsen/SCB official statistics republished per kommun by
RKA (Rådet för främjande av kommunala analyser) — open data, no auth. Used for
SE elder-care coverage because the Socialstyrelsen sdb API has no äldreomsorg
topic (verified 2026-06-12, see socialstyrelsen adapter docstring).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import pandas as pd
import requests

from ..geo import make_geo_id
from .cache import DEFAULT_TIMEOUT, JsonCache

logger = logging.getLogger(__name__)

TIDY_COLUMNS = ["country", "geo_code", "geo_id", "geo_name",
                "aar", "indicator", "gender", "value"]
MAX_MUNI_PAGES = 10


class KoladaAdapter:
    source_id = "kolada"
    DEFAULT_BASE_URL = "https://api.kolada.se/v3"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout

    def _get_json(self, url: str, cache_key: str | None) -> Any:
        if cache_key is not None:
            cached = self.cache.load(cache_key)
            if cached is not None:
                return cached
        logger.info("GET %s", url)
        resp = requests.get(url, headers={"Accept": "application/json"},
                            timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if cache_key is not None:
            self.cache.save(cache_key, data)
        return data

    def municipalities(self) -> dict[str, str]:
        """kommun code ('0180') -> name; type 'L' (regions/riket) excluded."""
        entries = self.cache.load("kolada_municipalities")
        if entries is None:
            entries = []
            url: str | None = f"{self.base_url}/municipality?per_page=500"
            for _ in range(MAX_MUNI_PAGES):
                if url is None:
                    break
                page = self._get_json(url, cache_key=None)
                entries.extend(page.get("values", []))
                nxt = page.get("next_url")
                if nxt:
                    host = urlparse(nxt).netloc.lower()
                    base_host = urlparse(self.base_url).netloc.lower()
                    if host != base_host:
                        raise RuntimeError(
                            f"kolada: next_url host {host!r} != base {base_host!r} "
                            "— refusing cross-host pagination"
                        )
                url = nxt or None
            self.cache.save("kolada_municipalities", entries)
        return {m["id"]: m["title"] for m in entries if m.get("type") == "K"}

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        kpi = str(source["kpi"])
        gender = str(source.get("gender", "T"))
        kommun = self.municipalities()
        rows: list[dict[str, Any]] = []
        for year in source["years"]:
            year = int(year)
            payload = self._get_json(
                f"{self.base_url}/data/kpi/{kpi}/year/{year}",
                cache_key=f"kolada_{kpi}_{year}",
            )
            for m in payload.get("values", []):
                code = str(m.get("municipality", ""))
                if code not in kommun:
                    continue  # riket "0000" + type-L regions
                for v in m.get("values", []):
                    if v.get("gender") == gender and v.get("value") is not None:
                        rows.append({
                            "geo_code": code,
                            "geo_name": kommun[code],
                            "aar": int(m["period"]),
                            "value": float(v["value"]),
                        })
        if not rows:
            return pd.DataFrame(columns=TIDY_COLUMNS)
        df = pd.DataFrame(rows)
        df["country"] = "SE"
        df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("SE", c))
        df["indicator"] = f"kolada_{kpi}"
        df["gender"] = gender
        logger.info("Kolada %s: %d rows, %d kommuner, years %s",
                    kpi, len(df), df["geo_id"].nunique(),
                    sorted(df["aar"].unique().tolist()))
        return df[TIDY_COLUMNS]
