"""PxWeb table API adapter (SSB; later FOHM/DST share the shape).

Extracted verbatim from ingest.py in G0 — behavior-identical: same cache file
naming (``<cache_key|table_id>.json``), same timeouts, same JSON-stat2 parse.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60  # seconds
REQUEST_PAUSE = 0.5   # politeness pause between requests


def jsonstat2_to_df(
    payload: dict[str, Any],
    use_codes: bool = False,
) -> pd.DataFrame:
    """Convert a JSON-stat2 response (SSB PxWebAPI v2 format) to a DataFrame.

    Handles nested ``dimension`` objects and a flat ``value`` list.

    Args:
        payload: Parsed JSON-stat2 dict.
        use_codes: If True, use the raw category codes (e.g. "3101") as cell
            values instead of human-readable labels (e.g. "Halden").
            Default is False (use labels) for backwards compatibility with
            the test fixtures.

    Returns:
        Tidy DataFrame with one column per dimension plus a ``value`` column.

    Raises:
        KeyError: if the payload is missing required JSON-stat2 keys.
    """
    dims = payload["dimension"]
    dim_ids: list[str] = payload["id"]
    dim_sizes: list[int] = payload["size"]
    values: list[float | None] = payload["value"]

    # Build index arrays (cartesian product of dimension categories)
    import itertools

    category_lists = []
    for dim_id, size in zip(dim_ids, dim_sizes):
        cats = dims[dim_id]["category"]
        label_map = cats.get("label", {})
        index_map = cats.get("index", {})
        # Reorder by index position
        if isinstance(index_map, dict):
            ordered = sorted(index_map.items(), key=lambda x: x[1])
            ordered_ids = [k for k, _ in ordered]
        else:
            ordered_ids = list(index_map)
        if use_codes:
            # Keep the raw codes (e.g. "3101", "KOShjtj80aarover0001", "2022")
            category_lists.append(ordered_ids)
        else:
            # Use human-readable labels (e.g. "Halden", "Andel...", "2022")
            labels = [label_map.get(k, k) for k in ordered_ids]
            category_lists.append(labels)

    rows = list(itertools.product(*category_lists))
    df = pd.DataFrame(rows, columns=dim_ids)
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.timeout = timeout

    # ── cache ────────────────────────────────────────────────────────────────
    def _cache_load(self, key: str) -> Any | None:
        if self.cache_dir is None:
            return None
        f = self.cache_dir / f"{key}.json"
        if f.exists():
            logger.debug("Cache hit: %s", f)
            return json.loads(f.read_text(encoding="utf-8"))
        return None

    def _cache_save(self, key: str, data: Any) -> None:
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
        resp = requests.post(url, json=query, timeout=self.timeout)
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
        resp = requests.get(url, params=params, timeout=self.timeout)
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
        return jsonstat2_to_df(payload)
