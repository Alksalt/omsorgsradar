"""Socialstyrelsen statistikdatabas (SE) REST adapter.

API shapes verified live 2026-06-12 (docs: sdb.socialstyrelsen.se/sdbapi.aspx):
- topics:  GET {base}            -> [{"namn":"amning","text":…}, …]
- regions: GET {base}/{amne}/region -> [{"id":"0180","kod":"0180","text":"Stockholm"}]
           (4-digit numeric kod = kommun, 2-digit numeric = lan, others = non-standard)
- data:    GET {base}/{amne}/resultat/matt/{id}?per_sida=N&sida=K
           -> {"data":[{"vardformId":"SV","typId":"1","regionId":"0180",
               "alderId":1,"konId":1,"mattId":1,"ar":"1995-1997","varde":"39,3"}],
               "nasta_sida": "http://…sida=2", …}
           regionId is a string; ar is a string (may be a range "YYYY-YYYY");
           varde is a Swedish-locale decimal string ("39,3", "X" = suppressed).
           nasta_sida links are http:// and must be followed as https://.
IMPORTANT 2026-06-12: The API provides NO server-side region/year filtering
(path segments /region/… and /ar/… return 404; query params are ignored).
All filtering is performed client-side after fetching the full dataset.
aar is kept as the raw period string; the generic profiler cannot derive
a numeric year_range for SE — downstream SE consumption is CSV (csv
adapter), which carries integer aar.
NB 2026-06-12: the topic list carries no aldreomsorg topic — Swedish elder-care
data arrives via Socialstyrelsen open-data CSV files (csv adapter) in G2.
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
from .http import safe_request

logger = logging.getLogger(__name__)

TIDY_COLUMNS = [
    "country", "geo_code", "geo_id", "geo_name",
    "aar", "indicator", "typId", "konId", "alderId",
    "value_raw", "value",
]
DEFAULT_PER_PAGE = 1000
DEFAULT_MAX_PAGES = 2000


class SocialstyrelsenAdapter:
    """Adapter for Socialstyrelsen statistikdatabas REST API.

    Fetches full paginated datasets and filters to kommuner client-side.
    Server-side filtering is not supported by the API.

    Args:
        base_url: API base, defaults to the production endpoint.
        cache_dir: Directory for JSON cache files. ``None`` disables caching.
        timeout: HTTP request timeout in seconds.
    """

    source_id = "socialstyrelsen"
    DEFAULT_BASE_URL = "https://sdb.socialstyrelsen.se/api/v1/sv"

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

    def _fetch_all_pages(self, url: str, *, max_pages: int) -> list[dict[str, Any]]:
        """Accumulate ``data`` rows following ``nasta_sida`` (rewritten to https).

        Each ``nasta_sida`` URL is validated via ``safe_request`` which enforces
        host-pinning; cross-host pagination raises ``ConfigError``.

        Args:
            url: Initial request URL.
            max_pages: Hard limit on number of pages to follow. Raises
                ``RuntimeError`` if exceeded while ``nasta_sida`` is still set.

        Returns:
            Flat list of all ``data`` rows across pages.

        Raises:
            RuntimeError: If ``max_pages`` is exceeded before pagination ends.
        """
        rows: list[dict[str, Any]] = []
        page_url: str | None = url
        for _ in range(max_pages):
            if page_url is None:
                return rows
            logger.info("GET %s", page_url)
            resp = safe_request(
                "GET", page_url,
                allowed_hosts=self._allowed_hosts,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows.extend(payload.get("data", []))
            nxt = payload.get("nasta_sida")
            if nxt:
                nxt = nxt.replace("http://", "https://", 1)
                # Validate the nasta_sida host before following — this is a JSON-level
                # pagination link, not an HTTP redirect, so safe_request's hop check
                # does not cover it. Use the same dot-bounded suffix logic.
                from .http import _host_allowed
                nxt_host = (urlparse(nxt).hostname or "").lower()
                if not _host_allowed(nxt_host, self._allowed_hosts):
                    raise RuntimeError(
                        f"socialstyrelsen: nasta_sida host {nxt_host!r} != allowed "
                        f"{sorted(self._allowed_hosts)} — refusing cross-host pagination"
                    )
            page_url = nxt or None
        if page_url is not None:
            raise RuntimeError(
                f"socialstyrelsen: exceeded max_pages={max_pages} at {page_url} — "
                "narrow source scope or raise max_pages in the source block"
            )
        return rows

    def _municipalities(self, amne: str) -> dict[str, str]:
        """Return ``{kod: name}`` for all 4-digit numeric kommuner in *amne*.

        Args:
            amne: Topic name string (e.g. ``skadorochskadehandelserisverigeskommunerochlan``).

        Returns:
            Dict mapping 4-digit string kommune code to municipality name.
        """
        key = f"sst_{amne}_regions"
        regions = self.cache.load(key)
        if regions is None:
            resp = safe_request(
                "GET", f"{self.base_url}/{amne}/region",
                allowed_hosts=self._allowed_hosts,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            regions = resp.json()
            self.cache.save(key, regions)
        return {
            r["kod"]: r["text"]
            for r in regions
            if len(str(r["kod"])) == 4 and str(r["kod"]).isdigit()
        }

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        """Fetch data for *source*, returning a tidy DataFrame of kommuner rows.

        Filters non-kommuner rows (riket, lan) client-side. Optionally filters
        to a specific set of year strings (``years`` key in source).

        Note:
            The Socialstyrelsen API does not support server-side filtering. The
            full paginated dataset is retrieved and filtered locally. Use ``years``
            to restrict output post-fetch (not to reduce network traffic).

        Args:
            source: Source config dict. Required keys: ``amne``, ``matt``.
                Optional: ``years`` (list of year strings to keep, e.g.
                ``["1995-1997"]``), ``per_sida`` (page size), ``max_pages``.

        Returns:
            Tidy DataFrame with columns defined in ``TIDY_COLUMNS``.
        """
        amne = source["amne"]
        matt = int(source["matt"])
        years = [str(y) for y in source.get("years", [])]
        kommun = self._municipalities(amne)

        key = f"sst_{amne}_m{matt}"
        rows = self.cache.load(key)
        if rows is None:
            url = (
                f"{self.base_url}/{amne}/resultat/matt/{matt}"
                f"?per_sida={int(source.get('per_sida', DEFAULT_PER_PAGE))}"
            )
            rows = self._fetch_all_pages(
                url, max_pages=int(source.get("max_pages", DEFAULT_MAX_PAGES))
            )
            self.cache.save(key, rows)

        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=TIDY_COLUMNS)

        # Filter to kommunnivå only (4-digit numeric regionId)
        df = df[df["regionId"].apply(
            lambda r: len(str(r)) == 4 and str(r).isdigit()
        )].copy()
        df = df[df["regionId"].isin(kommun)].copy()

        # Optional year filter (client-side)
        if years:
            df = df[df["ar"].isin(years)].copy()

        if df.empty:
            return pd.DataFrame(columns=TIDY_COLUMNS)

        df["geo_code"] = df["regionId"].astype(str)
        df["geo_name"] = df["geo_code"].map(kommun)
        df["geo_id"] = df["geo_code"].map(lambda c: make_geo_id("SE", c))
        df["aar"] = df["ar"]  # preserve original string (may be "YYYY-YYYY")
        df["indicator"] = f"{amne}_matt{matt}"
        df["country"] = "SE"
        df["value_raw"] = df["varde"]
        # Convert Swedish decimal strings ("39,3") to float; "X"/".." -> NaN
        df["value"] = pd.to_numeric(
            df["varde"].str.replace(",", ".", regex=False), errors="coerce"
        )

        logger.info(
            "Socialstyrelsen %s matt=%d: %d kommuner rows, %d kommuner",
            amne, matt, len(df), df["geo_id"].nunique(),
        )
        return df[TIDY_COLUMNS].reset_index(drop=True)
