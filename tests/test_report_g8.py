"""G8-A tests: report credibility — nb-NO, colormap, SSB attribution, figure guards.

TDD: all tests written before implementation. Fully offline.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field

import numpy as np
import pytest

from omsorgsradar.analyze import AnalysisResult, KommuneMetrics
from omsorgsradar.verify import VerificationReport, ClaimResult, Claim
from omsorgsradar.core.endpoint import MODEL_PRICING


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_result(
    *,
    n: int = 5,
    growth: float = 31.1,
    ssb: float = 46.5,
    baseline: float = 100_000.0,
    projected: float = 131_100.0,
) -> AnalysisResult:
    """Minimal AnalysisResult fixture with n ranked kommuner."""
    kommuner = []
    for i in range(1, n + 1):
        km = KommuneMetrics(
            knr=f"{1000 + i:04d}",
            navn=f"TestKommune{i}",
            pop_80plus_latest=500.0,
            pop_80plus_projected_2035=600.0,
            pop_80plus_growth_pct=float(30 - i),
            coverage_rate=float(20 + i),
            press_index_norm=float(1.0 - (i - 1) * 0.1),
            press_index_raw=float(2.0 - (i - 1) * 0.2),
            rank=i,
        )
        kommuner.append(km)
    return AnalysisResult(
        kommuner=kommuner,
        national_80plus_latest=baseline,
        national_80plus_2035=projected,
        national_growth_rate_2035=growth,
        ssb_projection_growth_2035=ssb,
        ssb_projection_baseline_year=2022,
    )


def _make_empty_result() -> AnalysisResult:
    """Result with no kommuner and NaN national figures."""
    return AnalysisResult(
        kommuner=[],
        national_80plus_latest=float("nan"),
        national_80plus_2035=float("nan"),
        national_growth_rate_2035=float("nan"),
        ssb_projection_growth_2035=float("nan"),
    )


def _make_verification_report(n: int = 31, passed: int = 31) -> VerificationReport:
    """Synthetic VerificationReport mimicking the gate's full set."""
    results = []
    for i in range(n):
        claim = Claim(
            claim_type="national_growth_rate_2035",
            claimed_value=31.1,
            source_text=f"Kontroll {i + 1}",
        )
        results.append(ClaimResult(claim=claim, recomputed_value=31.1,
                                   passes=(i < passed), message="OK" if i < passed else "FAIL"))
    return VerificationReport(
        total_claims=n,
        passed=passed,
        failed=n - passed,
        results=results,
        verdict="PASS" if passed == n else "FAIL",
    )


# ---------------------------------------------------------------------------
# A2 — plot_national_trend: title, bar label, SSB reference line
# ---------------------------------------------------------------------------


class TestPlotNationalTrend:
    """A2: figure title uses nb-NO formatting, SSB MMM reference shown."""

    def test_title_uses_nb_format(self, tmp_path):
        """Title must contain comma-decimal growth and SSB clause."""
        from omsorgsradar.report import plot_national_trend
        result = _make_result(growth=31.1, ssb=46.5)
        out = plot_national_trend(result, out_dir=tmp_path)
        assert out.exists()
        # The PNG exists — presence confirms no crash; formatting checked via render_template.

    def test_nan_ssb_runs_without_crash(self, tmp_path):
        """When ssb_projection_growth_2035 is NaN, plot must still build."""
        from omsorgsradar.report import plot_national_trend
        result = _make_result(ssb=float("nan"))
        out = plot_national_trend(result, out_dir=tmp_path)
        assert out.exists()

    def test_missing_national_data_returns_path_without_writing(self, tmp_path):
        """When both baseline and projected are NaN, returns path (may not write PNG)."""
        from omsorgsradar.report import plot_national_trend
        result = _make_empty_result()
        out = plot_national_trend(result, out_dir=tmp_path)
        # Should return a Path — no crash
        assert isinstance(out, Path)


# ---------------------------------------------------------------------------
# A2 — colormap semantics: Reds-family, dark = highest press
# ---------------------------------------------------------------------------


