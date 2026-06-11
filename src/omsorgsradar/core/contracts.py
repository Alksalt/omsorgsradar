"""Stage-boundary contracts: artifact manifests + JSON-schema validation.

Every stage that writes a cross-stage artifact also writes
``<artifact>.manifest.json`` beside it (sha256, schema version, producer,
upstream inputs) and validates the payload against the artifact's schema.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_VERSION = "1"


class ArtifactValidationError(ValueError):
    """An artifact payload does not match its declared schema."""


@dataclass
class ArtifactManifest:
    artifact: str
    path: str
    sha256: str
    schema_version: str
    created_at: str
    producer: str
    inputs: list[str] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_path(artifact_path: Path) -> Path:
    return artifact_path.with_name(artifact_path.name + ".manifest.json")


def write_manifest(
    artifact_path: Path,
    *,
    artifact: str,
    producer: str,
    inputs: list[str] | None = None,
) -> Path:
    manifest = ArtifactManifest(
        artifact=artifact,
        path=str(artifact_path),
        sha256=sha256_of(artifact_path),
        schema_version=SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        producer=producer,
        inputs=list(inputs or []),
    )
    out = _manifest_path(artifact_path)
    out.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def read_manifest(artifact_path: Path) -> ArtifactManifest:
    payload = json.loads(_manifest_path(artifact_path).read_text(encoding="utf-8"))
    return ArtifactManifest(**payload)
