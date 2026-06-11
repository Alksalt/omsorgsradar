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
