# G3 — Agentic Shell (/magic-analyze + /add-dataset) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the agentic shell per spec G3 — `/magic-analyze` (any dataset pointer → gated
analysis) and `/add-dataset` (agentic adapter authoring) skills, the research-ranked
`docs/dataset-registry.md`, and the **hard security gate** the spec requires before any
machine-authored `analysis.toml` executes (base_url host allowlist + csv path containment).

**Architecture:** Deterministic engine + agentic shell, strictly split: every enforcement and
every reusable decision lives in *testable engine code* (host allowlist + startup wiring, csv
containment, `--validate-only` / `--until` CLI gates, `core/discovery.py` pointer classifier);
the two skills are thin markdown that drive those engine commands and write **config and prose
only** (DECISIONS.md). The owner gate is explicit: `/magic-analyze` stops after ingest+profile
and presents the realness verdict before anything else runs.

**Tech Stack:** Existing only (stdlib `urllib.parse`, `argparse`, pandas, pytest via `uv`).
No new dependencies. No network in any new engine code path.

**Security gate inventory (spec §magic-analyze + G1/G2 panel flags):**
| Control | Status |
|---|---|
| cache keys sanitized (`\A[A-Za-z0-9._-]+\Z`, no `..`) | landed G1 |
| source `id` pattern-locked `^[a-z0-9_]+$` | landed G1 |
| socialstyrelsen/kolada response-URL host pinning | landed G1/G2 |
| **base_url host allowlist (startup)** | **this plan, Task 1** |
| **csv path containment (no absolute/`../` escape)** | **this plan, Task 2** |

**Conventions for the implementer:**
- `uv run` only; TDD; full suite green (`uv run pytest -q`, baseline **219 passed, 4
  deselected**) before each commit; commits prefixed `G3:` ending with:

```
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

- All new engine code is offline-testable; no live calls anywhere in this plan.
- Current file states this plan edits (verified 2026-06-12): `validate_source` at
  `core/adapters/__init__.py:95-122`; `pipeline.main()` at `pipeline.py:122-141` with
  `--skip-ingest/--skip-ml/--data-dir/--reports-dir`; `WORKFLOW_SCHEMA` at `config.py:26-57`
  (`endpoint` required; `models`/`defaults` optional); `CsvAdapter.fetch` at
  `csvfile.py:30-37` (absolute path wins, no containment).

**Execution notes (workspace policy):** sonnet implementers, opus reviewers, ≤10 agents.
Grouping: Tasks 1+2+3+4 (engine, one agent) → Tasks 5+6+7 (docs/skills, one agent) →
Task 8 (gate integration tests + close-out, one agent) → review panel.

---

## File structure

| Path | Action | Responsibility |
|---|---|---|
| `src/omsorgsradar/core/adapters/__init__.py` | modify | `ALLOWED_BASE_URL_HOSTS` + `validate_source_host` |
| `src/omsorgsradar/core/config.py` | modify | `[security].extra_allowed_hosts` in WORKFLOW_SCHEMA |
| `src/omsorgsradar/pipeline.py` | modify | startup host validation; `--validate-only`; `--until` |
| `src/omsorgsradar/core/adapters/csvfile.py` | modify | path containment |
| `src/omsorgsradar/core/discovery.py` | create | pointer classifier (pure, no network) |
| `docs/dataset-registry.md` | create | ranked source registry (verified vs adapter-ready) |
| `.claude/skills/magic-analyze/SKILL.md` | create | thin shell skill |
| `.claude/skills/add-dataset/SKILL.md` | create | thin shell skill |
| `tests/core/test_security_hosts.py`, `tests/core/test_discovery.py`, `tests/test_security_gate.py` | create | new coverage |
| `tests/core/test_csv_adapter.py`, `tests/core/test_config.py` | modify | containment policy + schema |
| `status.md`, `CLAUDE.md`, `DECISIONS.md`, `docs/adapters.md`, `.claude/skills/pipeline-stages/SKILL.md` | modify | close-out |

---

### Task 1: base_url host allowlist (startup security gate)

**Files:**
- Modify: `src/omsorgsradar/core/adapters/__init__.py`, `src/omsorgsradar/core/config.py`, `src/omsorgsradar/pipeline.py`
- Test: `tests/core/test_security_hosts.py` (create), `tests/core/test_config.py` (append)

- [ ] **Step 1: Write the failing tests** — `tests/core/test_security_hosts.py`:

```python
"""Startup security gate: base_url hosts must be allowlisted."""

import pytest

from omsorgsradar.core.adapters import ALLOWED_BASE_URL_HOSTS, validate_source_host
from omsorgsradar.core.config import ConfigError


