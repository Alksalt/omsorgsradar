# G0 — Engine + Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a reusable, config-driven engine from the shipped omsorgsradar pipeline — stage registry with instance extension point, validated workflow/analysis TOML config, artifact manifests, run journal, verify-gate, data-read hook — with all 65 existing tests staying green.

**Architecture:** Deterministic engine + agentic shell (spec: `docs/specs/2026-06-11-v2-generalization-design.md`). G0 builds the engine half: `core/` (config, contracts, journal, registry, adapters) + `analyses/omsorgsradar/` as the first instance. No new analyses, no skills logic beyond scaffolds, no behavior change to computed numbers.

**Tech Stack:** Python 3.11+ via `uv`, pandas, duckdb, `jsonschema` (new dep), `tomllib` (stdlib), pytest.

**Conventions for the implementer:**
- Run everything with `uv run …` — never bare `python`/`pip`.
- After every task: `uv run pytest -x -q` must pass before committing.
- Existing public function names that tests import (`jsonstat2_to_df`, `run_ingest`, fetchers) keep working — via re-exports or updated call sites *in this plan*.
- Repo root is the working directory for all commands.

---

### Task 1: Dependency + package skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `src/omsorgsradar/core/__init__.py`, `src/omsorgsradar/core/adapters/__init__.py` (placeholder docstrings), `tests/core/__init__.py`

- [ ] **Step 1: Add jsonschema dependency**

Run: `uv add "jsonschema>=4.23"`
Expected: `pyproject.toml` gains `"jsonschema>=4.23"` under `[project] dependencies`, `uv.lock` updated.

- [ ] **Step 2: Create package skeleton**

```bash
mkdir -p src/omsorgsradar/core/adapters tests/core
```

`src/omsorgsradar/core/__init__.py`:
```python
"""Reusable engine: config, contracts, journal, stage registry, adapters."""
```

`src/omsorgsradar/core/adapters/__init__.py`:
```python
"""Dataset adapters. Each adapter satisfies the DatasetAdapter protocol."""
```

`tests/core/__init__.py`: empty file.

- [ ] **Step 3: Verify nothing broke**

Run: `uv run pytest -x -q`
Expected: 65 passed.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock src/omsorgsradar/core tests/core
git commit -m "G0: add jsonschema dep + core package skeleton"
```

---

### Task 2: Config loader with schema validation (`core/config.py`)

**Files:**
- Create: `src/omsorgsradar/core/config.py`
- Test: `tests/core/test_config.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_config.py`:
```python
"""Config loading + validation — workflow.toml and analysis.toml."""

from pathlib import Path

import pytest

from omsorgsradar.core.config import (
    ConfigError,
    RunConfig,
    load_analysis_config,
    load_run_config,
    load_workflow_config,
)

VALID_WORKFLOW = """
[models]
report = "claude-fable-5"

[endpoint]
mode = "subscription"

[defaults]
language = "nb"
runs_dir = "runs"
"""

