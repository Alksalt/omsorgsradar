"""Local CSV adapter (downloaded open-data files, Kaggle official re-hosts).

The realness provenance gate has no known-host fallback for local files, so
csv sources MUST carry [sources.provenance] with institution + url — enforced
by validate_source (registry) and re-checked by the profile-stage gates.

Paths are contained: relative paths resolve inside the analysis dir, and any
path (absolute or ``../``) that resolves outside it is rejected — the G3
security gate for machine-authored configs. ``resolve()`` also neutralizes
symlink escapes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..config import ConfigError

logger = logging.getLogger(__name__)


class CsvAdapter:
    source_id = "csv"

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else None

    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        if self.base_dir is None:
            raise ConfigError(
                f"csv source '{source.get('id')}': base_dir is required for path "
                "containment — construct CsvAdapter with the analysis dir"
            )
        base = self.base_dir.resolve()
        raw = Path(str(source["path"]))
        p = (raw if raw.is_absolute() else base / raw).resolve()
        if not p.is_relative_to(base):
            raise ConfigError(
                f"csv source '{source.get('id')}': path escapes the analysis dir: "
                f"{p} (base: {base})"
            )
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
