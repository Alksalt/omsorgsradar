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


FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["kommuner", "analysis_year_range"],
    "properties": {
        "kommuner": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["knr", "rank", "press_index_norm"],
                "properties": {
                    "knr": {"type": "string"},
                    "rank": {"type": "integer"},
                    "press_index_norm": {"type": ["number", "null"]},
                },
            },
        },
        # result_to_dict persists this as a [start, end] pair; reports may
        # render it as a "start-end" string — both are valid on disk.
        "analysis_year_range": {
            "oneOf": [
                {"type": "string"},
                {
                    "type": "array",
                    "items": {"type": ["integer", "number"]},
                    "minItems": 2,
                    "maxItems": 2,
                },
            ]
        },
    },
}

QUALITY_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["datasets"],
    "properties": {
        "datasets": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "realness": {
                        "type": "object",
                        "required": ["verdict", "checks"],
                        "properties": {
                            "verdict": {"enum": ["PASS", "WARN", "FAIL", "SKIP"]},
                            "checks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["name", "status"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "status": {
                                            "enum": ["PASS", "WARN", "FAIL", "SKIP"]
                                        },
                                        "detail": {"type": "string"},
                                    },
                                },
                            },
                        },
                    }
                },
            },
        }
    },
}

VERIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["verdict", "total_claims", "passed", "failed"],
    "properties": {
        "verdict": {"enum": ["PASS", "FAIL"]},
        "total_claims": {"type": "integer"},
        "passed": {"type": "integer"},
        "failed": {"type": "integer"},
        "failures": {"type": "array", "items": {"type": "string"}},
    },
}

SCHEMAS: dict[str, dict[str, Any]] = {
    "findings": FINDINGS_SCHEMA,
    "quality_profile": QUALITY_PROFILE_SCHEMA,
    "verification": VERIFICATION_SCHEMA,
}


def register_schema(name: str, schema: dict[str, Any]) -> None:
    """Register an artifact schema (instance extension point).

    ``analyses/<name>/stages.py`` registers schemas for its custom artifacts so
    they flow through the same ``validate_artifact`` path as core artifacts.
    Re-registering the identical schema is a no-op (extension modules are
    re-imported on every pipeline run); a conflicting redefinition raises.
    """
    if name in SCHEMAS:
        if SCHEMAS[name] == schema:
            return
        raise ValueError(f"artifact schema '{name}' already registered with a different definition")
    SCHEMAS[name] = schema


def validate_artifact(name: str, payload: dict[str, Any]) -> None:
    """Validate an artifact payload against its registered schema.

    The payload is round-tripped through JSON first so what gets validated is
    exactly what persists on disk (tuples become arrays). NaN is allowed to
    match the writers' json.dumps defaults — quality profiles legitimately
    carry NaN for missing series (tightening this is a G2 concern).

    Raises:
        ArtifactValidationError: unknown artifact name, payload not
            JSON-serializable, or schema mismatch.
    """
    schema = SCHEMAS.get(name)
    if schema is None:
        raise ArtifactValidationError(
            f"unknown artifact '{name}' (known: {sorted(SCHEMAS)})"
        )
    try:
        payload = json.loads(json.dumps(payload))
    except (TypeError, ValueError) as exc:
        raise ArtifactValidationError(
            f"artifact '{name}' is not JSON-serializable: {exc}"
        ) from exc
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        loc = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise ArtifactValidationError(
            f"artifact '{name}' invalid at '{loc}': {exc.message}"
        ) from exc
