"""Shared raw-JSON disk cache for adapters.

Cache keys are restricted to ``[A-Za-z0-9._-]`` with no ``..`` so a
machine-authored config can never traverse out of the cache directory
(security flag 2026-06-11, partially landed here ahead of G3).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60  # seconds, shared by all HTTP adapters

_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class CacheKeyError(ValueError):
    """Cache key contains path separators, '..', or other unsafe characters."""


class JsonCache:
    """Raw JSON to ``<cache_dir>/<key>.json``; ``cache_dir=None`` disables."""

    def __init__(self, cache_dir: Path | str | None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None

    @staticmethod
    def check_key(key: str) -> str:
        if not _KEY_RE.match(key) or ".." in key:
            raise CacheKeyError(
                f"unsafe cache key {key!r} — allowed: letters, digits, '.', '_', '-'"
            )
        return key

    def load(self, key: str) -> Any | None:
        self.check_key(key)
        if self.cache_dir is None:
            return None
        f = self.cache_dir / f"{key}.json"
        if f.exists():
            logger.debug("Cache hit: %s", f)
            return json.loads(f.read_text(encoding="utf-8"))
        return None

    def save(self, key: str, data: Any) -> None:
        self.check_key(key)
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
