"""PxWeb table API adapter (SSB; later FOHM/DST share the shape).

Extracted verbatim from ingest.py in G0 — behavior-identical: same cache file
naming (``<cache_key|table_id>.json``), same timeouts, same JSON-stat2 parse.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests

from .cache import JsonCache
from .http import safe_request

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60  # seconds
REQUEST_PAUSE = 0.5   # politeness pause between requests


def jsonstat2_to_df(
    payload: dict[str, Any],
    use_codes: bool = False,
    label_columns: bool = False,
) -> pd.DataFrame:
    """Convert a JSON-stat2 response (SSB PxWebAPI v2 format) to a DataFrame.

    Handles nested ``dimension`` objects and a flat ``value`` list.

    Args:
        payload: Parsed JSON-stat2 dict.
        use_codes: If True, use the raw category codes (e.g. "3101") as cell
            values instead of human-readable labels (e.g. "Halden").
            Default is False (use labels) for backwards compatibility with
            the test fixtures.
        label_columns: If True, emit additional ``<dim>_label`` columns
            alongside each dimension column. Useful when ``use_codes=True``
            and you still want human-readable labels available. Default False.

    Returns:
        Tidy DataFrame with one column per dimension plus a ``value`` column.
        If ``label_columns=True``, each dimension also has a ``<dim>_label``
        column containing human-readable labels.

    Raises:
        KeyError: if the payload is missing required JSON-stat2 keys.
    """
    dims = payload["dimension"]
    dim_ids: list[str] = payload["id"]
    dim_sizes: list[int] = payload["size"]
    values: list[float | None] = payload["value"]

    import itertools

    code_lists: list[list[str]] = []
    label_lists: list[list[str]] = []
    for dim_id, size in zip(dim_ids, dim_sizes):
        cats = dims[dim_id]["category"]
        label_map = cats.get("label", {})
        index_map = cats.get("index", {})
        if isinstance(index_map, dict):
            ordered = sorted(index_map.items(), key=lambda x: x[1])
            ordered_ids = [k for k, _ in ordered]
        else:
            ordered_ids = list(index_map)
        code_lists.append(ordered_ids)
        label_lists.append([label_map.get(k, k) for k in ordered_ids])

    main_lists = code_lists if use_codes else label_lists
    rows = list(itertools.product(*main_lists))
    df = pd.DataFrame(rows, columns=dim_ids)
    if label_columns:
        label_rows = list(itertools.product(*label_lists))
        for i, dim_id in enumerate(dim_ids):
            df[f"{dim_id}_label"] = [r[i] for r in label_rows]
    df["value"] = values
    return df


class PxWebAdapter:
    """POST JSON queries to a PxWeb table endpoint, with raw-JSON disk cache."""

    source_id = "pxweb"

    def __init__(
        self,
        base_url: str,
        cache_dir: Path | None = None,
        timeout: int = REQUEST_TIMEOUT,
        allowed_hosts: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache = JsonCache(cache_dir)
        self.timeout = timeout
        # Pin redirect validation to the adapter's own base host by default.
        from urllib.parse import urlparse as _urlparse
        if allowed_hosts is not None:
            self._allowed_hosts: frozenset[str] = frozenset(allowed_hosts)
        else:
            host = (_urlparse(base_url).hostname or "").lower()
            self._allowed_hosts = frozenset({host} if host else set())

    # ── cache ────────────────────────────────────────────────────────────────
    def _cache_load(self, key: str) -> Any | None:
        return self.cache.load(key)

    def _cache_save(self, key: str, data: Any) -> None:
        self.cache.save(key, data)

    # ── HTTP ─────────────────────────────────────────────────────────────────
    def post_table(
        self, table_id: str, query: dict[str, Any], cache_key: str | None = None
    ) -> dict[str, Any]:
        """Behavior-identical replacement for ingest._post_px."""
        key = cache_key or table_id
        cached = self._cache_load(key)
        if cached is not None:
            return cached
        url = f"{self.base_url}/{table_id}"
        logger.info("POST %s", url)
        resp = safe_request(
            "POST", url,
            allowed_hosts=self._allowed_hosts,
            json=query,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._cache_save(key, data)
        return data

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        cache_key: str | None = None,
    ) -> Any:
        """Behavior-identical replacement for ingest._get_json."""
        if cache_key is not None:
            cached = self._cache_load(cache_key)
            if cached is not None:
                return cached
        logger.info("GET %s", url)
        resp = safe_request(
            "GET", url,
            allowed_hosts=self._allowed_hosts,
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if cache_key is not None:
            self._cache_save(cache_key, data)
        return data

    # ── DatasetAdapter protocol ─────────────────────────────────────────────
    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        """Minimal protocol implementation (G1 extends per-source queries)."""
        payload = self.post_table(
            str(source["table"]),
            query=dict(source.get("query", {"query": []})),
            cache_key=source.get("cache_key"),
        )
        return jsonstat2_to_df(
            payload,
            use_codes=bool(source.get("use_codes", False)),
            label_columns=bool(source.get("label_columns", False)),
        )