class TestValidateSourceHost:
    def test_all_shipping_hosts_allowlisted(self) -> None:
        for host in ("data.ssb.no", "statistikk-data.fhi.no", "sotkanet.fi",
                     "sdb.socialstyrelsen.se", "opne-data-api.helserefusjon.no",
                     "api.kolada.se", "api.scb.se"):
            assert host in ALLOWED_BASE_URL_HOSTS, host

    def test_known_host_passes(self) -> None:
        validate_source_host({"id": "x", "adapter": "pxweb",
                              "base_url": "https://data.ssb.no/api/v0/no/table"})

    def test_subdomain_of_known_host_passes(self) -> None:
        validate_source_host({"id": "x", "base_url": "https://api.sotkanet.fi/rest"})

    def test_no_base_url_passes(self) -> None:
        validate_source_host({"id": "x", "adapter": "sotkanet"})  # adapter default

    def test_unknown_host_rejected_naming_it(self) -> None:
        with pytest.raises(ConfigError, match="evil.example.com.*not allowlisted"):
            validate_source_host({"id": "x", "base_url": "https://evil.example.com/api"})

    def test_lookalike_host_rejected(self) -> None:
        # suffix match must be on dot boundaries: notdata.ssb.no.evil.com etc.
        with pytest.raises(ConfigError):
            validate_source_host({"id": "x", "base_url": "https://data.ssb.no.evil.com/x"})

    def test_extra_hosts_extend_allowlist(self) -> None:
        src = {"id": "x", "base_url": "https://api.statbank.dk/v1"}
        with pytest.raises(ConfigError):
            validate_source_host(src)
        validate_source_host(src, extra_hosts=frozenset({"api.statbank.dk"}))


