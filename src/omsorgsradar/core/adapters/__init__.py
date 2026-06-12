"""Dataset adapters.

Each adapter satisfies the :class:`DatasetAdapter` protocol: it knows one API
shape (PxWeb, Sotkanet, CKAN…) and turns a ``[[sources]]`` config block into a
tidy DataFrame. Adapters never analyze; they fetch, cache, and normalize.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

import pandas as pd

from ..config import ConfigError
from .csvfile import CsvAdapter
from .kuhr import KuhrAdapter
from .pxweb import PxWebAdapter
from .socialstyrelsen import SocialstyrelsenAdapter
from .sotkanet import SotkanetAdapter


@runtime_checkable
class DatasetAdapter(Protocol):
    source_id: str

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        """Fetch one configured source and return a tidy DataFrame."""
        ...


# v1 sources keep their bespoke fetchers in ingest._FETCHERS (dispatch by id,
# byte-identical behavior). A test pins this set == set(_FETCHERS).
LEGACY_SOURCE_IDS = frozenset(
    {"kostra_pleie", "befolkning", "framskrivinger", "fhi_nokkel"}
)

REQUIRED_SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "pxweb": ("base_url", "table"),
    "sotkanet": ("indicators", "years"),
    "socialstyrelsen": ("amne", "matt"),
    "kuhr": ("fagomraade", "fomar", "tomar"),
    "csv": ("path", "provenance"),
}


def _make_pxweb(source: Mapping[str, Any], *, cache_dir: Path | None = None, base_dir: Path | None = None) -> PxWebAdapter:
    return PxWebAdapter(base_url=source["base_url"], cache_dir=cache_dir)


def _make_sotkanet(source: Mapping[str, Any], *, cache_dir: Path | None = None, base_dir: Path | None = None) -> SotkanetAdapter:
    return SotkanetAdapter(
        base_url=source.get("base_url", SotkanetAdapter.DEFAULT_BASE_URL),
        cache_dir=cache_dir,
    )


def _make_socialstyrelsen(source: Mapping[str, Any], *, cache_dir: Path | None = None, base_dir: Path | None = None) -> SocialstyrelsenAdapter:
    return SocialstyrelsenAdapter(
        base_url=source.get("base_url", SocialstyrelsenAdapter.DEFAULT_BASE_URL),
        cache_dir=cache_dir,
    )


def _make_kuhr(source: Mapping[str, Any], *, cache_dir: Path | None = None, base_dir: Path | None = None) -> KuhrAdapter:
    return KuhrAdapter(
        base_url=source.get("base_url", KuhrAdapter.DEFAULT_BASE_URL),
        cache_dir=cache_dir,
    )


def _make_csv(source: Mapping[str, Any], *, cache_dir: Path | None = None, base_dir: Path | None = None) -> CsvAdapter:
    return CsvAdapter(base_dir=base_dir)


ADAPTER_FACTORIES = {
    "pxweb": _make_pxweb,
    "sotkanet": _make_sotkanet,
    "socialstyrelsen": _make_socialstyrelsen,
    "kuhr": _make_kuhr,
    "csv": _make_csv,
}


def validate_source(source: Mapping[str, Any]) -> None:
    """Abort at startup with the offending key on bad source blocks (spec rule).

    Legacy v1 ids are exempt — their fetchers own their required keys
    (tests/test_ingest.py pins those).
    """
    sid = source.get("id", "<missing id>")
    if source.get("id") in LEGACY_SOURCE_IDS:
        return
    adapter = source.get("adapter")
    if adapter not in ADAPTER_FACTORIES:
        raise ConfigError(
            f"source '{sid}': unknown adapter '{adapter}' "
            f"(known: {sorted(ADAPTER_FACTORIES)})"
        )
    missing = [f for f in REQUIRED_SOURCE_FIELDS[adapter] if f not in source]
    if missing:
        raise ConfigError(
            f"source '{sid}' (adapter '{adapter}'): missing required field(s) {missing}"
        )
    if adapter == "csv":
        prov = source.get("provenance")
        if (not isinstance(prov, dict) or not prov.get("institution")
                or not prov.get("url")):
            raise ConfigError(
                f"source '{sid}': csv sources require [sources.provenance] "
                "with non-empty institution and url"
            )


def make_adapter(
    source: Mapping[str, Any],
    *,
    cache_dir: Path | None = None,
    base_dir: Path | None = None,
) -> DatasetAdapter:
    validate_source(source)
    return ADAPTER_FACTORIES[source["adapter"]](
        source, cache_dir=cache_dir, base_dir=base_dir
    )
