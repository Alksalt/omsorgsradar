"""Artifact manifests + schema validation at stage boundaries."""

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
