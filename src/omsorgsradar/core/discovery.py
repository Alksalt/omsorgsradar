"""Pointer classification for the agentic shell (/magic-analyze).

The shell calls :func:`classify_pointer` to decide its first move. This is
pure string/filesystem logic — the engine never fetches anything here, and
free-text questions are resolved by the shell against
``docs/dataset-registry.md``, not by code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Hosts a generic adapter fully handles. (FHI is intentionally absent: its
# NOKKEL fetcher is legacy-id-only, not a generic adapter.)
HOST_ADAPTERS: dict[str, str] = {
    "data.ssb.no": "pxweb",
    "api.scb.se": "pxweb",
    "sotkanet.fi": "sotkanet",
    "api.kolada.se": "kolada",
    "sdb.socialstyrelsen.se": "socialstyrelsen",
    "opne-data-api.helserefusjon.no": "kuhr",
}

_FILE_SUFFIXES = (".csv", ".tsv")


@dataclass(frozen=True)
class Pointer:
    kind: str            # "url" | "file" | "question"
    adapter: str | None  # adapter name when known (url/file)
    host: str | None     # netloc for url pointers


def classify_pointer(pointer: str, *, base_dir: Path | str | None = None) -> Pointer:
    s = pointer.strip()
    if s.startswith(("http://", "https://")):
        host = urlparse(s).netloc.lower()
        adapter = next(
            (a for h, a in HOST_ADAPTERS.items()
             if host == h or host.endswith("." + h)),
            None,
        )
        return Pointer("url", adapter, host)
    p = Path(s)
    candidates = [p]
    if base_dir is not None and not p.is_absolute():
        candidates.append(Path(base_dir) / s)
    if s.lower().endswith(_FILE_SUFFIXES) or any(c.exists() for c in candidates):
        return Pointer("file", "csv", None)
    return Pointer("question", None, None)
