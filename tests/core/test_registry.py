"""Stage registry, verify-before-report rule, instance extension loading."""

from pathlib import Path

import pytest

from omsorgsradar.core.registry import (
    PipelineGateError,
    StageNotFoundError,
    StageRegistry,
    load_extensions,
    resolve_stage_list,
)


def _noop(ctx) -> None:  # minimal StageFn
    pass


class TestRegistry:
    def test_register_and_get(self) -> None:
        r = StageRegistry()
        r.register("profile", _noop)
        assert r.get("profile") is _noop

    def test_duplicate_without_override_rejected(self) -> None:
        r = StageRegistry()
        r.register("profile", _noop)
        with pytest.raises(ValueError, match="override"):
            r.register("profile", _noop)

    def test_override_shadows(self) -> None:
        def other(ctx) -> None:
            pass

        r = StageRegistry()
        r.register("profile", _noop)
        r.register("profile", other, override=True)
        assert r.get("profile") is other

    def test_unknown_stage_lists_known(self) -> None:
        r = StageRegistry()
        r.register("profile", _noop)
        with pytest.raises(StageNotFoundError, match="profile"):
            r.get("nope")


class TestResolveStageList:
    def test_verify_inserted_before_report(self) -> None:
        assert resolve_stage_list(["ingest", "report"]) == ["ingest", "verify", "report"]

    def test_misordered_verify_moved(self) -> None:
        assert resolve_stage_list(["report", "verify"]) == ["verify", "report"]

    def test_correct_order_untouched(self) -> None:
        stages = ["ingest", "analyze", "verify", "report"]
        assert resolve_stage_list(stages) == stages

    def test_no_report_no_change(self) -> None:
        assert resolve_stage_list(["ingest", "ml"]) == ["ingest", "ml"]


class TestExtensions:
    def test_missing_stages_py_is_fine(self, tmp_path: Path) -> None:
        r = StageRegistry()
        assert load_extensions(tmp_path, r) is False

    def test_extension_registers_shadow(self, tmp_path: Path) -> None:
        (tmp_path / "stages.py").write_text(
            "def my_report(ctx):\n"
            "    ctx.state['custom_report'] = True\n"
            "\n"
            "def register(registry):\n"
            "    registry.register('report', my_report, override=True)\n",
            encoding="utf-8",
        )
        r = StageRegistry()
        r.register("report", _noop)
        assert load_extensions(tmp_path, r) is True
        assert r.get("report") is not _noop

    def test_extension_without_register_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "stages.py").write_text("X = 1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="register"):
            load_extensions(tmp_path, StageRegistry())
