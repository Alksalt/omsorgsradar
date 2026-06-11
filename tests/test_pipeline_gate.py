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
