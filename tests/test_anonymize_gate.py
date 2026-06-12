"""Integration tests for G4: anonymize stage, identifiability gate, row_level check.

Tests follow the TestRealnessGate pattern: build a temp analysis dir with a CSV +
analysis.toml, call run_pipeline, assert gate behaviour + artifact-published-before-abort.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from omsorgsradar.core.anonymize import append_fnr_control_digits
from omsorgsradar.core.registry import PipelineGateError
from omsorgsradar.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _planted_fnr() -> str:
    """Build a checksum-valid fnr for use in notes text."""
    return append_fnr_control_digits("010190100")


def _make_people_csv(path: Path, homogeneous_diabetes: bool = False) -> None:
    """Write ~30 rows: state, age, sex, diabetes, notes.

    Design:
    - Three states (A, B, C), two age values (30, 50), two sex values (M, F)
      giving 12 (state x age x sex) classes of 2-3 rows each — enough to
      survive k=3 suppression after generalize bins collapse age into bands.
    - After generalization all ages map to "30-59" → large classes survive k=3.
    - Row 0 note contains the planted fnr; rest are "rutinekontroll".
    """
    fnr = _planted_fnr()
    rows = []
    # 5 rows per (state, sex) with ages 30/50 → after bin collapse into "30-59"
    # each (state, sex) class has 10 rows, well above k=3.
    for state in ["A", "B", "C"]:
        for sex in ["M", "F"]:
            for i, age in enumerate([30, 30, 30, 50, 50]):
                diabetes_val = 1 if homogeneous_diabetes else (i % 2)
                note = f"Pasient fnr {fnr} rutinekontroll" if (state == "A" and sex == "M" and i == 0) else "rutinekontroll"
                rows.append(f"{state},{age},{sex},{diabetes_val},{note}")

    content = "state,age,sex,diabetes,notes\n" + "\n".join(rows) + "\n"
    path.write_text(content, encoding="utf-8")


_ANALYSIS_TOML_PASS = """\
[analysis]
name = "people"

[stages]
list = ["ingest", "profile", "anonymize"]

[[sources]]
adapter = "csv"
id = "people"
path = "microdata/people.csv"
row_level = true

[sources.provenance]
institution = "Test Institution"
url = "https://example.org/data"

[params.anonymize]
source = "people"
text_columns = ["notes"]
quasi_identifiers = ["state", "age", "sex"]
sensitive = "diabetes"
k = 3

[params.anonymize.generalize.age]
bins = [0, 60, 120]
labels = ["30-59", "60+"]

[params.anonymize.thresholds]
l_min = 1
inference = 0.9
linkability = 0.5
"""

_ANALYSIS_TOML_FAIL = """\
[analysis]
name = "people"

[stages]
list = ["ingest", "profile", "anonymize"]

[[sources]]
adapter = "csv"
id = "people"
path = "microdata/people.csv"
row_level = true

[sources.provenance]
institution = "Test Institution"
url = "https://example.org/data"

[params.anonymize]
source = "people"
text_columns = ["notes"]
quasi_identifiers = ["state", "age", "sex"]
sensitive = "diabetes"
k = 3

[params.anonymize.generalize.age]
bins = [0, 60, 120]
labels = ["30-59", "60+"]

[params.anonymize.thresholds]
l_min = 2
inference = 0.9
linkability = 0.5
"""

_ANALYSIS_TOML_NO_ANONYMIZE = """\
[analysis]
name = "people"

[stages]
list = ["ingest", "profile"]

[[sources]]
adapter = "csv"
id = "people"
path = "microdata/people.csv"
row_level = true