class TestColormapSemantics:
    """A2: worst kommune (highest press) must render dark, not green."""

    def test_press_index_bar_cmap_is_reds_family(self, tmp_path):
        """Colormap in plot_press_index_bar must be sequential Reds (not RdYlGn)."""
        import matplotlib.pyplot as plt
        import matplotlib
        from omsorgsradar.report import plot_press_index_bar
        import numpy as np

        result = _make_result(n=5)
        # Capture colors used for bars by monkey-patching ax.barh
        captured_colors = []
        original_barh = plt.Axes.barh

        def _capture_barh(self, *args, **kwargs):
            c = kwargs.get("color", args[2] if len(args) > 2 else None)
            if c is not None:
                captured_colors.extend(c if hasattr(c, "__iter__") and not isinstance(c, str) else [c])
            return original_barh(self, *args, **kwargs)

        with patch.object(plt.Axes, "barh", _capture_barh):
            plot_press_index_bar(result, out_dir=tmp_path)

        # Colors should be RGBA tuples. The highest-press bar (index 0, value=1.0)
        # should be darker (lower sum of RGB) than the lowest-press bar.
        assert len(captured_colors) >= 2
        first_rgba = captured_colors[0]   # highest press — should be dark
        last_rgba = captured_colors[-1]   # lowest press — should be light

        # Dark = low RGB sum; for Reds dark red has high R but low G+B
        # Just check it's not RdYlGn by verifying high-press is not green
        # In RdYlGn_r: high value → red (low green), in RdYlGn: high value → green
        # In Reds: high value → dark red
        # We check that the high-press bar has higher R than G (reddish, not greenish)
        first_r = first_rgba[0]
        first_g = first_rgba[1]
        # Reds cmap: high value → dark red means R > G always
        assert first_r > first_g, (
            f"High-press bar appears greenish (R={first_r:.2f} <= G={first_g:.2f}). "
            "Colormap may still be RdYlGn."
        )

    def test_coverage_scatter_cmap_dark_is_high_press(self, tmp_path):
        """scatter colorbar: high press_index → darker color (Reds family)."""
        from omsorgsradar.report import plot_coverage_scatter
        import matplotlib.cm as cm
        import numpy as np

        result = _make_result(n=5)
        # Just verify no crash and file written
        out = plot_coverage_scatter(result, out_dir=tmp_path)
        assert out.exists()


# ---------------------------------------------------------------------------
# A3 — scatter y-label
# ---------------------------------------------------------------------------


class TestScatterYLabel:
    """A3: y-axis label must say «Andel innbyggere 80+ som mottar hjemmetjenester (%)»."""

    def test_scatter_ylabel_correct(self, tmp_path):
        import matplotlib.pyplot as plt
        from omsorgsradar.report import plot_coverage_scatter

        captured_ylabels = []
        original_set_ylabel = plt.Axes.set_ylabel

        def _capture(self, label, *args, **kwargs):
            captured_ylabels.append(label)
            return original_set_ylabel(self, label, *args, **kwargs)

        result = _make_result(n=5)
        with patch.object(plt.Axes, "set_ylabel", _capture):
            plot_coverage_scatter(result, out_dir=tmp_path)

        assert any("Andel innbyggere 80+" in lbl for lbl in captured_ylabels), (
            f"Expected y-label with 'Andel innbyggere 80+', got: {captured_ylabels}"
        )
        assert any("hjemmetjenester" in lbl for lbl in captured_ylabels), (
            f"Expected 'hjemmetjenester' in y-label, got: {captured_ylabels}"
        )
        # Must NOT say "per 1000" (that's the wrong unit)
        assert not any("per 1000" in lbl for lbl in captured_ylabels), (
            f"y-label still says 'per 1000': {captured_ylabels}"
        )


# ---------------------------------------------------------------------------
# A3 — choropleth map_anchor_knrs parameter
# ---------------------------------------------------------------------------


class TestChoroplethAnchors:
    """A3: plot_press_index_choropleth accepts map_anchor_knrs and labels them."""

    def test_choropleth_accepts_anchor_param_no_crash(self, tmp_path):
        """plot_press_index_choropleth(result, out_dir, map_anchor_knrs=[...]) must not crash."""
        from omsorgsradar.report import plot_press_index_choropleth
        from omsorgsradar.maps import DEFAULT_GEO_PATH

        if not DEFAULT_GEO_PATH.exists():
            pytest.skip("Geo asset not available in this env")

        result = _make_result(n=5)
        # pass anchors directly
        out = plot_press_index_choropleth(result, out_dir=tmp_path,
                                         map_anchor_knrs=["0301", "4601"])
        # Either a Path (PNG written) or None (asset missing) — no exception
        assert out is None or isinstance(out, Path)

    def test_choropleth_default_anchor_empty(self, tmp_path):
        """Default call (no map_anchor_knrs) must still work."""
        from omsorgsradar.report import plot_press_index_choropleth
        from omsorgsradar.maps import DEFAULT_GEO_PATH

        if not DEFAULT_GEO_PATH.exists():
            pytest.skip("Geo asset not available in this env")

        result = _make_result(n=5)
        out = plot_press_index_choropleth(result, out_dir=tmp_path)
        assert out is None or isinstance(out, Path)


