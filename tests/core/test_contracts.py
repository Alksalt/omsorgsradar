"""Artifact manifests + schema validation at stage boundaries."""

from pathlib import Path

import pytest

from omsorgsradar.core.contracts import (
    read_manifest,
    sha256_of,
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
