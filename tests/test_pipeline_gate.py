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


class TestRealnessGate:
    def _analysis_dir(self, tmp_path):
        adir = tmp_path / "analyses" / "fabricated"
        adir.mkdir(parents=True)
        rows = "\n".join("NO-0301,2020,7.0" for _ in range(200))
        (adir / "fake.csv").write_text("geo_id,aar,value\n" + rows + "\n")
        (adir / "analysis.toml").write_text(
            '[analysis]\nname = "fabricated"\n'
            '[stages]\nlist = ["ingest", "profile"]\n'
            '[[sources]]\nadapter = "csv"\nid = "fake"\npath = "fake.csv"\n'
            '[sources.provenance]\ninstitution = "Test"\nurl = "https://example.org"\n',
            encoding="utf-8",
        )
        return adir

    def test_fabricated_csv_aborts_after_publishing_verdict(self, tmp_path) -> None:
        import json
        import pytest
        from omsorgsradar.core.registry import PipelineGateError
        from omsorgsradar.pipeline import run_pipeline

        adir = self._analysis_dir(tmp_path)
        data_dir = tmp_path / "data"
        with pytest.raises(PipelineGateError, match="realness"):
            run_pipeline(
                adir,
                data_dir=data_dir,
                reports_dir=tmp_path / "reports",
                runs_dir=tmp_path / "runs",
            )
        # Verdict was published before the abort (spec: verdict in the profile)
        quality = json.loads((data_dir / "quality_profile.json").read_text())
        assert quality["datasets"]["fake"]["realness"]["verdict"] == "FAIL"
        # 200 identical duplicated rows + zero variance triggered it
        statuses = {c["name"]: c["status"]
                    for c in quality["datasets"]["fake"]["realness"]["checks"]}
        assert statuses["duplicates"] == "FAIL"
        assert statuses["distribution"] == "FAIL"