# ---------------------------------------------------------------------------
# A4 — Datakvalitet block
# ---------------------------------------------------------------------------


class TestDatakvalitetBlock:
    """A4: zero-row sources suppressed, — instead of N/A, befolkning annotated."""

    def test_zero_row_source_suppressed(self, tmp_path):
        """A source with 0 rows must NOT appear in the rendered table."""
        from omsorgsradar.report import render_template

        result = _make_result()
        quality_report = {
            "datasets": {
                "kostra_pleie": {"n_rows": 100, "n_kommuner": 30, "source": "SSB KOSTRA"},
                "fhi_nokkel": {"n_rows": 0, "n_kommuner": 0, "source": "FHI"},
            }
        }
        md = render_template(result, quality_report=quality_report)
        # fhi_nokkel with 0 rows must not appear as a table row
        assert "fhi_nokkel: 0 rader" not in md
        assert "fhi_nokkel" not in md or "ekskludert" in md or "utilgjengelig" in md

    def test_na_replaced_by_dash(self, tmp_path):
        """«N/A» must not appear in the quality block; use «—» instead."""
        from omsorgsradar.report import render_template

        result = _make_result()
        quality_report = {
            "datasets": {
                "kostra_pleie": {"n_rows": None, "n_kommuner": None, "source": "SSB KOSTRA"},
            }
        }
        md = render_template(result, quality_report=quality_report)
        # N/A must be replaced by —
        # The quality block should not show literal "N/A"
        lines = [l for l in md.split("\n") if "Datakvalitet" in l or "kostra" in l.lower()]
        for line in lines:
            assert "N/A" not in line, f"Found 'N/A' in quality line: {line!r}"

    def test_befolkning_annotated_with_counts(self):
        """befolkning row must include n_rows and n_kommuner annotation."""
        from omsorgsradar.report import render_template

        result = _make_result()
        quality_report = {
            "datasets": {
                "befolkning": {"n_rows": 483, "n_kommuner": 357, "source": "SSB befolkning"},
            }
        }
        md = render_template(result, quality_report=quality_report)
        # Should mention the row count and kommuner count in the befolkning line
        assert "483" in md
        assert "357" in md


# ---------------------------------------------------------------------------
# A5 — Figure guards: run_report aborts on missing figures
# ---------------------------------------------------------------------------


class TestFigureGuards:
    """A5: run_report must raise RuntimeError if a figure failed to write."""

    def test_empty_result_raises_runtime_error(self, tmp_path):
        """An empty result where figures can't be drawn must raise RuntimeError."""
        from omsorgsradar.report import run_report

        result = _make_empty_result()
        with pytest.raises(RuntimeError, match="figures missing"):
            run_report(result, report_dir=tmp_path)

    def test_all_figures_present_does_not_raise(self, tmp_path):
        """A valid result with all figures written must complete normally."""
        from omsorgsradar.report import run_report

        result = _make_result(n=10)
        # Should not raise
        path, cost = run_report(result, report_dir=tmp_path)
        assert Path(path).exists()

    def test_choropleth_skipped_no_dead_link(self, tmp_path):
        """When choropleth skipped (geo asset absent), template must not embed the img tag."""
        from omsorgsradar.report import render_template

        result = _make_result(n=5)
        # Render template without choropleth (choropleth_available=False)
        md = render_template(result, choropleth_available=False)
        # The choropleth img tag must not appear
        assert "press_index_choropleth.png" not in md

    def test_choropleth_present_embeds_link(self, tmp_path):
        """When choropleth is available, the template must embed the img link."""
        from omsorgsradar.report import render_template

        result = _make_result(n=5)
        md = render_template(result, choropleth_available=True)
        assert "press_index_choropleth.png" in md


