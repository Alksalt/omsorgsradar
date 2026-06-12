"""Config loading + validation for the workflow engine.

Two layers: ``workflow.toml`` (global HOW: models, endpoint, defaults) and
``analyses/<name>/analysis.toml`` (WHAT: question, stages, sources, params).
Precedence: analysis > workflow defaults > code default. Structural validation
is JSON-schema at load time; semantic checks (known adapters/stages) happen at
registry/adapter resolution with their own clear errors.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema


class ConfigError(ValueError):
    """A config file is missing, malformed, or fails schema validation."""


ENDPOINT_MODES = ["subscription", "api", "local"]

WORKFLOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["endpoint"],
    "properties": {
        "models": {"type": "object", "additionalProperties": {"type": "string"}},
        "endpoint": {
            "type": "object",
            "required": ["mode"],
            "properties": {
                "mode": {"enum": ENDPOINT_MODES},
                "api": {
                    "type": "object",
                    "properties": {
                        "provider": {"enum": ["anthropic", "openai", "openrouter"]}
                    },
                },
                "local": {
                    "type": "object",
                    "properties": {"base_url": {"type": "string"}},
                },
            },
        },
        "defaults": {
            "type": "object",
            "properties": {
                "language": {"type": "string"},
                "figure_style": {"type": "string"},
                "runs_dir": {"type": "string"},
            },
        },
        "security": {
            "type": "object",
            "properties": {
                "extra_allowed_hosts": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
        },
    },
}

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["analysis", "stages"],
    "properties": {
        "analysis": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
                "question": {"type": "string"},
                "language": {"type": "string"},
            },
        },
        "stages": {
            "type": "object",
            "required": ["list"],
            "properties": {
                "list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["adapter", "id"],
                "properties": {
                    "adapter": {"type": "string"},
                    # id becomes a DuckDB table name + cache-key fragment —
                    # pattern-locked so config can never inject SQL/paths.
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                },
            },
        },
        "params": {"type": "object"},
    },
}


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc


def _validate(payload: dict[str, Any], schema: dict[str, Any], path: Path) -> None:
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        loc = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise ConfigError(f"{path}: invalid config at '{loc}': {exc.message}") from exc


def load_workflow_config(path: Path) -> dict[str, Any]:
    payload = _load_toml(path)
    _validate(payload, WORKFLOW_SCHEMA, path)
    return payload


def load_analysis_config(path: Path) -> dict[str, Any]:
    payload = _load_toml(path)
    _validate(payload, ANALYSIS_SCHEMA, path)
    return payload


@dataclass
class RunConfig:
    """Merged view over one analysis + the global workflow config."""

    workflow: dict[str, Any]
    analysis: dict[str, Any]
    analysis_dir: Path

    @property
    def name(self) -> str:
        return self.analysis["analysis"]["name"]

    @property
    def stage_list(self) -> list[str]:
        return list(self.analysis["stages"]["list"])

    @property
    def sources(self) -> list[dict[str, Any]]:
        return list(self.analysis.get("sources", []))

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.analysis.get("params", {}))

    def setting(self, *keys: str, default: Any = None) -> Any:
        """Resolve a setting: nested analysis lookup, then workflow
        ``[defaults]`` by the last key, then the code default."""
        node: Any = self.analysis
        for k in keys:
            node = node.get(k) if isinstance(node, dict) else None
        if node is not None:
            return node
        defaults = self.workflow.get("defaults", {})
        value = defaults.get(keys[-1]) if isinstance(defaults, dict) else None
        return value if value is not None else default


def load_run_config(analysis_dir: Path | str, workflow_path: Path | str) -> RunConfig:
    analysis_dir = Path(analysis_dir)
    return RunConfig(
        workflow=load_workflow_config(Path(workflow_path)),
        analysis=load_analysis_config(analysis_dir / "analysis.toml"),
        analysis_dir=analysis_dir,
    )
