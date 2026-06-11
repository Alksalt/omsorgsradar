"""Dataset adapters.

Each adapter satisfies the :class:`DatasetAdapter` protocol: it knows one API
shape (PxWeb, Sotkanet, CKAN…) and turns a ``[[sources]]`` config block into a
tidy DataFrame. Adapters never analyze; they fetch, cache, and normalize.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class DatasetAdapter(Protocol):
    source_id: str

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        """Fetch one configured source and return a tidy DataFrame."""
        ...
