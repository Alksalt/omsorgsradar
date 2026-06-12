"""Local CSV adapter (downloaded open-data files, Kaggle official re-hosts).

The realness provenance gate has no known-host fallback for local files, so
csv sources MUST carry [sources.provenance] with institution + url — enforced
by validate_source (registry) and re-checked by the profile-stage gates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

logger = logging.getLogger(__name__)


class CsvAdapter:
    source_id = "csv"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else None

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        p = Path(str(source["path"]))
        if not p.is_absolute():
            p = (self.base_dir or Path.cwd()) / p
        if not p.exists():
            raise FileNotFoundError(
                f"csv source '{source.get('id')}': file not found: {p}"
            )
        df = pd.read_csv(
            p,
            sep=str(source.get("sep", ",")),
            encoding=str(source.get("encoding", "utf-8")),
            decimal=str(source.get("decimal", ".")),
            dtype=dict(source.get("dtype", {})) or None,
        )
        rename = dict(source.get("rename", {}))
        if rename:
            df = df.rename(columns=rename)
        logger.info("CSV %s: %d rows, %d columns from %s",
                    source.get("id"), len(df), len(df.columns), p.name)
        return df