VALID_ANALYSIS = """
[analysis]
name = "testanalyse"
language = "en"

[stages]
list = ["profile", "analyze"]

[[sources]]
adapter = "pxweb"
id = "kostra_pleie"
base_url = "https://example.invalid/api"
table = "12209"
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestWorkflowConfig:
    def test_valid_loads(self, tmp_path: Path) -> None:
        cfg = load_workflow_config(_write(tmp_path, "workflow.toml", VALID_WORKFLOW))
        assert cfg["endpoint"]["mode"] == "subscription"

    def test_bad_mode_rejected(self, tmp_path: Path) -> None:
        bad = VALID_WORKFLOW.replace('"subscription"', '"telepathy"')
        with pytest.raises(ConfigError, match="endpoint/mode"):
            load_workflow_config(_write(tmp_path, "workflow.toml", bad))

    def test_missing_file_clear_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_workflow_config(tmp_path / "nope.toml")


class TestAnalysisConfig:
    def test_valid_loads(self, tmp_path: Path) -> None:
        cfg = load_analysis_config(_write(tmp_path, "analysis.toml", VALID_ANALYSIS))
        assert cfg["analysis"]["name"] == "testanalyse"

    def test_missing_name_rejected(self, tmp_path: Path) -> None:
        bad = VALID_ANALYSIS.replace('name = "testanalyse"\n', "")
        with pytest.raises(ConfigError, match="analysis"):
            load_analysis_config(_write(tmp_path, "analysis.toml", bad))

    def test_empty_stage_list_rejected(self, tmp_path: Path) -> None:
        bad = VALID_ANALYSIS.replace('list = ["profile", "analyze"]', "list = []")
        with pytest.raises(ConfigError, match="stages"):
            load_analysis_config(_write(tmp_path, "analysis.toml", bad))

    def test_source_without_adapter_rejected(self, tmp_path: Path) -> None:
        bad = VALID_ANALYSIS.replace('adapter = "pxweb"\n', "")
        with pytest.raises(ConfigError, match="adapter"):
            load_analysis_config(_write(tmp_path, "analysis.toml", bad))


class TestRunConfig:
    def _cfg(self, tmp_path: Path) -> RunConfig:
        adir = tmp_path / "analyses" / "testanalyse"
        adir.mkdir(parents=True)
        (adir / "analysis.toml").write_text(VALID_ANALYSIS, encoding="utf-8")
        wf = _write(tmp_path, "workflow.toml", VALID_WORKFLOW)
        return load_run_config(adir, wf)

    def test_accessors(self, tmp_path: Path) -> None:
        cfg = self._cfg(tmp_path)
        assert cfg.name == "testanalyse"
        assert cfg.stage_list == ["profile", "analyze"]
        assert cfg.sources[0]["table"] == "12209"

    def test_setting_precedence_analysis_wins(self, tmp_path: Path) -> None:
        cfg = self._cfg(tmp_path)
        # analysis.toml says "en", workflow default says "nb"
        assert cfg.setting("analysis", "language", default="xx") == "en"

    def test_setting_falls_back_to_workflow_default(self, tmp_path: Path) -> None:
        cfg = self._cfg(tmp_path)
        assert cfg.setting("analysis", "runs_dir", default="xx") == "runs"

    def test_setting_falls_back_to_code_default(self, tmp_path: Path) -> None:
        cfg = self._cfg(tmp_path)
        assert cfg.setting("analysis", "nonexistent_key", default="fallback") == "fallback"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'omsorgsradar.core.config'`

- [ ] **Step 3: Implement `core/config.py`**

```python
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
                    "id": {"type": "string"},
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_config.py -q`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/omsorgsradar/core/config.py tests/core/test_config.py
git commit -m "G0: config loader with JSON-schema validation + precedence"
```

---

### Task 3: Canonical config files (`workflow.toml`, `analyses/omsorgsradar/analysis.toml`)

**Files:**
- Create: `workflow.toml`, `analyses/omsorgsradar/analysis.toml`
- Test: `tests/core/test_config.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/core/test_config.py`)**

```python
REPO_ROOT = Path(__file__).resolve().parents[2]


class TestCanonicalConfigs:
    """The committed config files must always validate."""

    def test_workflow_toml_valid(self) -> None:
        cfg = load_workflow_config(REPO_ROOT / "workflow.toml")
        assert cfg["endpoint"]["mode"] in ("subscription", "api", "local")

    def test_omsorgsradar_analysis_valid(self) -> None:
        cfg = load_run_config(
            REPO_ROOT / "analyses" / "omsorgsradar", REPO_ROOT / "workflow.toml"
        )
        assert cfg.name == "omsorgsradar"
        assert cfg.stage_list[0] == "ingest"
        ids = [s["id"] for s in cfg.sources]
        assert ids == ["kostra_pleie", "befolkning", "framskrivinger", "fhi_nokkel"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/core/test_config.py -q -k Canonical`
Expected: FAIL — `ConfigError: Config file not found: …/workflow.toml`

- [ ] **Step 3: Create `workflow.toml` (repo root)**

```toml
# Global workflow config — HOW the pipeline runs. Per-analysis settings in
# analyses/<name>/analysis.toml override [defaults] here.

[models]
profile = "claude-sonnet-4-6"
report = "claude-fable-5"

[endpoint]
mode = "subscription"   # subscription | api | local

[endpoint.api]
provider = "anthropic"  # anthropic | openai | openrouter

[endpoint.local]
base_url = "http://localhost:1234"

[defaults]
language = "nb"
figure_style = "seaborn-v0_8-whitegrid"
runs_dir = "runs"
```

- [ ] **Step 4: Create `analyses/omsorgsradar/analysis.toml`**

```toml
[analysis]
name = "omsorgsradar"
question = "Hvilke kommuner får den hardeste skvisen mellom aldrende befolkning og dagens omsorgskapasitet fram mot 2035?"
language = "nb"

[stages]
list = ["ingest", "profile", "analyze", "verify", "report", "ml"]

[[sources]]
adapter = "pxweb"
id = "kostra_pleie"
base_url = "https://data.ssb.no/api/v0/no/table"
table = "12209"

[sources.var_map]
hjemmetjeneste_andel = "KOShjtj80aarover0001"
institusjon_andel = "KOSsykhjand80aar0000"
aarsverk_per_bruker = "KOSaarsvbrukerom0000"
utgifter_per_innbygger = "KOSbduFKG9innbyg0000"

[[sources]]
adapter = "pxweb"
id = "befolkning"
base_url = "https://data.ssb.no/api/v0/no/table"
table = "07459"

[[sources]]
adapter = "pxweb"
id = "framskrivinger"
base_url = "https://data.ssb.no/api/v0/no/table"
table = "12880"

[[sources]]
adapter = "fhi"
id = "fhi_nokkel"
base_url = "https://statistikk-data.fhi.no/api/open/v1"
source = "nokkel"

[params]
projection_year = 2035
```

- [ ] **Step 5: Run tests, then commit**

Run: `uv run pytest tests/core/test_config.py -q`
Expected: 13 passed.

```bash
git add workflow.toml analyses/omsorgsradar/analysis.toml tests/core/test_config.py
git commit -m "G0: canonical workflow.toml + omsorgsradar analysis.toml"
```

---

### Task 4: Artifact manifests (`core/contracts.py`, part 1)

**Files:**
- Create: `src/omsorgsradar/core/contracts.py`
- Test: `tests/core/test_contracts.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_contracts.py`:
```python
"""Artifact manifests + schema validation at stage boundaries."""

import json
from pathlib import Path

import pytest

from omsorgsradar.core.contracts import (
    ArtifactValidationError,
    read_manifest,
    sha256_of,
    validate_artifact,
    write_manifest,
)


@pytest.fixture()
def artifact(tmp_path: Path) -> Path:
    p = tmp_path / "findings.json"
    p.write_text('{"hello": 1}', encoding="utf-8")
    return p


class TestManifest:
    def test_roundtrip(self, artifact: Path) -> None:
        mpath = write_manifest(
            artifact, artifact="findings", producer="analyze", inputs=["data/x.json"]
        )
        assert mpath.name == "findings.json.manifest.json"
        m = read_manifest(artifact)
        assert m.artifact == "findings"
        assert m.producer == "analyze"
        assert m.inputs == ["data/x.json"]
        assert m.sha256 == sha256_of(artifact)
        assert m.created_at.endswith("+00:00") or m.created_at.endswith("Z")

    def test_hash_changes_with_content(self, artifact: Path) -> None:
        h1 = sha256_of(artifact)
        artifact.write_text('{"hello": 2}', encoding="utf-8")
        assert sha256_of(artifact) != h1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/core/test_contracts.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement manifests in `core/contracts.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass, then commit**

Run: `uv run pytest tests/core/test_contracts.py -q`
Expected: 2 passed.

```bash
git add src/omsorgsradar/core/contracts.py tests/core/test_contracts.py
git commit -m "G0: artifact manifests with sha256 + producer lineage"
```

---

### Task 5: Artifact schemas + `validate_artifact` (`core/contracts.py`, part 2)

**Files:**
- Modify: `src/omsorgsradar/core/contracts.py`
- Test: `tests/core/test_contracts.py` (append)

- [ ] **Step 1: Write the failing tests (append)**

```python
VALID_FINDINGS = {
    "kommuner": [
        {"knr": "1505", "rank": 1, "press_index_norm": 0.91},
        {"knr": "0301", "rank": 2, "press_index_norm": 0.77},
    ],
    "analysis_year_range": "2007-2024",
}

VALID_QUALITY = {"datasets": {"kostra_pleie": {"rows": 100}}}

VALID_VERIFICATION = {
    "verdict": "PASS",
    "total_claims": 5,
    "passed": 5,
    "failed": 0,
    "failures": [],
}


class TestValidateArtifact:
    def test_valid_payloads_pass(self) -> None:
        validate_artifact("findings", VALID_FINDINGS)
        validate_artifact("quality_profile", VALID_QUALITY)
        validate_artifact("verification", VALID_VERIFICATION)

    def test_findings_missing_kommuner_fails(self) -> None:
        with pytest.raises(ArtifactValidationError, match="kommuner"):
            validate_artifact("findings", {"analysis_year_range": "x"})

    def test_verification_bad_verdict_fails(self) -> None:
        bad = dict(VALID_VERIFICATION, verdict="MAYBE")
        with pytest.raises(ArtifactValidationError, match="verdict"):
            validate_artifact("verification", bad)

    def test_unknown_artifact_name_fails(self) -> None:
        with pytest.raises(ArtifactValidationError, match="unknown artifact"):
            validate_artifact("blob", {})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/core/test_contracts.py -q -k Validate`
Expected: FAIL — `ImportError` / `NameError` for the new names is already covered; failures show `validate_artifact` cases failing.

- [ ] **Step 3: Append schemas + validator to `core/contracts.py`**

```python
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
        "analysis_year_range": {"type": "string"},
    },
}

QUALITY_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["datasets"],
    "properties": {"datasets": {"type": "object"}},
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


def validate_artifact(name: str, payload: dict[str, Any]) -> None:
    """Validate an artifact payload against its registered schema.

    Raises:
        ArtifactValidationError: unknown artifact name or schema mismatch.
    """
    schema = SCHEMAS.get(name)
    if schema is None:
        raise ArtifactValidationError(
            f"unknown artifact '{name}' (known: {sorted(SCHEMAS)})"
        )
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        loc = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise ArtifactValidationError(
            f"artifact '{name}' invalid at '{loc}': {exc.message}"
        ) from exc
```

- [ ] **Step 4: Run tests to verify they pass, then commit**

Run: `uv run pytest tests/core/test_contracts.py -q`
Expected: 6 passed.

```bash
git add src/omsorgsradar/core/contracts.py tests/core/test_contracts.py
git commit -m "G0: artifact schemas (findings, quality_profile, verification) + validator"
```

---

### Task 6: Run journal (`core/journal.py`)

**Files:**
- Create: `src/omsorgsradar/core/journal.py`
- Test: `tests/core/test_journal.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_journal.py`:
```python
"""Run journal — crash-safe per-run record of stages, artifacts, status."""

import json
from pathlib import Path

from omsorgsradar.core.journal import RunJournal


class TestRunJournal:
    def test_start_creates_run_json(self, tmp_path: Path) -> None:
        j = RunJournal.start(tmp_path, analysis="omsorgsradar")
        run_json = j.run_dir / "run.json"
        assert run_json.exists()
        rec = json.loads(run_json.read_text(encoding="utf-8"))
        assert rec["analysis"] == "omsorgsradar"
        assert rec["status"] == "running"
        assert rec["run_id"].endswith("-omsorgsradar")

    def test_record_stage_flushes_immediately(self, tmp_path: Path) -> None:
        j = RunJournal.start(tmp_path, analysis="x")
        j.record_stage("profile", artifacts=["data/quality_profile.json"],
                       meta={"rows": 7}, duration_s=0.12)
        rec = json.loads((j.run_dir / "run.json").read_text(encoding="utf-8"))
        assert rec["stages"][0]["stage"] == "profile"
        assert rec["stages"][0]["artifacts"] == ["data/quality_profile.json"]
        assert rec["stages"][0]["meta"] == {"rows": 7}

    def test_finalize_sets_status(self, tmp_path: Path) -> None:
        j = RunJournal.start(tmp_path, analysis="x")
        j.finalize("gate_failed")
        rec = json.loads((j.run_dir / "run.json").read_text(encoding="utf-8"))
        assert rec["status"] == "gate_failed"
        assert "finished_at" in rec

    def test_config_snapshot_stored(self, tmp_path: Path) -> None:
        j = RunJournal.start(tmp_path, analysis="x", config_snapshot={"stages": ["a"]})
        rec = json.loads((j.run_dir / "run.json").read_text(encoding="utf-8"))
        assert rec["config"] == {"stages": ["a"]}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/core/test_journal.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `core/journal.py`**

```python
"""Per-run journal: ``runs/<run-id>/run.json``.