[sources.provenance]
institution = "Test Institution"
url = "https://example.org/data"
"""


def _make_analysis_dir(tmp_path: Path, toml_content: str, homogeneous: bool = False) -> Path:
    adir = tmp_path / "analyses" / "people"
    adir.mkdir(parents=True)
    micro_dir = adir / "microdata"
    micro_dir.mkdir()
    _make_people_csv(micro_dir / "people.csv", homogeneous_diabetes=homogeneous)
    (adir / "analysis.toml").write_text(toml_content, encoding="utf-8")
    return adir


def _run(adir: Path, tmp_path: Path):
    return run_pipeline(
        adir,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        runs_dir=tmp_path / "runs",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAnonymizeGate:
    def test_planted_pii_redacted_and_receipted(self, tmp_path: Path) -> None:
        """PII redaction fires, receipt written, row_level realness doesn't FAIL."""
        adir = _make_analysis_dir(tmp_path, _ANALYSIS_TOML_PASS)
        data_dir = tmp_path / "data"

        # Should NOT raise — loose thresholds (l_min=1, inference=0.9) allow PASS/WARN
        _run(adir, tmp_path)

        # identifiability.json on disk
        receipt_path = data_dir / "identifiability.json"
        assert receipt_path.exists(), "identifiability.json not written"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        # Verdict must be PASS or WARN (not FAIL)
        assert receipt["verdict"] in {"PASS", "WARN"}, (
            f"Expected PASS or WARN, got {receipt['verdict']}"
        )

        # PII sub-dict present + fnr was detected
        pii = receipt.get("pii", {})
        assert pii.get("total_redacted", 0) >= 1, "Expected at least one entity redacted"
        assert "NO_FODSELSNUMMER" in pii.get("entity_types", []), (
            "Expected NO_FODSELSNUMMER in entity_types"
        )

        # Planted fnr must NOT appear in the anonymized CSV
        anon_csv_path = data_dir / "people_anonymized.csv"
        assert anon_csv_path.exists(), "people_anonymized.csv not written"
        anon_text = anon_csv_path.read_text(encoding="utf-8")
        fnr = _planted_fnr()
        assert fnr not in anon_text, (
            f"Planted fnr {fnr} still present in anonymized CSV — redaction failed"
        )

        # quality_profile realness for people should NOT be FAIL
        # (row_level skips duplicate/missingness/distribution checks)
        quality_path = data_dir / "quality_profile.json"
        assert quality_path.exists()
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        realness = quality["datasets"]["people"]["realness"]
        assert realness["verdict"] != "FAIL", (
            f"Realness gate FAIL for row_level source (should be SKIP'd for shape checks): "
            f"{realness}"
        )
        # Duplicate + missingness + distribution should be SKIP
        check_map = {c["name"]: c["status"] for c in realness["checks"]}
        assert check_map.get("duplicates") == "SKIP", (
            f"Expected duplicates=SKIP for row_level source, got {check_map}"
        )
        assert check_map.get("missingness") == "SKIP"
        assert check_map.get("distribution") == "SKIP"

    def test_inference_fail_aborts(self, tmp_path: Path) -> None:
        """Homogeneous sensitive attribute + l_min=2 → inference FAIL, gate raises."""
        adir = _make_analysis_dir(tmp_path, _ANALYSIS_TOML_FAIL, homogeneous=True)
        data_dir = tmp_path / "data"

        with pytest.raises(PipelineGateError, match="identifiability"):
            _run(adir, tmp_path)

        # Receipt must be on disk BEFORE the abort
        receipt_path = data_dir / "identifiability.json"
        assert receipt_path.exists(), "identifiability.json must be written before abort"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["verdict"] == "FAIL", (
            f"Expected FAIL verdict in receipt, got {receipt['verdict']}"
        )
        # N14: the insufficiently-anonymized CSV must NOT remain on disk
        leftover = list(data_dir.glob("*_anonymized.csv"))
        assert not leftover, f"FAIL verdict must unlink the anonymized CSV, found {leftover}"

    def test_row_level_source_requires_anonymize(self, tmp_path: Path) -> None:
        """row_level=true source without 'anonymize' in stages → startup PipelineGateError."""
        adir = _make_analysis_dir(tmp_path, _ANALYSIS_TOML_NO_ANONYMIZE)

        with pytest.raises(PipelineGateError, match="row.level|anonymize"):
            _run(adir, tmp_path)
