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


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestCanonicalConfigs:
    """The committed config files must always validate."""

    def test_workflow_toml_valid(self) -> None:
        cfg = load_workflow_config(REPO_ROOT / "workflow.toml")
        assert cfg["endpoint"]["mode"] in ("subscription", "api", "local")

    def test_omsorgsradar_analysis_valid(self) -> None:
        cfg = load_run_config(
            REPO_ROOT / "analyses" / "omsorgsradar", REPO_ROOT / "workflow.toml"
        )
        assert cfg.name == "omsorgsradar"
        assert cfg.stage_list[0] == "ingest"
        ids = [s["id"] for s in cfg.sources]
        assert ids == ["kostra_pleie", "befolkning", "framskrivinger", "fhi_nokkel"]


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


class TestEndpointSecurity:
    def _wf(self, tmp_path, body: str):
        p = tmp_path / "workflow.toml"
        p.write_text(body, encoding="utf-8")
        return p

    def test_api_key_in_toml_rejected(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config, ConfigError
        import pytest
        body = ('[endpoint]\nmode = "api"\n[endpoint.api]\nprovider = "anthropic"\n'
                'api_key = "sk-leak"\n')
        with pytest.raises(ConfigError, match="key material"):
            load_workflow_config(self._wf(tmp_path, body))

    def test_secret_named_field_anywhere_rejected(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config, ConfigError
        import pytest
        body = '[endpoint]\nmode = "subscription"\n[models]\ntoken = "x"\n'
        with pytest.raises(ConfigError, match="key material"):
            load_workflow_config(self._wf(tmp_path, body))

    def test_unknown_endpoint_field_rejected(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config, ConfigError
        import pytest
        body = '[endpoint]\nmode = "subscription"\nflavour = "x"\n'
        with pytest.raises(ConfigError):
            load_workflow_config(self._wf(tmp_path, body))

    def test_local_api_flavor_allowed(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config
        body = ('[endpoint]\nmode = "local"\n[endpoint.local]\n'
                'base_url = "http://localhost:1234"\napi = "openai"\n')
        cfg = load_workflow_config(self._wf(tmp_path, body))
        assert cfg["endpoint"]["local"]["api"] == "openai"

    def test_api_base_url_allowed(self, tmp_path):
        from omsorgsradar.core.config import load_workflow_config
        body = ('[endpoint]\nmode = "api"\n[endpoint.api]\n'
                'provider = "openrouter"\nbase_url = "https://openrouter.ai/api/v1"\n')
        cfg = load_workflow_config(self._wf(tmp_path, body))
        assert cfg["endpoint"]["api"]["provider"] == "openrouter"