class TestPipelineStartupGate:
    def test_run_pipeline_rejects_unknown_host_before_any_stage(self, tmp_path) -> None:
        from omsorgsradar.pipeline import run_pipeline

        adir = tmp_path / "analyses" / "evil"
        adir.mkdir(parents=True)
        (adir / "analysis.toml").write_text(
            '[analysis]\nname = "evil"\n[stages]\nlist = ["ingest"]\n'
            '[[sources]]\nadapter = "pxweb"\nid = "bad"\n'
            'base_url = "https://evil.example.com/api"\ntable = "1"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="not allowlisted"):
            run_pipeline(adir, data_dir=tmp_path / "d",
                         reports_dir=tmp_path / "r", runs_dir=tmp_path / "runs")
        assert not list((tmp_path / "runs").glob("*")), "no journal before validation"
```

Append to `tests/core/test_config.py`:

```python
class TestSecuritySchema:
    def test_security_extra_hosts_accepted(self, tmp_path) -> None:
        from omsorgsradar.core.config import load_workflow_config
        (tmp_path / "workflow.toml").write_text(
            '[endpoint]\nmode = "subscription"\n'
            '[security]\nextra_allowed_hosts = ["api.statbank.dk"]\n',
            encoding="utf-8",
        )
        cfg = load_workflow_config(tmp_path / "workflow.toml")
        assert cfg["security"]["extra_allowed_hosts"] == ["api.statbank.dk"]

    def test_security_wrong_type_rejected(self, tmp_path) -> None:
        import pytest
        from omsorgsradar.core.config import ConfigError, load_workflow_config
        (tmp_path / "workflow.toml").write_text(
            '[endpoint]\nmode = "subscription"\n'
            '[security]\nextra_allowed_hosts = "api.statbank.dk"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="extra_allowed_hosts"):
            load_workflow_config(tmp_path / "workflow.toml")
```

- [ ] **Step 2:** Run: `uv run pytest tests/core/test_security_hosts.py -q` → ImportError.

- [ ] **Step 3: Implement.** In `core/adapters/__init__.py` add `from urllib.parse import
urlparse` to the imports, and after `REQUIRED_SOURCE_FIELDS` add:

```python
# Hosts the engine may fetch from — the startup security gate for
# machine-authored configs (spec 2026-06-11 §magic-analyze). Extend per repo
# via workflow.toml [security].extra_allowed_hosts, never by editing this
# list for one analysis.
ALLOWED_BASE_URL_HOSTS: frozenset[str] = frozenset({
    "data.ssb.no",
    "statistikk-data.fhi.no",
    "sotkanet.fi",
    "sdb.socialstyrelsen.se",
    "opne-data-api.helserefusjon.no",
    "api.kolada.se",
    "api.scb.se",
})


def validate_source_host(
    source: Mapping[str, Any],
    extra_hosts: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Reject ``base_url`` hosts outside the allowlist (startup gate).

    Sources without ``base_url`` use their adapter's default endpoint, which
    is allowlisted by construction. Suffix matches only on dot boundaries.
    """
    base = str(source.get("base_url", ""))
    if not base:
        return
    host = urlparse(base).netloc.lower()
    allowed = set(ALLOWED_BASE_URL_HOSTS) | set(extra_hosts)
    if host in allowed or any(host.endswith("." + h) for h in allowed):
        return
    raise ConfigError(
        f"source '{source.get('id', '<missing id>')}': base_url host {host!r} "
        f"is not allowlisted — extend workflow.toml [security].extra_allowed_hosts "
        f"if this host is genuinely needed (allowed: {sorted(allowed)})"
    )
```

In `config.py` `WORKFLOW_SCHEMA` properties (after `"defaults"`), add:

```python
        "security": {
            "type": "object",
            "properties": {
                "extra_allowed_hosts": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
        },
```

In `pipeline.py` `run_pipeline`, replace the existing startup loop

```python
    from .core.adapters import validate_source

    for src in cfg.sources:
        validate_source(src)
```
with:
```python
    from .core.adapters import validate_source, validate_source_host

    extra_hosts = frozenset(
        cfg.workflow.get("security", {}).get("extra_allowed_hosts", [])
    )
    for src in cfg.sources:
        validate_source(src)
        validate_source_host(src, extra_hosts)
```

- [ ] **Step 4:** `uv run pytest -q` → all green (canonical + nordisk configs use only
allowlisted hosts; the e2e tests must stay green — they are the regression proof).

- [ ] **Step 5: Commit**
```bash
git add src/omsorgsradar/core/adapters/__init__.py src/omsorgsradar/core/config.py src/omsorgsradar/pipeline.py tests/core/test_security_hosts.py tests/core/test_config.py
git commit -m "G3: base_url host allowlist enforced at pipeline startup"
```

---

### Task 2: csv path containment

**Files:**
- Modify: `src/omsorgsradar/core/adapters/csvfile.py`
- Test: `tests/core/test_csv_adapter.py` (policy change)

- [ ] **Step 1: Rewrite the affected tests.** In `tests/core/test_csv_adapter.py`, DELETE
`test_absolute_path_wins` and add:

```python
    def test_absolute_path_inside_base_ok(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "abs.csv", "a,b\n1,2\n")
        df = CsvAdapter(base_dir=tmp_path).fetch(
            {"adapter": "csv", "id": "x", "path": str(p),
             "provenance": {"institution": "T", "url": "https://x"}})
        assert df["a"].tolist() == [1]

    def test_absolute_path_outside_base_rejected(self, tmp_path: Path) -> None:
        outside = write_csv(tmp_path / "outside.csv", "a\n1\n")
        base = tmp_path / "analysis"
        base.mkdir()
        with pytest.raises(ValueError, match="escapes the analysis dir"):
            CsvAdapter(base_dir=base).fetch(
                {"adapter": "csv", "id": "x", "path": str(outside),
                 "provenance": {"institution": "T", "url": "https://x"}})

    def test_parent_escape_rejected(self, tmp_path: Path) -> None:
        write_csv(tmp_path / "secret.csv", "a\n1\n")
        base = tmp_path / "analysis"
        base.mkdir()
        with pytest.raises(ValueError, match="escapes the analysis dir"):
            CsvAdapter(base_dir=base).fetch(
                {"adapter": "csv", "id": "x", "path": "../secret.csv",
                 "provenance": {"institution": "T", "url": "https://x"}})
```

- [ ] **Step 2:** Run: `uv run pytest tests/core/test_csv_adapter.py -q` → 2 new FAIL.

- [ ] **Step 3: Implement.** In `csvfile.py` add `from ..config import ConfigError` and
replace the start of `fetch`:

```python
    def fetch(self, source: Mapping[str, Any]) -> pd.DataFrame:
        base = (self.base_dir or Path.cwd()).resolve()
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
```
(rest unchanged). Update the module docstring: replace the G1 paragraph
"Absolute and ``../`` paths are accepted ONLY because configs are owner-authored in G1…"
with:

```
Paths are contained: relative paths resolve inside the analysis dir, and any
path (absolute or ``../``) that resolves outside it is rejected — the G3
security gate for machine-authored configs. ``resolve()`` also neutralizes
symlink escapes.
```

- [ ] **Step 4:** `uv run pytest -q` → all green (the nordic-integration and
fabricated-csv tests use in-dir relative paths and still pass).

- [ ] **Step 5: Commit**
```bash
git add src/omsorgsradar/core/adapters/csvfile.py tests/core/test_csv_adapter.py
git commit -m "G3: csv path containment — no absolute/parent escape from the analysis dir"
```

---

### Task 3: pipeline `--validate-only` and `--until`

**Files:**
- Modify: `src/omsorgsradar/pipeline.py`
- Test: `tests/test_security_gate.py` (create — also used by Task 8)

- [ ] **Step 1: Write the failing tests** — `tests/test_security_gate.py`:

```python
"""G3 gate plumbing: --until truncation, --validate-only, gate flow."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SOTKANET_ANALYSIS = """\
[analysis]
name = "gate-test"

[stages]
list = ["ingest", "profile", "analyze", "verify", "report"]

[[sources]]
adapter = "sotkanet"
id = "fi_test"
indicators = [127]
years = [2023]
"""


def make_analysis(tmp_path: Path) -> tuple[Path, Path]:
    adir = tmp_path / "analyses" / "gate-test"
    adir.mkdir(parents=True)
    (adir / "analysis.toml").write_text(SOTKANET_ANALYSIS, encoding="utf-8")
    data_dir = tmp_path / "data"
    cache = data_dir / "cache"
    cache.mkdir(parents=True)
    fx = REPO / "tests" / "fixtures"
    shutil.copy(fx / "sotkanet_regions_fixture.json", cache / "sotkanet_regions.json")
    shutil.copy(fx / "sotkanet_127_fixture.json",
                cache / "sotkanet_127_2023_total.json")
    return adir, data_dir


class TestUntil:
    def test_until_profile_stops_before_analyze(self, tmp_path: Path) -> None:
        from omsorgsradar.pipeline import run_pipeline

        adir, data_dir = make_analysis(tmp_path)
        run_pipeline(adir, data_dir=data_dir, reports_dir=tmp_path / "r",
                     runs_dir=tmp_path / "runs", until="profile")
        run = json.loads(
            next((tmp_path / "runs").glob("*/run.json")).read_text(encoding="utf-8")
        )
        assert [s["name"] for s in run["stages"]] == ["ingest", "profile"]
        assert run["status"] == "ok"
        assert (data_dir / "quality_profile.json").exists()
        assert not (data_dir / "findings.json").exists()

    def test_until_unknown_stage_raises(self, tmp_path: Path) -> None:
        from omsorgsradar.pipeline import run_pipeline

        adir, data_dir = make_analysis(tmp_path)
        with pytest.raises(ValueError, match="until.*'nope'"):
            run_pipeline(adir, data_dir=data_dir, reports_dir=tmp_path / "r",
                         runs_dir=tmp_path / "runs", until="nope")


class TestValidateOnly:
    def test_cli_validate_only_ok(self) -> None:
        proc = subprocess.run(
            ["uv", "run", "python", "-m", "omsorgsradar.pipeline",
             "analyses/omsorgsradar", "--validate-only"],
            capture_output=True, text=True, cwd=REPO, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "OK: omsorgsradar" in proc.stdout
        assert "4 sources" in proc.stdout

    def test_cli_validate_only_bad_config_fails(self, tmp_path: Path) -> None:
        adir = tmp_path / "analyses" / "bad"
        adir.mkdir(parents=True)
        (adir / "analysis.toml").write_text(
            '[analysis]\nname = "bad"\n[stages]\nlist = ["ingest"]\n'
            '[[sources]]\nadapter = "pxweb"\nid = "x"\n'
            'base_url = "https://evil.example.com"\ntable = "1"\n',
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["uv", "run", "python", "-m", "omsorgsradar.pipeline",
             str(adir), "--validate-only"],
            capture_output=True, text=True, cwd=REPO, timeout=120,
        )
        assert proc.returncode != 0
        assert "not allowlisted" in (proc.stderr + proc.stdout)
```
(Note the sotkanet cache key: years `[2023]` → `sotkanet_127_2023_total` — the G1
full-year-list format. Also: the `run["stages"]` assertion assumes journal stage entries
carry a `"name"` key — check `src/omsorgsradar/core/journal.py` / an actual `run.json`
first and adjust the KEY in the assertion if the journal uses a different field name;
do not change journal.py.)

- [ ] **Step 2:** Run: `uv run pytest tests/test_security_gate.py -q` → FAIL
(`run_pipeline() got an unexpected keyword argument 'until'`).

- [ ] **Step 3: Implement.** In `run_pipeline`, add the parameter `until: str | None = None`
(after `use_llm`), and after the `skip_ml` block:

```python
    if until is not None:
        if until not in stages:
            raise ValueError(
                f"--until stage '{until}' is not in the resolved stage list {stages}"
            )
        stages = stages[: stages.index(until) + 1]
```

In `main()`, add the flags and the validate-only branch:

```python
    parser.add_argument(
        "--until", default=None, metavar="STAGE",
        help="stop after STAGE (e.g. 'profile' — the /magic-analyze owner gate)",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="load + validate config and sources (incl. host allowlist), then exit",
    )
    args = parser.parse_args()
    if args.validate_only:
        from .core.adapters import validate_source, validate_source_host

        cfg = load_run_config(args.analysis_dir, DEFAULT_WORKFLOW)
        extra = frozenset(
            cfg.workflow.get("security", {}).get("extra_allowed_hosts", [])
        )
        for src in cfg.sources:
            validate_source(src)
            validate_source_host(src, extra)
        print(f"OK: {cfg.name} — {len(cfg.sources)} sources valid, "
              f"stages: {cfg.stage_list}")
        return
    run_pipeline(
        args.analysis_dir,
        data_dir=args.data_dir,
        reports_dir=args.reports_dir,
        skip_ingest=args.skip_ingest,
        skip_ml=args.skip_ml,
        until=args.until,
    )
```

- [ ] **Step 4:** `uv run pytest tests/test_security_gate.py -q` → 4 passed
(the gate-test analysis runs offline from the seeded cache). Full suite green.

- [ ] **Step 5: Commit**
```bash
git add src/omsorgsradar/pipeline.py tests/test_security_gate.py
git commit -m "G3: pipeline --until (owner gate) and --validate-only CLI"
```

---

### Task 4: pointer classifier (`core/discovery.py`)

**Files:**
- Create: `src/omsorgsradar/core/discovery.py`
- Test: `tests/core/test_discovery.py`

- [ ] **Step 1: Failing tests** — `tests/core/test_discovery.py`:

```python
"""Pointer classification for /magic-analyze — pure, no network."""

from pathlib import Path

from omsorgsradar.core.discovery import HOST_ADAPTERS, Pointer, classify_pointer


class TestClassifyPointer:
    def test_known_api_urls_map_to_adapters(self) -> None:
        cases = {
            "https://data.ssb.no/api/v0/no/table/12209": "pxweb",
            "https://api.scb.se/OV0104/v1/doris/sv/ssd/START/BE": "pxweb",
            "https://sotkanet.fi/rest/1.1/json?indicator=127": "sotkanet",
            "https://api.kolada.se/v3/data/kpi/N21704/year/2023": "kolada",
            "https://sdb.socialstyrelsen.se/api/v1/sv/amning": "socialstyrelsen",
            "https://opne-data-api.helserefusjon.no/v1/fagomraader": "kuhr",
        }
        for url, adapter in cases.items():
            p = classify_pointer(url)
            assert p == Pointer("url", adapter, p.host), url

    def test_unknown_api_url(self) -> None:
        p = classify_pointer("https://opendata.nhsbsa.net/api/3/action/datastore_search")
        assert p.kind == "url" and p.adapter is None
        assert p.host == "opendata.nhsbsa.net"

    def test_csv_extension_is_file(self) -> None:
        assert classify_pointer("nedlastet/data.csv") == Pointer("file", "csv", None)

    def test_existing_file_is_file(self, tmp_path: Path) -> None:
        f = tmp_path / "dump.txt"
        f.write_text("x")
        assert classify_pointer(str(f)) == Pointer("file", "csv", None)

    def test_relative_existing_file_with_base_dir(self, tmp_path: Path) -> None:
        (tmp_path / "d.parquet").write_text("x")
        p = classify_pointer("d.parquet", base_dir=tmp_path)
        assert p.kind == "file"

    def test_free_text_is_question(self) -> None:
        p = classify_pointer("hvilke kommuner har flest fastlegebytter?")
        assert p == Pointer("question", None, None)

    def test_host_adapters_consistent_with_allowlist(self) -> None:
        from omsorgsradar.core.adapters import ALLOWED_BASE_URL_HOSTS
        assert set(HOST_ADAPTERS) <= set(ALLOWED_BASE_URL_HOSTS)
```

- [ ] **Step 2:** run → ModuleNotFoundError.

- [ ] **Step 3: Implement** `src/omsorgsradar/core/discovery.py`:

```python
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
```

- [ ] **Step 4:** tests pass; full suite green. **Commit:**
```bash
git add src/omsorgsradar/core/discovery.py tests/core/test_discovery.py
git commit -m "G3: pointer classifier — url/file/question with host-adapter mapping"
```

---

### Task 5: `docs/dataset-registry.md`

**Files:** Create `docs/dataset-registry.md`.

- [ ] **Step 1: Write the file** (content below is complete — verification dates are real
session facts; do not invent new ones):

```markdown
# Dataset registry — ranked open health-data sources

The `/magic-analyze` shell resolves free-text questions against this registry
(Tier 1 first). Adapter column = what `[[sources]]` needs; per-adapter fields in
`docs/adapters.md`. Hosts must be in the engine allowlist
(`core/adapters/__init__.py::ALLOWED_BASE_URL_HOSTS` + workflow.toml
`[security].extra_allowed_hosts`).

## Tier 1 — adapter exists, API verified live

| Source | Land | Innhold | Adapter | Base URL | Verifisert |
|---|---|---|---|---|---|
| SSB PxWebAPI v2 | NO | KOSTRA pleie/omsorg (12209), befolkning (07459), framskrivinger (12880) — kommune | `pxweb` | `https://data.ssb.no/api/v0/no/table` | 2026-06-11/12 |
| SCB PxWeb | SE | Befolkning per kommun/ålder (BefolkningNy) m.fl. | `pxweb` (+`cache_key`, `use_codes`) | `https://api.scb.se/OV0104/v1/doris/sv/ssd/...` | 2026-06-12 |
| THL Sotkanet | FI | ~3 700 indikatorer per kunta; kotihoito 75+ = **5513** (3216 er død), 75+-andel = 171, befolkning = 127, prognoser 745/757. CC BY 4.0 | `sotkanet` | `https://sotkanet.fi/rest/1.1` (krever User-Agent) | 2026-06-12 |
| Kolada (RKA) | SE | Kommunale KPI-er; hemtjänst 80+ = **N21704** (Socialstyrelsen/SCB-data republisert) | `kolada` | `https://api.kolada.se/v3` | 2026-06-12 |
| KUHR helserefusjon | NO | Takstbruk per kommune/år (fastlege m.fl.), 2015– | `kuhr` | `https://opne-data-api.helserefusjon.no/v1` | 2026-06-12 |
| Socialstyrelsen sdb | SE | Helse-emner (amning, diagnoser, läkemedel, skador per kommun, dödsorsaker). ⚠ INGEN äldreomsorg-topic — bruk Kolada | `socialstyrelsen` | `https://sdb.socialstyrelsen.se/api/v1/sv` | 2026-06-12 |
| FHI NOKKEL | NO | Folkehelseindikatorer per kommune. ⚠ Discovery-endepunkt 404 2026-06-11 (`docs/api_drift.md`) | legacy fetcher (id `fhi_nokkel`) | `https://statistikk-data.fhi.no/api/open/v1` | delvis |

## Tier 2 — adapter-ready, IKKE verifisert (research 2026-06-11, wiki
`tech/agentic-healthcare-analysis-workflow-2026`)

| Source | Land | Innhold | Nærmeste adapter | Notat |
|---|---|---|---|---|
| Danmarks Statistik StatBank | DK | Hjemmesygepleje per kommune m.m. | NY (`api.statbank.dk/v1` er egen JSON-API, ikke PxWeb) | /add-dataset-kandidat |
| Folkhälsomyndigheten | SE | Folkhälsodata (PxWeb) | trolig `pxweb` | verifiser dialekt først |
| NHS English Prescribing Dataset | EN | GP-praksis × legemiddel × måned, >2,2 mrd rader, CKAN `datastore_search_sql`, OGL v3 | NY (`ckan`) | størst åpne forskrivningsdata |
| CDC BRFSS | US | Reell mikrodata (helseatferd), XPT-filer | `csv` etter konvertering | anonymiserings-demo (G4) |
| CMS Medicare Part D | US | Forskrivning per lege/legemiddel | NY | data.cms.gov API |

## Regler

- Nye kilder: `/add-dataset` — én prøvespørring, så `[[sources]]`-blokk eller ny
  adapter + fixture + known-value-test (G1-mønsteret). Aldri endre eksisterende
  adapteres oppførsel.
- Nye verter: legg til i `ALLOWED_BASE_URL_HOSTS` (kodeendring + review) eller
  midlertidig i workflow.toml `[security].extra_allowed_hosts` (eier-beslutning).
- Realness-gates kjører uansett kilde; csv krever eksplisitt `[sources.provenance]`.
```

- [ ] **Step 2: Commit**
```bash
git add docs/dataset-registry.md
git commit -m "G3: dataset registry — Tier 1 verified sources + Tier 2 candidates"
```

---

### Task 6: `/magic-analyze` skill

**Files:** Create `.claude/skills/magic-analyze/SKILL.md`.

- [ ] **Step 1: Write the skill** (thin; every step is an engine command; full text):

```markdown
---
name: magic-analyze
description: Analyser et hvilket som helst datasett-pekepunkt (URL, lokal fil, eller fritekst-spørsmål) gjennom omsorgsradar-pipelinen — klassifiser, skriv analyses/<slug>/analysis.toml, kjør ingest+profile-gaten, presenter realness-verdikten for eieren, og kjør resten på grønt. Use when the owner says "/magic-analyze <pointer>" or "analyser <datasett/spørsmål>".
---

# /magic-analyze <url | path | question>

## Hard rules (DECISIONS.md — not negotiable)

- You write **config and prose only**. Never computation code. A custom
  `analyses/<slug>/stages.py` is allowed only if the owner explicitly asks.
- Never state a number that is not in an artifact
  (`findings*.json` / `quality_profile.json` / `verification.json`).
- The profile gate verdict goes to the OWNER before analyze/report runs. Stop
  and present it — do not proceed on your own.
- Never bypass the host allowlist. Unknown host → ask the owner to add it to
  `workflow.toml [security].extra_allowed_hosts` (their call, not yours).

## Flow

1. **Classify the pointer:**
   `uv run python -c "from omsorgsradar.core.discovery import classify_pointer; print(classify_pointer('<pointer>'))"`
   - `url` + adapter → write the `[[sources]]` block directly
     (required fields per adapter: `docs/adapters.md`).
   - `url` + no adapter → switch to `/add-dataset` first.
   - `file` → csv adapter. Copy/download the file INTO `analyses/<slug>/`
     (path containment is engine-enforced); `[sources.provenance]`
     institution + url are mandatory for csv.
   - `question` → pick candidates from `docs/dataset-registry.md` (Tier 1
     first). If several fit, propose 1–3 to the owner before drafting.
2. **Draft** `analyses/<slug>/analysis.toml` (slug `^[a-z0-9-]+$`; ids
   `^[a-z0-9_]+$`). Stage list `["ingest", "profile"]` unless the analysis
   semantics are already defined — the default analyze stage is
   omsorgsradar-specific, and a new question usually needs an owner decision
   about metrics before any analyze stage exists.
3. **Validate:**
   `uv run python -m omsorgsradar.pipeline analyses/<slug> --validate-only`
   Fix exactly what the error names. Repeat until `OK:`.
4. **Gate run:**
   `uv run python -m omsorgsradar.pipeline analyses/<slug> --data-dir data/<slug> --reports-dir reports/<slug> --until profile`
   Read `data/<slug>/quality_profile.json`. Present per-dataset realness
   verdicts + row counts to the owner. **STOP.** (FAIL aborts the pipeline by
   itself; WARN/PASS is the owner's call.)
5. **On owner green:** rerun without `--until`. Link the report, figures and
   `runs/<run-id>/run.json`. Narrate findings from the artifacts only.

## Debugging

A failed run names its stage in `runs/<run-id>/run.json`; from there use the
`pipeline-stages` skill.
```

- [ ] **Step 2: Verify the engine commands the skill quotes actually work** (offline):

Run: `uv run python -c "from omsorgsradar.core.discovery import classify_pointer; print(classify_pointer('https://sotkanet.fi/rest/1.1/json?indicator=127'))"`
Expected: `Pointer(kind='url', adapter='sotkanet', host='sotkanet.fi')`

Run: `uv run python -m omsorgsradar.pipeline analyses/omsorgsradar --validate-only`
Expected: `OK: omsorgsradar — 4 sources valid, stages: [...]`

- [ ] **Step 3: Commit**
```bash
git add .claude/skills/magic-analyze/SKILL.md
git commit -m "G3: /magic-analyze skill — classify, draft config, owner-gated run"
```

---

### Task 7: `/add-dataset` skill

**Files:** Create `.claude/skills/add-dataset/SKILL.md`.

- [ ] **Step 1: Write the skill** (full text):

```markdown
---
name: add-dataset
description: Koble en ny åpen data-API eller fil inn i pipelinen — inspiser API-formen med ÉN prøvespørring, skriv en [[sources]]-blokk for en eksisterende adapter, eller skaff ny adapter-modul + offline fixture + known-value-test etter G1-mønsteret. Use when the owner says "/add-dataset <url>" or asks to wire in a new data source/API.
---

# /add-dataset <api-url>

## Hard rules

- **Never edit an existing adapter's behavior** for a new dataset
  (DECISIONS.md). New API shape = new module.
- Every new adapter ships with: offline fixture captured from the REAL API,
  a known-value test pinning real printed literals (never invented numbers),
  and a `@pytest.mark.live` test. `sotkanet.py` and `kolada.py` are the
  cleanest templates to copy.
- Output is a commit-ready diff; the owner reviews and commits.

## Flow

1. **Classify:** `classify_pointer('<url>')` (see /magic-analyze step 1).
   Known adapter → just write the `[[sources]]` block per `docs/adapters.md`,
   check it with `--validate-only`, add a row to `docs/dataset-registry.md`,
   done — no code.
2. **Unknown shape:** make ONE small sample call (curl, a few KB). Identify:
   JSON-stat2 (→ `pxweb` likely covers it)? Flat JSON rows? Paginated
   (response-supplied next-links MUST be host-pinned — copy the kolada/
   socialstyrelsen guard)? Document the exact request/response shape in the
   new module docstring with today's date, exactly like the existing adapters.
3. **New adapter checklist** (G1 pattern, in order):
   - `src/omsorgsradar/core/adapters/<name>.py` — use `JsonCache`,
     `DEFAULT_TIMEOUT`; geographic data emits the tidy contract
     (`country, geo_code, geo_id, geo_name, aar, indicator, value`,
     `geo_id` via `core/geo.py` where NO/SE/FI).
   - Register: `REQUIRED_SOURCE_FIELDS` + factory + `ADAPTER_FACTORIES` in
     `core/adapters/__init__.py`; host into `ALLOWED_BASE_URL_HOSTS`;
     `realness.py` `KNOWN_HOSTS` + `ADAPTER_PROVENANCE`.
   - Fixture capture script run once; paste the printed literals into the
     known-value test.
   - Tests: seeded-cache offline (unreachable `base_url`), known-value,
     registry/provenance, live-marked.
   - Docs: section in `docs/adapters.md` + row in `docs/dataset-registry.md`.
4. **Prove it:** `uv run pytest -q` green and the new live test green
   (`uv run pytest tests/core/test_<name>_adapter.py -m live -q`).
   Present the diff to the owner.
```

- [ ] **Step 2: Commit**
```bash
git add .claude/skills/add-dataset/SKILL.md
git commit -m "G3: /add-dataset skill — one probe, adapter checklist, commit-ready diff"
```

---

### Task 8: Gate integration tests + close-out

**Files:**
- Test: `tests/test_security_gate.py` (append)
- Modify: `status.md`, `CLAUDE.md`, `DECISIONS.md`, `docs/adapters.md`, `.claude/skills/pipeline-stages/SKILL.md`

- [ ] **Step 1: Append the machine-authored-config gate tests** to
`tests/test_security_gate.py`:

```python
class TestMachineAuthoredConfigGate:
    """The two G3 security controls, end-to-end through run_pipeline."""

    def test_csv_escape_blocked_at_ingest(self, tmp_path: Path) -> None:
        from omsorgsradar.core.config import ConfigError
        from omsorgsradar.pipeline import run_pipeline

        (tmp_path / "secret.csv").write_text("a\n1\n", encoding="utf-8")
        adir = tmp_path / "analyses" / "sneaky"
        adir.mkdir(parents=True)
        (adir / "analysis.toml").write_text(
            '[analysis]\nname = "sneaky"\n[stages]\nlist = ["ingest"]\n'
            '[[sources]]\nadapter = "csv"\nid = "leak"\n'
            'path = "../../secret.csv"\n'
            '[sources.provenance]\ninstitution = "X"\nurl = "https://x"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="escapes the analysis dir"):
            run_pipeline(adir, data_dir=tmp_path / "d",
                         reports_dir=tmp_path / "r", runs_dir=tmp_path / "runs")

    def test_extra_allowed_hosts_honored_end_to_end(self, tmp_path: Path) -> None:
        from omsorgsradar.core.config import load_workflow_config
        from omsorgsradar.core.adapters import validate_source_host

        (tmp_path / "workflow.toml").write_text(
            '[endpoint]\nmode = "subscription"\n'
            '[security]\nextra_allowed_hosts = ["api.statbank.dk"]\n',
            encoding="utf-8",
        )
        wf = load_workflow_config(tmp_path / "workflow.toml")
        extra = frozenset(wf["security"]["extra_allowed_hosts"])
        validate_source_host(
            {"id": "dk", "adapter": "pxweb",
             "base_url": "https://api.statbank.dk/v1", "table": "x"},
            extra,
        )  # no raise
```

Run: `uv run pytest tests/test_security_gate.py -q` → all pass. Full suite green.

- [ ] **Step 2: docs.** In `docs/adapters.md` csv section, append: *`path` must resolve
inside the analysis dir — absolute paths and `../` escapes are rejected (G3 gate).*
In `.claude/skills/pipeline-stages/SKILL.md` §Run, add the two new commands:

```markdown
- Validate a config without running: `uv run python -m omsorgsradar.pipeline analyses/<name> --validate-only`
- Owner-gate run (ingest+profile only): add `--until profile`
```

In `DECISIONS.md`, append:

```markdown
- Machine-authored analysis.toml executes only behind the startup security gate: base_url host-allowlist (`ALLOWED_BASE_URL_HOSTS`; owner extends via workflow.toml `[security].extra_allowed_hosts`) + csv path containment. Skills (`/magic-analyze`, `/add-dataset`) never bypass it.
- `/magic-analyze` presents the ingest+profile realness verdict to the owner and stops; analyze/report run only on the owner's green.
```

In `status.md`, append (fill N with the real count):

```markdown
- **2026-06-12** — **G3 (agentic shell) shipped.** `/magic-analyze` (klassifiser →
  utkast analysis.toml → `--validate-only` → `--until profile`-gate → eier-verdikt →
  full kjøring) + `/add-dataset` (én prøvespørring → sources-blokk eller ny adapter
  etter G1-mønsteret) som tynne skills over testbare motor-kommandoer. Motor:
  `ALLOWED_BASE_URL_HOSTS`-allowlist håndhevet ved oppstart (+ workflow.toml
  `[security].extra_allowed_hosts`), csv-path-containment, `--validate-only`/`--until`,
  `core/discovery.py` pointer-klassifisering. `docs/dataset-registry.md` (Tier 1
  verifisert / Tier 2 kandidater). Tests: 219 → N offline. **Next: G4 — anonymize
  stage (Presidio nb + anonymeter) + BRFSS-demo + planted-PII-test.**
```

In `CLAUDE.md`, update the Status line (G3 shipped, next G4) and add one line to the
v2 engine block: `Shell: /magic-analyze + /add-dataset skills; sources gated by host
allowlist + path containment at startup.`

- [ ] **Step 3: Final verification + commit**

Run: `uv run pytest -q` (record count) and `uv run pytest -m live -q` (4 expected).
```bash
git add tests/test_security_gate.py docs/adapters.md .claude/skills/pipeline-stages/SKILL.md DECISIONS.md status.md CLAUDE.md
git commit -m "G3: close out — gate integration tests, docs, decisions"
```

---

## Self-review checklist (run before execution)

- Spec §magic-analyze: classify (T4+T6) ✓ · draft toml only (T6 hard rules) ✓ · gate on
  ingest+profile with owner verdict (T3 `--until` + T6 step 4) ✓ · run on green, narrate
  from findings only (T6 step 5) ✓ · security gate base_url/cache-keys (T1 + landed G1)
  ✓ · csv containment (T2, panel flag) ✓.
- Spec §add-dataset: one sample call + shape sniff (T7 step 2) ✓ · closest adapter →
  sources block (T7 step 1) ✓ · new shape → adapter+fixture+known-value test (T7 step 3,
  G1 pattern) ✓ · commit-ready diff, never edit existing adapters (T7 hard rules) ✓.
- Spec: dataset registry doc (T5) ✓ · "skills tested by their underlying engine
  commands; skill markdown stays thin" — every skill step quotes an engine command that
  has its own test (T1/T3/T4) ✓.
- Out of scope (deliberate): `[endpoint.api]` additionalProperties hardening (G5 flag),
  anonymize (G4), LLM endpoint plumbing (G5), Pages site (G6).
- Breaking change accepted: csv absolute-path-outside-base now rejected (was allowed in
  G1) — policy change, tests updated in T2, no shipped config uses it.