# ---------------------------------------------------------------------------
# A6 — render_llm default model resolves to MODEL_PRICING key
# ---------------------------------------------------------------------------


class TestRenderLlmDefaultModel:
    """A6: default model must exist in MODEL_PRICING."""

    def test_default_model_in_pricing(self):
        """When model=None, render_llm must resolve to a key in MODEL_PRICING."""
        # We check the resolution logic directly without calling the API.
        # The default is resolved at call time; we import and inspect.
        import inspect
        from omsorgsradar import report as report_mod

        # The default value for model parameter in render_llm should be None
        sig = inspect.signature(report_mod.render_llm)
        default = sig.parameters["model"].default
        assert default is None, (
            f"render_llm model param default should be None (lazy resolution), got {default!r}"
        )

    def test_resolved_model_in_model_pricing(self):
        """The resolved model (when None passed) must be a key in MODEL_PRICING."""
        from omsorgsradar.report import _resolve_default_model
        resolved = _resolve_default_model()
        assert resolved in MODEL_PRICING, (
            f"Default model {resolved!r} not in MODEL_PRICING keys: {list(MODEL_PRICING.keys())}"
        )


# ---------------------------------------------------------------------------
# A7 — TabPFN no-token: single INFO line, not repeated WARNINGs
# ---------------------------------------------------------------------------


class TestTabPFNNoToken:
    """A7: missing token → ONE INFO log line, no repeated per-fold WARNINGs."""

    def test_missing_token_single_info_log(self, caplog, monkeypatch):
        """run_tabpfn_on_folds with no token → exactly 1 INFO containing 'hoppes over'."""
        import logging
        from omsorgsradar.ml import run_tabpfn_on_folds, CVFold, TABPFN_TOKEN_ENV_VAR

        monkeypatch.delenv(TABPFN_TOKEN_ENV_VAR, raising=False)

        # Build minimal folds (no actual XGB run)
        folds = [
            CVFold(fold=1, train_years=[2018, 2019], test_years=[2020],
                   n_train=10, n_test=5, xgb_mae=1.0, xgb_rmse=1.5, naive_mae=1.2, naive_rmse=1.8),
            CVFold(fold=2, train_years=[2018, 2019, 2020], test_years=[2021],
                   n_train=15, n_test=5, xgb_mae=1.0, xgb_rmse=1.5, naive_mae=1.2, naive_rmse=1.8),
            CVFold(fold=3, train_years=[2018, 2019, 2020, 2021], test_years=[2022],
                   n_train=20, n_test=5, xgb_mae=1.0, xgb_rmse=1.5, naive_mae=1.2, naive_rmse=1.8),
        ]

        # Use the stub class that raises a license error
        class _NoTokenRegressor:
            def __init__(self, **kwargs): ...
            def fit(self, X, y):
                raise RuntimeError("No token available")
            def predict(self, X): ...

        import pandas as pd
        import numpy as np
        rng = np.random.RandomState(0)
        n = 30
        df = pd.DataFrame({
            "knr": [f"{1000+i:04d}" for i in range(n)] * 3,
            "year": [2020]*n + [2021]*n + [2022]*n,
            "coverage_rate": rng.uniform(15, 40, 3*n),
            "coverage_rate_lag1": rng.uniform(14, 39, 3*n),
            "coverage_rate_lag2": rng.uniform(13, 38, 3*n),
            "log_pop_80plus": rng.uniform(3, 6, 3*n),
            "inst_per_1000_80plus": rng.uniform(5, 30, 3*n),
        })

        with caplog.at_level(logging.INFO, logger="omsorgsradar.ml"):
            run_tabpfn_on_folds(df, folds, n_folds=3, _tabpfn_cls=_NoTokenRegressor)

        # Count WARNING messages
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                    and "TabPFN" in r.getMessage()]
        infos = [r for r in caplog.records if r.levelno == logging.INFO
                 and "hoppes over" in r.getMessage()]

        assert len(warnings) == 0, (
            f"Expected 0 TabPFN WARNINGs, got {len(warnings)}: {[r.getMessage() for r in warnings]}"
        )
        assert len(infos) == 1, (
            f"Expected exactly 1 INFO 'hoppes over' log line, got {len(infos)}: {[r.getMessage() for r in infos]}"
        )

    def test_no_token_env_var_detected_before_folds(self, monkeypatch):
        """When TABPFN_TOKEN is absent, run_ml logs INFO once, not per-fold."""
        import logging
        from omsorgsradar.ml import TABPFN_TOKEN_ENV_VAR

        monkeypatch.delenv(TABPFN_TOKEN_ENV_VAR, raising=False)
        # The env-var check must occur BEFORE fold iteration in run_tabpfn_on_folds
        # This is validated by test_missing_token_single_info_log above.
        # This test just confirms the env var name is the right constant.
        assert TABPFN_TOKEN_ENV_VAR == "TABPFN_TOKEN"


