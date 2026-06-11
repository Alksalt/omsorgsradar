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
