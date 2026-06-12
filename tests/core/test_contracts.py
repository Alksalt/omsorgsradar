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

    def test_absolute_path_inside_repo_is_relativized(self) -> None:
        """Finding 5: an absolute artifact path inside the repo must be stored
        repo-relative — committed manifests must not leak /Users/... local
        paths. The omsorgsradar top-level passes absolute paths; the manifest
        on disk must carry neither a leading '/' nor a '/Users/' segment."""
        from omsorgsradar.core.contracts import REPO_ROOT, read_manifest

        data_dir = REPO_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        art = data_dir / "_finding5_probe.json"
        art.write_text('{"probe": 1}', encoding="utf-8")
        try:
            inp = REPO_ROOT / "data" / "quality_profile.json"
            write_manifest(
                art, artifact="findings", producer="analyze", inputs=[str(inp)]
            )
            m = read_manifest(art)
            assert not m.path.startswith("/"), f"leaked absolute path: {m.path}"
            assert "/Users/" not in m.path, f"leaked user path: {m.path}"
            assert m.path == "data/_finding5_probe.json", m.path
            for i in m.inputs:
                assert not i.startswith("/") and "/Users/" not in i, i
            assert m.inputs == ["data/quality_profile.json"], m.inputs
        finally:
            art.unlink(missing_ok=True)
            (art.with_name(art.name + ".manifest.json")).unlink(missing_ok=True)

    def test_path_outside_repo_falls_back_to_basename(self, tmp_path: Path) -> None:
        """An artifact path outside the repo root (no relative_to) falls back to
        the basename, never leaking the absolute directory."""
        from omsorgsradar.core.contracts import read_manifest

        art = tmp_path / "outside.json"
        art.write_text('{"x": 1}', encoding="utf-8")
        write_manifest(art, artifact="findings", producer="analyze")
        m = read_manifest(art)
        assert m.path == "outside.json", m.path
        assert "/Users/" not in m.path


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


class TestRegisterSchema:
    DUMMY = {"type": "object", "required": ["x"],
             "properties": {"x": {"type": "integer"}}}

    def test_register_validate_roundtrip(self) -> None:
        from omsorgsradar.core.contracts import (
            ArtifactValidationError, SCHEMAS, register_schema, validate_artifact,
        )
        try:
            register_schema("g2_dummy", self.DUMMY)
            validate_artifact("g2_dummy", {"x": 1})
            with pytest.raises(ArtifactValidationError):
                validate_artifact("g2_dummy", {"x": "nope"})
        finally:
            SCHEMAS.pop("g2_dummy", None)

    def test_identical_reregistration_is_idempotent(self) -> None:
        from omsorgsradar.core.contracts import SCHEMAS, register_schema
        try:
            register_schema("g2_dummy", self.DUMMY)
            register_schema("g2_dummy", self.DUMMY)  # extension reload — no raise
        finally:
            SCHEMAS.pop("g2_dummy", None)

    def test_conflicting_reregistration_raises(self) -> None:
        from omsorgsradar.core.contracts import SCHEMAS, register_schema
        try:
            register_schema("g2_dummy", self.DUMMY)
            with pytest.raises(ValueError, match="already registered"):
                register_schema("g2_dummy", {"type": "object"})
        finally:
            SCHEMAS.pop("g2_dummy", None)

    def test_core_schema_protected(self) -> None:
        from omsorgsradar.core.contracts import register_schema
        with pytest.raises(ValueError, match="already registered"):
            register_schema("findings", {"type": "object"})