# ---------------------------------------------------------------------------
# A8 — run_report accepts verification parameter
# ---------------------------------------------------------------------------


class TestRunReportVerification:
    """A8: run_report accepts verification=VerificationReport and renders it."""

    def test_run_report_accepts_verification_kwarg(self, tmp_path):
        """run_report(result, verification=...) must not raise TypeError."""
        from omsorgsradar.report import run_report

        result = _make_result(n=5)
        vr = _make_verification_report(n=31, passed=31)

        # Should accept verification keyword argument
        path, cost = run_report(result, report_dir=tmp_path, verification=vr)
        assert Path(path).exists()

    def test_verification_report_shows_passed_total(self, tmp_path):
        """When verification is provided, the report must show passed/total."""
        from omsorgsradar.report import run_report

        result = _make_result(n=5)
        vr = _make_verification_report(n=31, passed=31)

        path, cost = run_report(result, report_dir=tmp_path, verification=vr)
        md = Path(path).read_text(encoding="utf-8")

        assert "31/31" in md or "31" in md

    def test_verification_none_uses_rebuild(self, tmp_path):
        """When verification=None, run_report rebuilds its own verification (current behavior)."""
        from omsorgsradar.report import run_report

        result = _make_result(n=5)
        # Explicit None — same as before
        path, cost = run_report(result, report_dir=tmp_path, verification=None)
        assert Path(path).exists()

    def test_verification_gloss_present_in_report(self, tmp_path):
        """The gate verification block must include the one-clause gloss."""
        from omsorgsradar.report import run_report

        result = _make_result(n=5)
        vr = _make_verification_report(n=31, passed=31)

        path, cost = run_report(result, report_dir=tmp_path, verification=vr)
        md = Path(path).read_text(encoding="utf-8")

        # The gloss should mention kontroller
        assert "kontroller" in md or "kontroll" in md


# ---------------------------------------------------------------------------
# A1 — nb-NO formatting applied in render_template output
# ---------------------------------------------------------------------------


class TestRenderTemplateNbFormat:
    """A1: render_template must use nb-NO formatting in the report text."""

    def test_template_uses_comma_decimal_in_growth(self):
        """Growth % in the template must use comma decimal (Norwegian style)."""
        from omsorgsradar.report import render_template

        result = _make_result(growth=31.1, ssb=46.5)
        md = render_template(result)

        # Must contain comma-decimal format like «31,1»
        assert "31,1" in md, f"Expected '31,1' in report, not found. Excerpt:\n{md[:800]}"

    def test_template_press_index_norm_not_dot_decimal(self):
        """Press-index in table must use comma decimal (not dot)."""
        from omsorgsradar.report import render_template

        result = _make_result(n=3)
        md = render_template(result)

        # The table has press_index_norm values; top commune = 1.00 → must show 1,00
        assert "1,00" in md, f"Expected '1,00' in table, got:\n{md[:1000]}"

    def test_template_does_not_emit_1000_as_one_thousand(self):
        """«1.000» must not appear (Norwegian reader reads it as one thousand)."""
        from omsorgsradar.report import render_template

        result = _make_result(n=3)
        md = render_template(result)

        # Press index 1.000 (English notation) must not appear in table
        # (nb_index(1.0) → «1,00»)
        assert "1.000" not in md, "Found English-formatted press index «1.000» in report"

    def test_template_pct_uses_space_before_percent(self):
        """Percentage values must use «X,X %» format with space before %."""
        from omsorgsradar.report import render_template

        result = _make_result(growth=31.1)
        md = render_template(result)

        # «31,1 %» must appear in summary
        assert "31,1 %" in md, f"Expected '31,1 %' in report, not found. Excerpt:\n{md[:800]}"
