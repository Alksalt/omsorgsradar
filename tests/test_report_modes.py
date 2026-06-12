"""Tests: report stage consumes execution-mode config (G5 Task 3)."""
from pathlib import Path

import pytest

from omsorgsradar.analyze import run_analysis
from omsorgsradar.report import run_report
from omsorgsradar.core import endpoint as ep


@pytest.fixture()
def result(fixture_datasets):
    return run_analysis(
        df_kostra=fixture_datasets["kostra_pleie"],
        df_pop=fixture_datasets["befolkning"],
        df_proj=fixture_datasets.get("framskrivinger"),
    )


class TestReportModes:
    def test_subscription_uses_template(self, tmp_path, result, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-ignored")
        wf = {"endpoint": {"mode": "subscription"}, "models": {"report": "claude-fable-5"}}
        path, cost = run_report(result, report_dir=tmp_path, workflow=wf)
        assert cost["renderer"] == "template"
        assert Path(path).exists()

    def test_local_mode_round_trip(self, tmp_path, result, monkeypatch):
        monkeypatch.setattr(
            ep.AnthropicClient, "_sdk_create",
            lambda self, **kw: type("M", (), {
                "content": [type("B", (), {"text": "LOKAL NARRASJON"})()],
                "usage": type("U", (), {"input_tokens": 10, "output_tokens": 5})(),
            })(),
        )
        wf = {"endpoint": {"mode": "local", "local": {"base_url": "http://localhost:1234"}},
              "models": {"report": "local-model"}}
        path, cost = run_report(result, report_dir=tmp_path, workflow=wf)
        assert "LOKAL NARRASJON" in Path(path).read_text(encoding="utf-8")
        assert cost["renderer"] == "llm"
        assert cost["model"] == "local-model"

    def test_api_no_key_falls_back_to_template(self, tmp_path, result, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        wf = {"endpoint": {"mode": "api", "api": {"provider": "anthropic"}},
              "models": {"report": "claude-fable-5"}}
        path, cost = run_report(result, report_dir=tmp_path, workflow=wf)
        assert cost["renderer"] == "template"

    def test_legacy_no_workflow_is_template(self, tmp_path, result):
        path, cost = run_report(result, report_dir=tmp_path)
        assert cost["renderer"] in ("template", "template_fallback")
