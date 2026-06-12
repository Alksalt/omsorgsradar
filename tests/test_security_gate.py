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
        # journal uses "stage" key (not "name") — verified from journal.py
        assert [s["stage"] for s in run["stages"]] == ["ingest", "profile"]
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