Flushed after every mutation so a crashed run still leaves a readable record.
File-based by design (see DECISIONS.md — no vector/graph memory).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunJournal:
    run_dir: Path
    record: dict[str, Any]

    @classmethod
    def start(
        cls,
        runs_dir: Path,
        *,
        analysis: str,
        config_snapshot: dict[str, Any] | None = None,
    ) -> "RunJournal":
        run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")[:-4]
            + "Z-"
            + analysis
        ).replace("ZZ-", "Z-")
        run_dir = Path(runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "run_id": run_id,
            "analysis": analysis,
            "started_at": _utcnow(),
            "status": "running",
            "config": config_snapshot or {},
            "stages": [],
        }
        journal = cls(run_dir=run_dir, record=record)
        journal._flush()
        return journal

    def record_stage(
        self,
        stage: str,
        *,
        artifacts: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        duration_s: float | None = None,
    ) -> None:
        self.record["stages"].append(
            {
                "stage": stage,
                "finished_at": _utcnow(),
                "duration_s": duration_s,
                "artifacts": list(artifacts or []),
                "meta": meta or {},
            }
        )
        self._flush()

    def finalize(self, status: str = "ok") -> None:
        self.record["status"] = status
        self.record["finished_at"] = _utcnow()
        self._flush()

    def _flush(self) -> None:
        (self.run_dir / "run.json").write_text(
            json.dumps(self.record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
```

- [ ] **Step 4: Run tests to verify they pass, then commit**

Run: `uv run pytest tests/core/test_journal.py -q`
Expected: 4 passed.

```bash
git add src/omsorgsradar/core/journal.py tests/core/test_journal.py
git commit -m "G0: crash-safe run journal (runs/<id>/run.json)"
```

---

### Task 7: PxWeb adapter extraction (`core/adapters/`)

**Files:**
- Modify: `src/omsorgsradar/core/adapters/__init__.py`
- Create: `src/omsorgsradar/core/adapters/pxweb.py`
- Test: `tests/core/test_pxweb_adapter.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_pxweb_adapter.py`:
```python
"""PxWeb adapter — JSON-stat2 parsing + cache behavior, fully offline."""

import json
from pathlib import Path

from omsorgsradar.core.adapters.pxweb import PxWebAdapter, jsonstat2_to_df

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


class TestJsonStat2:
    def test_fixture_parses_to_tidy_df(self) -> None:
        payload = json.loads(
            (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
        )
        df = jsonstat2_to_df(payload)
        assert "value" in df.columns
        assert len(df) == len(payload["value"])


class TestAdapterCache:
    def test_post_table_uses_cache_without_network(self, tmp_path: Path) -> None:
        # Pre-seed the cache; base_url is unreachable on purpose — a cache hit
        # must short-circuit before any HTTP call.
        payload = {"dimension": {}, "id": [], "size": [], "value": []}
        (tmp_path / "12209.json").write_text(json.dumps(payload), encoding="utf-8")
        adapter = PxWebAdapter(
            base_url="http://127.0.0.1:9/unreachable", cache_dir=tmp_path
        )
        out = adapter.post_table("12209", query={"query": []})
        assert out == payload
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/core/test_pxweb_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Define the protocol in `core/adapters/__init__.py`**

Replace the placeholder content with:
```python
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
```

- [ ] **Step 4: Implement `core/adapters/pxweb.py`**

Move — do not rewrite — the bodies of `_post_px`, `_get_json`, and
`jsonstat2_to_df` from `src/omsorgsradar/ingest.py` into this file, adapted to
instance state as shown:

```python
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


def jsonstat2_to_df(payload: dict[str, Any], use_codes: bool = False) -> pd.DataFrame:
    # ← MOVE the existing function body from ingest.py UNCHANGED (incl. docstring).
    ...


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
```

The `...` under `jsonstat2_to_df` is the verbatim moved body (lines ~160–211 of
the current `ingest.py`, including the `import itertools` inside).

- [ ] **Step 5: Run tests to verify they pass, then commit**

Run: `uv run pytest tests/core/test_pxweb_adapter.py -q`
Expected: 2 passed.

```bash
git add src/omsorgsradar/core/adapters/__init__.py src/omsorgsradar/core/adapters/pxweb.py tests/core/test_pxweb_adapter.py
git commit -m "G0: PxWebAdapter extracted (cache + JSON-stat2 parse) + DatasetAdapter protocol"
```

---

### Task 8: Rewire `ingest.py` to the adapter + config-driven sources

**Files:**
- Modify: `src/omsorgsradar/ingest.py`
- Modify: `tests/test_ingest.py` (only if it calls changed signatures — check first)

- [ ] **Step 1: Inventory current usage**

Run: `grep -rn "fetch_kostra_pleie\|fetch_population\|fetch_fhi\|run_ingest\|_post_px\|_get_json\|jsonstat2_to_df\|KOSTRA_" src tests --include="*.py" | grep -v "core/adapters"`
Record every call site; the steps below must cover all of them.

- [ ] **Step 2: Re-export moved functions and delete duplicates in `ingest.py`**

At the top of `ingest.py`:
```python
from .core.adapters.pxweb import (  # noqa: F401  (backwards-compat re-exports)
    PxWebAdapter,
    jsonstat2_to_df,
)
```
Delete the now-duplicated `_post_px`, `_get_json`, `jsonstat2_to_df` function
bodies from `ingest.py`. Keep thin wrappers ONLY if Step 1 found external
callers of `_post_px`/`_get_json` (tests currently import `jsonstat2_to_df`
only — the re-export covers that).

- [ ] **Step 3: Make fetchers config-driven (signatures)**

Change the four fetchers to take their source parameters explicitly — no
module-level table constants remain (`KOSTRA_VAR_MAP`, `KOSTRA_WANTED_CODES`,
`KOSTRA_PLEIE_VARS`, `SSB_BASE`, `FHI_BASE` are deleted; canonical values live
in `analyses/omsorgsradar/analysis.toml` from Task 3):

```python
def fetch_kostra_pleie(
    *, base_url: str, table_id: str, var_map: dict[str, str],
    cache_dir: Path | None = None,
) -> pd.DataFrame: ...

def fetch_population_current(
    *, base_url: str, table_id: str, cache_dir: Path | None = None,
) -> pd.DataFrame: ...

def fetch_population_projections(
    *, base_url: str, table_id: str, cache_dir: Path | None = None,
) -> pd.DataFrame | None: ...

def fetch_fhi_nokkel(
    *, base_url: str, source: str, cache_dir: Path | None = None,
) -> pd.DataFrame | None: ...
```

Inside each body: replace `SSB_BASE`/`FHI_BASE`/literal table ids/var maps with
the parameters; route HTTP through one `PxWebAdapter(base_url=base_url,
cache_dir=cache_dir)` instance per call. Preserve existing cache keys exactly
(`table_id` default; projections keep `cache_key=f"proj_{table_id}"`).

- [ ] **Step 4: Make `run_ingest` consume `[[sources]]` blocks**

```python
_FETCHERS = {
    "kostra_pleie": lambda s, cache_dir: fetch_kostra_pleie(
        base_url=s["base_url"], table_id=s["table"],
        var_map=dict(s.get("var_map", {})), cache_dir=cache_dir),
    "befolkning": lambda s, cache_dir: fetch_population_current(
        base_url=s["base_url"], table_id=s["table"], cache_dir=cache_dir),
    "framskrivinger": lambda s, cache_dir: fetch_population_projections(
        base_url=s["base_url"], table_id=s["table"], cache_dir=cache_dir),
    "fhi_nokkel": lambda s, cache_dir: fetch_fhi_nokkel(
        base_url=s["base_url"], source=s["source"], cache_dir=cache_dir),
}


def run_ingest(
    sources: list[dict[str, Any]],
    *,
    db_path: Path,
    cache_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch every configured source, persist to DuckDB, return DataFrames."""
    datasets: dict[str, pd.DataFrame] = {}
    for src in sources:
        sid = src["id"]
        fetcher = _FETCHERS.get(sid)
        if fetcher is None:
            raise ValueError(
                f"no fetcher for source id '{sid}' (known: {sorted(_FETCHERS)})"
            )
        df = fetcher(src, cache_dir)
        if df is None:
            logger.warning("Source %s returned no data — skipped", sid)
            df = pd.DataFrame()
        datasets[sid] = df
    save_to_duckdb(datasets, db_path=db_path)
    return datasets
```
(Keep the existing knr-normalization and DuckDB persistence logic where it
lives today; only the dispatch/source plumbing changes. `_FETCHERS` keyed by
source id is interim — G1 replaces it with adapter-generic dispatch.)

- [ ] **Step 5: Fix call sites found in Step 1**

`pipeline.py` is rewritten in Task 10 (skip here). Update any `tests/test_ingest.py`
cases that called old signatures to pass explicit kwargs (values from
`analyses/omsorgsradar/analysis.toml`).

- [ ] **Step 6: Verify zero behavior change, then commit**

Run: `uv run pytest -x -q`
Expected: full suite passes (65 pre-existing + new core tests).
Run: `grep -rn "KOSTRA_VAR_MAP\|SSB_BASE\|FHI_BASE" src tests --include="*.py"`
Expected: no matches.

```bash
git add src/omsorgsradar/ingest.py tests/test_ingest.py
git commit -m "G0: ingest rewired to PxWebAdapter + config-driven sources (constants → analysis.toml)"
```

---

### Task 9: Stage registry + extension point (`core/registry.py`)

**Files:**
- Create: `src/omsorgsradar/core/registry.py`
- Test: `tests/core/test_registry.py`

- [ ] **Step 1: Write the failing tests**

`tests/core/test_registry.py`:
```python
"""Stage registry, verify-before-report rule, instance extension loading."""

from pathlib import Path

import pytest

from omsorgsradar.core.registry import (
    PipelineGateError,
    StageNotFoundError,
    StageRegistry,
    load_extensions,
    resolve_stage_list,
)


def _noop(ctx) -> None:  # minimal StageFn
    pass


class TestRegistry:
    def test_register_and_get(self) -> None:
        r = StageRegistry()
        r.register("profile", _noop)
        assert r.get("profile") is _noop

    def test_duplicate_without_override_rejected(self) -> None:
        r = StageRegistry()
        r.register("profile", _noop)
        with pytest.raises(ValueError, match="override"):
            r.register("profile", _noop)

    def test_override_shadows(self) -> None:
        def other(ctx) -> None:
            pass

        r = StageRegistry()
        r.register("profile", _noop)
        r.register("profile", other, override=True)
        assert r.get("profile") is other

    def test_unknown_stage_lists_known(self) -> None:
        r = StageRegistry()
        r.register("profile", _noop)
        with pytest.raises(StageNotFoundError, match="profile"):
            r.get("nope")


class TestResolveStageList:
    def test_verify_inserted_before_report(self) -> None:
        assert resolve_stage_list(["ingest", "report"]) == ["ingest", "verify", "report"]

    def test_misordered_verify_moved(self) -> None:
        assert resolve_stage_list(["report", "verify"]) == ["verify", "report"]

    def test_correct_order_untouched(self) -> None:
        stages = ["ingest", "analyze", "verify", "report"]
        assert resolve_stage_list(stages) == stages

    def test_no_report_no_change(self) -> None:
        assert resolve_stage_list(["ingest", "ml"]) == ["ingest", "ml"]


class TestExtensions:
    def test_missing_stages_py_is_fine(self, tmp_path: Path) -> None:
        r = StageRegistry()
        assert load_extensions(tmp_path, r) is False

    def test_extension_registers_shadow(self, tmp_path: Path) -> None:
        (tmp_path / "stages.py").write_text(
            "def my_report(ctx):\n"
            "    ctx.state['custom_report'] = True\n"
            "\n"
            "def register(registry):\n"
            "    registry.register('report', my_report, override=True)\n",
            encoding="utf-8",
        )
        r = StageRegistry()
        r.register("report", _noop)
        assert load_extensions(tmp_path, r) is True
        assert r.get("report") is not _noop

    def test_extension_without_register_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "stages.py").write_text("X = 1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="register"):
            load_extensions(tmp_path, StageRegistry())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/core/test_registry.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `core/registry.py`**

```python
"""Stage registry + execution context + instance extension point.

An *analysis instance* may ship ``analyses/<name>/stages.py`` exposing
``register(registry)``; its registrations (with ``override=True``) shadow core
stages for that analysis only. Core is never edited for a variant
(DECISIONS.md). Hard rule enforced here: ``verify`` always precedes
``report`` regardless of what the config says.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import RunConfig
from .journal import RunJournal


class StageNotFoundError(KeyError):
    """Requested stage is not registered."""


class PipelineGateError(RuntimeError):
    """A hard gate (verification) failed — downstream stages must not run."""


@dataclass
class StageContext:
    """Everything a stage may touch. Stages communicate via ``state``
    (in-memory, this run only) and ``artifacts`` (files, source of truth)."""

    config: RunConfig
    data_dir: Path
    reports_dir: Path
    journal: RunJournal
    state: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)


StageFn = Callable[[StageContext], None]


class StageRegistry:
    def __init__(self) -> None:
        self._stages: dict[str, StageFn] = {}

    def register(self, name: str, fn: StageFn, *, override: bool = False) -> None:
        if name in self._stages and not override:
            raise ValueError(
                f"stage '{name}' already registered — pass override=True to shadow it"
            )
        self._stages[name] = fn

    def get(self, name: str) -> StageFn:
        try:
            return self._stages[name]
        except KeyError:
            raise StageNotFoundError(
                f"unknown stage '{name}' (known: {sorted(self._stages)})"
            ) from None


def resolve_stage_list(stages: list[str]) -> list[str]:
    """Return the stage list with the verify-before-report rule enforced."""
    out = list(stages)
    if "report" in out:
        if "verify" in out:
            out.remove("verify")
        out.insert(out.index("report"), "verify")
    return out


def load_extensions(analysis_dir: Path, registry: StageRegistry) -> bool:
    """Import ``<analysis_dir>/stages.py`` (if present) and let it register.

    Returns True if an extension module was loaded.
    """
    ext = Path(analysis_dir) / "stages.py"
    if not ext.exists():
        return False
    spec = importlib.util.spec_from_file_location(
        f"omsorgsradar_ext_{Path(analysis_dir).name}", ext
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register", None)
    if not callable(register):
        raise ValueError(f"{ext} must define register(registry)")
    register(registry)
    return True
```

- [ ] **Step 4: Run tests to verify they pass, then commit**

Run: `uv run pytest tests/core/test_registry.py -q`
Expected: 11 passed.

```bash
git add src/omsorgsradar/core/registry.py tests/core/test_registry.py
git commit -m "G0: stage registry, verify-before-report rule, instance extension point"
```

---

### Task 10: Default stages + registry-driven pipeline

**Files:**
- Create: `src/omsorgsradar/stages.py`
- Modify: `src/omsorgsradar/pipeline.py` (full rewrite of `run_pipeline`)
- Create: `tests/conftest.py` (fixture-dataset helpers)
- Test: `tests/test_pipeline_gate.py`

- [ ] **Step 1: Create `tests/conftest.py` with fixture datasets**

```python
"""Shared fixtures: fixture-built datasets for offline pipeline runs."""

import json
from pathlib import Path

import pandas as pd
import pytest

from omsorgsradar.core.adapters.pxweb import jsonstat2_to_df
from omsorgsradar.kommune_mergers import normalize_knr_series

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _prep(payload: dict, *, has_alder: bool) -> pd.DataFrame:
    df = jsonstat2_to_df(payload)
    rename = {"Region": "region_label", "Tid": "aar"}
    if has_alder:
        rename["Alder"] = "alder"
    df = df.rename(columns=rename)
    df["knr_raw"] = (
        df["region_label"].str.extract(r"^(\d{4})", expand=False).str.zfill(4)
    )
    df["knr"] = normalize_knr_series(df["knr_raw"])
    df["aar"] = pd.to_numeric(df["aar"], errors="coerce")
    return df


@pytest.fixture()
def fixture_datasets() -> dict[str, pd.DataFrame]:
    kostra = json.loads(
        (FIXTURE_DIR / "ssb_12209_fixture.json").read_text(encoding="utf-8")
    )
    pop = json.loads((FIXTURE_DIR / "pop_fixture.json").read_text(encoding="utf-8"))
    return {
        "kostra_pleie": _prep(kostra, has_alder=False),
        "befolkning": _prep(pop, has_alder=True),
        "framskrivinger": pd.DataFrame(),
        "fhi_nokkel": pd.DataFrame(),
    }
```

- [ ] **Step 2: Write the failing pipeline tests**

`tests/test_pipeline_gate.py`:
```python
"""Registry-driven pipeline: journaled fixture run + verify-gate enforcement."""

import json
from pathlib import Path

import pytest

from omsorgsradar.core.registry import PipelineGateError, StageRegistry
from omsorgsradar.pipeline import run_pipeline
from omsorgsradar.stages import build_default_registry
from omsorgsradar.verify import VerificationReport

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = REPO_ROOT / "analyses" / "omsorgsradar"
WORKFLOW = REPO_ROOT / "workflow.toml"


def _test_registry(fixture_datasets) -> StageRegistry:
    """Default registry with ingest shadowed to inject fixture data (offline)."""
    registry = build_default_registry()

    def fake_ingest(ctx) -> None:
        ctx.state["datasets"] = fixture_datasets

    registry.register("ingest", fake_ingest, override=True)
    return registry


def _run(tmp_path: Path, fixture_datasets, **kwargs):
    return run_pipeline(
        ANALYSIS_DIR,
        workflow_path=WORKFLOW,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
        registry=_test_registry(fixture_datasets),
        skip_ml=True,
        use_llm=False,
        **kwargs,
    )


class TestFixtureRun:
    def test_full_offline_run(self, tmp_path: Path, fixture_datasets) -> None:
        report_path = _run(tmp_path, fixture_datasets)
        assert report_path is not None and report_path.exists()
        # journal
        run_dirs = list((tmp_path / "runs").iterdir())
        assert len(run_dirs) == 1
        rec = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
        assert rec["status"] == "ok"
        assert [s["stage"] for s in rec["stages"]] == [
            "ingest", "profile", "analyze", "verify", "report",
        ]
        # artifacts + manifests
        for name in ("quality_profile.json", "findings.json", "verification.json"):
            assert (tmp_path / "data" / name).exists()
            assert (tmp_path / "data" / f"{name}.manifest.json").exists()
        verdict = json.loads(
            (tmp_path / "data" / "verification.json").read_text(encoding="utf-8")
        )
        assert verdict["verdict"] == "PASS"


class TestVerifyGate:
    def test_failed_verification_blocks_report(
        self, tmp_path: Path, fixture_datasets, monkeypatch
    ) -> None:
        # The verifier's own claim-catching is covered by test_verify.py;
        # this test proves the PIPELINE refuses to ship on a FAIL verdict.
        from omsorgsradar.verify import Verifier

        def forced_fail(self, claims):
            return VerificationReport(
                total_claims=1, passed=0, failed=1, results=[], verdict="FAIL"
            )

        monkeypatch.setattr(Verifier, "verify_all", forced_fail)
        with pytest.raises(PipelineGateError):
            _run(tmp_path, fixture_datasets)
        run_dirs = list((tmp_path / "runs").iterdir())
        rec = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
        assert rec["status"] == "gate_failed"
        assert not (tmp_path / "reports").exists() or not list(
            (tmp_path / "reports").glob("*.md")
        )
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_pipeline_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_default_registry'`

- [ ] **Step 4: Implement `src/omsorgsradar/stages.py`**

```python
"""Default stage implementations wrapping the existing modules.

Each stage: read from ``ctx.state``/``ctx.artifacts``, compute via the
existing module functions, write file artifacts + manifests, fill ``ctx``.
The pipeline executor (pipeline.py) does the journaling.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from .core.contracts import validate_artifact, write_manifest
from .core.registry import PipelineGateError, StageContext, StageRegistry

logger = logging.getLogger(__name__)


def stage_ingest(ctx: StageContext) -> None:
    from .ingest import load_from_duckdb, run_ingest

    db_path = ctx.data_dir / f"{ctx.config.name}.duckdb"
    if ctx.state.get("skip_ingest"):
        datasets: dict[str, pd.DataFrame] = {}
        for src in ctx.config.sources:
            try:
                datasets[src["id"]] = load_from_duckdb(src["id"], db_path=db_path)
            except Exception as exc:  # missing table → empty df, same as v1
                logger.warning("Could not load %s: %s", src["id"], exc)
                datasets[src["id"]] = pd.DataFrame()
    else:
        datasets = run_ingest(
            ctx.config.sources, db_path=db_path, cache_dir=ctx.data_dir / "cache"
        )
    ctx.state["datasets"] = datasets
    ctx.artifacts["duckdb"] = db_path


def stage_profile(ctx: StageContext) -> None:
    from .profile import profile_all, save_quality_report

    quality = profile_all(ctx.state["datasets"])
    path = ctx.data_dir / "quality_profile.json"
    save_quality_report(quality, path=path)
    validate_artifact("quality_profile", quality)
    write_manifest(path, artifact="quality_profile", producer="profile")
    ctx.state["quality_report"] = quality
    ctx.artifacts["quality_profile"] = path


def stage_analyze(ctx: StageContext) -> None:
    from .analyze import result_to_dict, run_analysis, save_findings

    datasets = ctx.state["datasets"]
    result = run_analysis(
        df_kostra=datasets.get("kostra_pleie", pd.DataFrame()),
        df_pop=datasets.get("befolkning", pd.DataFrame()),
        df_proj=datasets.get("framskrivinger"),
    )
    path = ctx.data_dir / "findings.json"
    save_findings(result, path=path)
    validate_artifact("findings", result_to_dict(result))
    write_manifest(
        path,
        artifact="findings",
        producer="analyze",
        inputs=[str(ctx.artifacts.get("quality_profile", ""))],
    )
    ctx.state["result"] = result
    ctx.artifacts["findings"] = path


def stage_verify(ctx: StageContext) -> None:
    from .verify import Verifier, build_standard_claims

    result = ctx.state["result"]
    claims = build_standard_claims(result)
    vreport = Verifier(result).verify_all(claims)
    payload = {
        "verdict": vreport.verdict,
        "total_claims": vreport.total_claims,
        "passed": vreport.passed,
        "failed": vreport.failed,
        "failures": [r.message for r in vreport.results if not r.passes],
    }
    path = ctx.data_dir / "verification.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validate_artifact("verification", payload)
    write_manifest(
        path,
        artifact="verification",
        producer="verify",
        inputs=[str(ctx.artifacts.get("findings", ""))],
    )
    ctx.state["verification"] = vreport
    ctx.artifacts["verification"] = path
    if vreport.verdict != "PASS":
        raise PipelineGateError(vreport.summary())


def stage_report(ctx: StageContext) -> None:
    from .report import run_report

    vreport = ctx.state.get("verification")
    if vreport is None or vreport.verdict != "PASS":  # defense in depth
        raise PipelineGateError("report stage requires a green verification artifact")
    report_path, cost_info = run_report(
        result=ctx.state["result"],
        quality_report=ctx.state["quality_report"],
        report_dir=ctx.reports_dir,
        use_llm=ctx.state.get("use_llm"),
    )
    ctx.state["cost_info"] = cost_info
    ctx.artifacts["report"] = report_path


def stage_ml(ctx: StageContext) -> None:
    from .ml import ml_results_summary_md, run_ml, save_ml_results

    datasets = ctx.state["datasets"]
    ml_results = run_ml(
        df_kostra=datasets.get("kostra_pleie", pd.DataFrame()),
        df_pop=datasets.get("befolkning", pd.DataFrame()),
        figures_dir=ctx.reports_dir / "figures",
    )
    path = ctx.data_dir / "ml_results.json"
    save_ml_results(ml_results, path=path)
    write_manifest(path, artifact="quality_profile", producer="ml")  # NOTE: see Step 5
    ctx.artifacts["ml_results"] = path
    report_path = ctx.artifacts.get("report")
    if report_path is not None and report_path.exists():
        section = ml_results_summary_md(ml_results)
        existing = report_path.read_text(encoding="utf-8")
        marker = "---\n\n*Rapporten er generert"
        if marker in existing:
            existing = existing.replace(marker, section + "\n\n---\n\n*Rapporten er generert")
        else:
            existing = existing + "\n\n" + section
        report_path.write_text(existing, encoding="utf-8")


def build_default_registry() -> StageRegistry:
    registry = StageRegistry()
    registry.register("ingest", stage_ingest)
    registry.register("profile", stage_profile)
    registry.register("analyze", stage_analyze)
    registry.register("verify", stage_verify)
    registry.register("report", stage_report)
    registry.register("ml", stage_ml)
    return registry
```

- [ ] **Step 5: Fix the ml manifest artifact name**

The `stage_ml` manifest call above intentionally shows the wrong artifact name
to make this explicit: `ml_results` has no schema yet (G2 adds one). Manifests
without schemas are allowed — change that line to:

```python
    write_manifest(path, artifact="ml_results", producer="ml")
```
and in `core/contracts.py` `validate_artifact` is simply not called for it.

- [ ] **Step 6: Rewrite `src/omsorgsradar/pipeline.py`**

Full replacement:
```python
"""Registry-driven pipeline runner.

Usage::

    uv run python -m omsorgsradar.pipeline                       # omsorgsradar
    uv run python -m omsorgsradar.pipeline analyses/<name>       # any instance

Programmatic::

    from omsorgsradar.pipeline import run_pipeline
    run_pipeline("analyses/omsorgsradar")
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .core.config import load_run_config
from .core.journal import RunJournal
from .core.registry import (
    PipelineGateError,
    StageContext,
    StageRegistry,
    load_extensions,
    resolve_stage_list,
)
from .stages import build_default_registry

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
DEFAULT_ANALYSIS_DIR = REPO_ROOT / "analyses" / "omsorgsradar"
DEFAULT_WORKFLOW = REPO_ROOT / "workflow.toml"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"


def run_pipeline(
    analysis_dir: Path | str = DEFAULT_ANALYSIS_DIR,
    *,
    workflow_path: Path | str = DEFAULT_WORKFLOW,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    reports_dir: Path | str = DEFAULT_REPORTS_DIR,
    runs_dir: Path | str | None = None,
    registry: StageRegistry | None = None,
    skip_ingest: bool = False,
    skip_ml: bool = False,
    use_llm: bool | None = None,
) -> Path | None:
    """Run one analysis instance through its configured stages.

    Returns the report path if a report stage ran, else None.

    Raises:
        PipelineGateError: verification failed — no report was produced.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_run_config(analysis_dir, workflow_path)
    data_dir, reports_dir = Path(data_dir), Path(reports_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    reg = registry if registry is not None else build_default_registry()
    load_extensions(cfg.analysis_dir, reg)

    stages = resolve_stage_list(cfg.stage_list)
    if skip_ml and "ml" in stages:
        stages.remove("ml")

    journal = RunJournal.start(
        Path(runs_dir) if runs_dir is not None
        else REPO_ROOT / str(cfg.setting("analysis", "runs_dir", default="runs")),
        analysis=cfg.name,
        config_snapshot={"stages": stages, "workflow": cfg.workflow},
    )
    ctx = StageContext(
        config=cfg, data_dir=data_dir, reports_dir=reports_dir, journal=journal
    )
    ctx.state["skip_ingest"] = skip_ingest
    ctx.state["use_llm"] = use_llm

    try:
        for name in stages:
            before = dict(ctx.artifacts)
            t0 = time.monotonic()
            logger.info("Stage: %s", name)
            reg.get(name)(ctx)
            journal.record_stage(
                name,
                artifacts=[
                    str(p) for k, p in ctx.artifacts.items() if k not in before
                ],
                duration_s=round(time.monotonic() - t0, 3),
            )
    except PipelineGateError as exc:
        # record the failing stage before re-raising so the journal shows it
        journal.record_stage("verify", meta={"error": str(exc)})
        journal.finalize("gate_failed")
        raise
    except Exception:
        journal.finalize("error")
        raise

    journal.finalize("ok")
    logger.info("=== Pipeline complete: %s ===", journal.run_dir / "run.json")
    return ctx.artifacts.get("report")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an analysis instance.")
    parser.add_argument(
        "analysis_dir", nargs="?", default=str(DEFAULT_ANALYSIS_DIR),
        help="Path to analyses/<name>/ (default: omsorgsradar)",
    )
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-ml", action="store_true")
    args = parser.parse_args()
    run_pipeline(
        args.analysis_dir, skip_ingest=args.skip_ingest, skip_ml=args.skip_ml
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the new tests, then the full suite**

Run: `uv run pytest tests/test_pipeline_gate.py -q`
Expected: 2 passed.
Run: `uv run pytest -x -q`
Expected: full suite passes. If `tests/test_analyze.py` and friends fail on
imports of `jsonstat2_to_df` from `omsorgsradar.ingest`, the Task 8 re-export
is wrong — fix there, not here.

- [ ] **Step 8: Commit**

```bash
git add src/omsorgsradar/stages.py src/omsorgsradar/pipeline.py tests/conftest.py tests/test_pipeline_gate.py
git commit -m "G0: registry-driven pipeline with verify-gate, manifests, run journal"
```

---

### Task 11: Data-read hook (`.claude/hooks/`)

**Files:**
- Create: `.claude/hooks/block_raw_data_reads.py`, `.claude/settings.json`
- Test: `tests/test_hook_block_raw_data.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_hook_block_raw_data.py`:
```python
"""The data-read hook: row-level data never enters model context."""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block_raw_data_reads.py"


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestHook:
    def test_blocks_cache_read(self) -> None:
        p = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "data/cache/12209.json"}}
        )
        assert p.returncode == 2
        assert "row-level" in p.stderr

    def test_blocks_duckdb_read(self) -> None:
        p = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "data/omsorgsradar.duckdb"}}
        )
        assert p.returncode == 2

    def test_blocks_grep_in_cache(self) -> None:
        p = _run_hook({"tool_name": "Grep", "tool_input": {"path": "data/cache"}})
        assert p.returncode == 2

    def test_allows_findings_read(self) -> None:
        p = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "data/findings.json"}}
        )
        assert p.returncode == 0

    def test_allows_other_tools(self) -> None:
        p = _run_hook({"tool_name": "Bash", "tool_input": {"command": "ls data/cache"}})
        assert p.returncode == 0

    def test_garbage_input_does_not_crash_open(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(HOOK)], input="not json", capture_output=True,
            text=True, timeout=10,
        )
        assert proc.returncode == 0  # fail-open for malformed harness input
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_hook_block_raw_data.py -q`
Expected: FAIL — hook file does not exist.

- [ ] **Step 3: Implement `.claude/hooks/block_raw_data_reads.py`**

```python
#!/usr/bin/env python3
"""PreToolUse hook: deny model-context access to row-level data.

DECISIONS.md: the LLM orchestrates code; code touches data; only schemas,
profiles, and aggregates enter model context. Blocks Read/Grep on raw API
caches and DuckDB files. Aggregate artifacts (findings.json,
quality_profile.json, verification.json, reports) stay readable.
Stdlib only — runs under any python3 without the project venv.
"""

import json
import re
import sys

BLOCKED_PATTERNS = [
    r"(^|/)data/cache(/|$)",
    r"\.duckdb$",
]

MESSAGE = (
    "Blocked: row-level data must not enter model context (DECISIONS.md). "
    "Use the profile stage output (data/quality_profile.json) or DuckDB "
    "aggregate queries via Bash instead."
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail-open on malformed input; never brick the session
    if payload.get("tool_name") not in ("Read", "Grep"):
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}
    target = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if any(re.search(p, target) for p in BLOCKED_PATTERNS):
        print(MESSAGE, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `.claude/settings.json`**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Grep",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/block_raw_data_reads.py"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5: Run tests to verify they pass, then commit**

Run: `uv run pytest tests/test_hook_block_raw_data.py -q`
Expected: 6 passed.

```bash
git add .claude/hooks/block_raw_data_reads.py .claude/settings.json tests/test_hook_block_raw_data.py
git commit -m "G0: PreToolUse hook — raw caches/DuckDB never enter model context"
```

---

### Task 12: Stage skills scaffold + CLAUDE.md pointer

**Files:**
- Create: `.claude/skills/pipeline-stages/SKILL.md`
- Modify: `CLAUDE.md` (repo)

One skill (not five): G0 stages share one procedure document; per-stage skills
(`/magic-analyze`, `/add-dataset`) arrive in G3 with real workflows behind them.
YAGNI applies.

- [ ] **Step 1: Create `.claude/skills/pipeline-stages/SKILL.md`**

```markdown
---
name: pipeline-stages
description: How to run, extend, and debug the omsorgsradar analysis pipeline (ingest → profile → analyze → verify → report → ml). Use when working on any pipeline stage, adding an analysis instance, or investigating a failed run.
---

# Pipeline stages

## Run
- Full run: `uv run python -m omsorgsradar.pipeline` (default analysis: omsorgsradar)
- Any instance: `uv run python -m omsorgsradar.pipeline analyses/<name>`
- Offline iteration: add `--skip-ingest` (reads DuckDB) and `--skip-ml`
- Tests: `uv run pytest -x -q` — must be green before any commit

## Rules (DECISIONS.md, enforced)
- The LLM narrates and orchestrates; code computes. Never state a number that
  is not in `data/findings.json` / `data/ml_results.json`.
- `verify` always runs before `report` (engine-enforced; FAIL verdict aborts).
- Never Read `data/cache/**` or `*.duckdb` into context (hook-enforced).
  Inspect data via `data/quality_profile.json` or aggregate DuckDB queries.

## Extend
- New analysis: create `analyses/<name>/analysis.toml` (schema:
  `core/config.py`). Stage list + `[[sources]]` blocks; no code needed for
  existing adapters.
- Variant behavior: add `analyses/<name>/stages.py` with
  `register(registry)`; use `registry.register(name, fn, override=True)`.
  Core stages are never edited for a variant.
- Custom stages must write artifacts + manifests via
  `core.contracts.write_manifest` and validate known artifact types.

## Debug a run
- Every run journals to `runs/<run-id>/run.json`: stage order, durations,
  artifact paths, status (`ok` | `gate_failed` | `error`).
- `gate_failed` → read `data/verification.json` for the failing claims.
```

- [ ] **Step 2: Append to repo `CLAUDE.md`**

Add at the end of `/Users/ol/agents/ehelse_project/omsorgsradar/CLAUDE.md`:
```markdown

## v2 engine (G0+)
Config: `workflow.toml` (models/endpoint/defaults) + `analyses/<name>/analysis.toml`
(stages/sources/params); precedence analysis > workflow > code. Engine:
`src/omsorgsradar/core/` (config, contracts, journal, registry, adapters) +
`src/omsorgsradar/stages.py` (default stages). Variants = new instance folder,
never core edits. Run/extend/debug: see skill `pipeline-stages`.
Spec: `docs/specs/2026-06-11-v2-generalization-design.md`.
```

- [ ] **Step 3: Verify suite still green, then commit**

Run: `uv run pytest -x -q`
Expected: all pass.

```bash
git add .claude/skills/pipeline-stages/SKILL.md CLAUDE.md
git commit -m "G0: pipeline-stages skill + CLAUDE.md engine orientation"
```

---

### Task 13: Close out G0

**Files:**
- Modify: `status.md`, `.gitignore`

- [ ] **Step 1: Gitignore runs**

Append to `.gitignore` (create the lines if absent):
```
runs/
data/*.duckdb
```

- [ ] **Step 2: Full verification**

Run: `uv run pytest -q`
Expected: every test passes (pre-existing 65 + ~38 new). Record the exact count.
Run: `uv run python -m omsorgsradar.pipeline --skip-ingest --skip-ml`
Expected: completes with `Pipeline complete`, writes `runs/<id>/run.json` with
status `ok` (uses the committed DuckDB-cached data; if no local DuckDB exists,
expected: a clear `gate`/empty-data failure is acceptable — note which occurred).

- [ ] **Step 3: Update `status.md`**

Append:
```markdown
- **<today's date>** — **G0 shipped.** Engine extracted: core/ (config+schemas,
  contracts/manifests, journal, registry+extension point, PxWeb adapter),
  registry-driven pipeline with verify-gate, data-read hook, pipeline-stages
  skill. Canonical configs: workflow.toml + analyses/omsorgsradar/analysis.toml.
  Tests: <N>/<N> green. Next: G1 (Nordic adapters) — plan to be written.
```

- [ ] **Step 4: Final commit**

```bash
git add status.md .gitignore
git commit -m "G0: close out — engine + config extraction complete"
```

---

## Self-review (done at planning time)

- **Spec coverage (G0 scope):** core/ extraction ✓ (T1,4–10) · config files + validation ✓ (T2–3) · stage registry + extension point ✓ (T9) · manifests ✓ (T4–5) · journal ✓ (T6) · verify-gate in pipeline ✓ (T10) · data-read hook ✓ (T11) · skills scaffold ✓ (T12, consciously reduced to one skill — YAGNI) · 65 tests stay green ✓ (gates in T8, T10, T12, T13).
- **Known judgment calls:** `_FETCHERS` dispatch keyed by source id is explicitly interim (G1 replaces with adapter-generic dispatch). `ml_results` manifest has no schema until G2. `language`/`figure_style`/`[models]` config fields are loaded and validated but not yet consumed (G2/G5 wire them) — they exist now so configs don't churn.
- **Type consistency check:** `StageFn = Callable[[StageContext], None]` used by registry, stages.py, tests ✓ · `RunConfig.sources` list[dict] consumed by `run_ingest(sources=…)` and `stage_ingest` ✓ · `PipelineGateError` imported from `core.registry` everywhere (stages.py, pipeline.py, tests) ✓ · `VerificationReport(total_claims=…, passed=…, failed=…, results=[], verdict=…)` matches the existing dataclass field order/defaults in verify.py ✓.

## Follow-up plans (written per-phase, after the previous lands)

G1 Nordic adapters → G2 nordisk-omsorg analysis → G3 `/magic-analyze` + `/add-dataset`
→ G4 anonymize → G5 execution modes → G6 marimo + Pages + package.
Scope for each is locked in `docs/specs/2026-06-11-v2-generalization-design.md`.
