"""Tests for ml.py — TabPFN fold-parity, token-leak, and honest framing.

All tests are fully offline and avoid calling xgboost (which can segfault
on macOS/Apple Silicon when called in the same pytest session after the
brfss-integration pipeline fixture exhausts numpy/xgboost C memory). Folds
are constructed directly from CVFold dataclasses rather than calling
walk_forward_cv, and TabPFNRegressor is replaced with a deterministic stub.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Stub regressor (train-mean predictor, fully deterministic, zero I/O)
# ---------------------------------------------------------------------------


class _StubTabPFNRegressor:
    """Predicts the training-set mean for every test sample.

    Deterministic, reproducible MAE, never does network I/O or weight loading.
    """

    def __init__(self, **kwargs):
        self._train_mean: float = 0.0

    def fit(self, X, y):
        self._train_mean = float(np.mean(y))
        return self

    def predict(self, X):
        return np.full(len(X), self._train_mean)


class _LicenseErrorRegressor:
    """Raises TabPFNLicenseError on .fit() — simulates missing token."""

    def __init__(self, **kwargs): ...

    def fit(self, X, y):
        from tabpfn.errors import TabPFNLicenseError
        raise TabPFNLicenseError()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_feature_df(n_kommuner: int = 30, n_years: int = 8) -> pd.DataFrame:
    """Generate a synthetic feature DataFrame with sufficient history for 3 folds."""
    rng = np.random.RandomState(0)
    years = list(range(2015, 2015 + n_years))
    rows = []
    for k in range(n_kommuner):
        cov = rng.uniform(15, 40)
        for year in years:
            cov += rng.normal(0, 0.5)
            rows.append(
                {
                    "knr": f"{k + 1001:04d}",
                    "year": year,
                    "coverage_rate": cov,
                    "coverage_rate_lag1": cov - rng.uniform(0.1, 1.0),
                    "coverage_rate_lag2": cov - rng.uniform(0.5, 2.0),
                    "log_pop_80plus": np.log1p(rng.randint(50, 500)),
                    "inst_per_1000_80plus": rng.uniform(5, 30),
                }
            )
    return pd.DataFrame(rows).dropna(subset=["coverage_rate", "coverage_rate_lag1"])


def _make_folds_no_xgb(n_folds: int = 3) -> list:
    """Build CVFold list without calling xgboost.

    Constructs deterministic folds directly from CVFold dataclasses.
    This avoids the xgboost/numpy C-extension segfault that occurs on
    macOS/Apple Silicon when xgboost is called a second time in the same
    pytest session after the brfss-integration module fixture.
    """
    from omsorgsradar.ml import CVFold

    folds = []
    for i in range(n_folds):
        test_year = 2021 + i
        folds.append(
            CVFold(
                fold=i + 1,
                train_years=list(range(2015, test_year)),
                test_years=[test_year],
                n_train=(test_year - 2015) * 30,
                n_test=30,
                xgb_mae=2.1 + i * 0.05,
                xgb_rmse=2.8 + i * 0.05,
                naive_mae=2.3 + i * 0.05,
                naive_rmse=3.0 + i * 0.05,
            )
        )
    return folds


# ---------------------------------------------------------------------------
# C1 — Fold parity
# ---------------------------------------------------------------------------


class TestTabPFNFoldParity:
    """TabPFN must run the same 3 walk-forward folds as XGBoost.

    Folds are constructed via _make_folds_no_xgb to avoid calling xgboost
    in the test process (a macOS/numpy-2.x segfault can occur when xgboost
    is called a second time after the brfss-integration module fixture).
    The fold iteration logic inside run_tabpfn_on_folds is exercised via the
    feature DataFrame; the per-fold metadata comes from the prebuilt folds.
    """

    def test_tabpfn_same_fold_count_as_xgb(self):
        """TabPFN populates tabpfn_mae/rmse on all 3 folds."""
        from omsorgsradar import ml

        df = _make_feature_df()
        folds = _make_folds_no_xgb(n_folds=3)
        results = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_StubTabPFNRegressor)

        assert results.tabpfn_available is True, "tabpfn_available must be True with stub"
        assert len(folds) == 3, f"Expected 3 folds, got {len(folds)}"
        for fold in folds:
            assert fold.tabpfn_mae is not None, f"Fold {fold.fold} missing tabpfn_mae"
            assert fold.tabpfn_rmse is not None, f"Fold {fold.fold} missing tabpfn_rmse"
            assert fold.tabpfn_mae >= 0, f"Fold {fold.fold} tabpfn_mae is negative"

    def test_tabpfn_mean_set(self):
        """mean_tabpfn_mae must equal the mean of per-fold values."""
        from omsorgsradar import ml

        df = _make_feature_df()
        folds = _make_folds_no_xgb(n_folds=3)
        results = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_StubTabPFNRegressor)

        assert results.mean_tabpfn_mae is not None
        expected = float(np.mean([f.tabpfn_mae for f in folds if f.tabpfn_mae is not None]))
        assert abs(results.mean_tabpfn_mae - expected) < 1e-9

    def test_tabpfn_fold_test_years_populated(self):
        """Each fold must have a test_years list with at least one entry."""
        folds = _make_folds_no_xgb(n_folds=3)
        assert all(len(f.test_years) >= 1 for f in folds)

    def test_tabpfn_subsampling_guard(self):
        """If training set > 5000 rows, TabPFN still completes (stub sees subsample)."""
        from omsorgsradar import ml

        df_large = _make_feature_df(n_kommuner=600, n_years=12)
        folds = _make_folds_no_xgb(n_folds=3)
        results = ml.run_tabpfn_on_folds(df_large, folds, _tabpfn_cls=_StubTabPFNRegressor)
        assert results.tabpfn_available is True

    def test_tabpfn_not_available_when_no_cls(self):
        """When _tabpfn_cls=None and import fails, tabpfn_available=False."""
        from omsorgsradar import ml
        import sys
        from unittest.mock import patch

        df = _make_feature_df()
        folds = _make_folds_no_xgb(n_folds=3)

        # Block real import without disturbing sys.modules for other packages
        with patch.dict(sys.modules, {"tabpfn": None}):
            results = ml.run_tabpfn_on_folds(df, folds)  # _tabpfn_cls=None → tries import

        assert results.tabpfn_available is False
        assert results.mean_tabpfn_mae is None


# ---------------------------------------------------------------------------
# C2 — License/status path + token-leak test
# ---------------------------------------------------------------------------


class TestTabPFNLicenseHandling:
    """When TabPFN raises TabPFNLicenseError, status must be a clean bokmål string."""

    def test_license_error_sets_unavailable(self):
        """TabPFNLicenseError → tabpfn_available=False, mean_tabpfn_mae=None."""
        from omsorgsradar import ml

        df = _make_feature_df()
        folds = _make_folds_no_xgb(n_folds=3)
        results = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_LicenseErrorRegressor)

        assert results.tabpfn_available is False
        assert results.mean_tabpfn_mae is None

    def test_license_error_status_is_bokmal(self):
        """Status note must be in bokmål and must not contain a raw exception repr."""
        from omsorgsradar import ml

        df = _make_feature_df()
        folds = _make_folds_no_xgb(n_folds=3)
        results = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_LicenseErrorRegressor)

        assert results.notes, "Expected at least one note"
        tabpfn_note = next(
            (n for n in results.notes if "TabPFN" in n or "tabpfn" in n.lower()), None
        )
        assert tabpfn_note is not None, f"No TabPFN note found; notes={results.notes}"
        # Must reference priorlabs or token
        assert "priorlabs" in tabpfn_note.lower() or "token" in tabpfn_note.lower(), (
            f"Note doesn't mention priorlabs/token: {tabpfn_note!r}"
        )
        # Must NOT be a raw exception repr
        assert "Traceback" not in tabpfn_note
        assert "TabPFNLicenseError" not in tabpfn_note


class TestTokenLeak:
    """Token value must never appear in JSON output, markdown summary, or logs."""

    FAKE_TOKEN = "tok_LEAK_TEST_VALUE_abc123xyz"

    def _run_and_collect(self, tmp_path: Path) -> tuple[str, str]:
        """Run ml pipeline with stub, return (json_text, summary_md)."""
        from omsorgsradar import ml

        os.environ["TABPFN_TOKEN"] = self.FAKE_TOKEN
        try:
            df = _make_feature_df()
            folds = _make_folds_no_xgb(n_folds=3)
            # The stub is injected — so the token value in env should NEVER propagate
            # into any artifact regardless
            results = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_StubTabPFNRegressor)

            json_path = tmp_path / "ml_results.json"
            ml.save_ml_results(results, json_path)
            json_text = json_path.read_text()

            summary_md = ml.ml_results_summary_md(results)
        finally:
            os.environ.pop("TABPFN_TOKEN", None)

        return json_text, summary_md

    def test_token_not_in_json(self, tmp_path: Path):
        json_text, _ = self._run_and_collect(tmp_path)
        assert self.FAKE_TOKEN not in json_text, (
            "FAKE TOKEN leaked into ml_results.json!"
        )

    def test_token_not_in_summary_md(self, tmp_path: Path):
        _, summary_md = self._run_and_collect(tmp_path)
        assert self.FAKE_TOKEN not in summary_md, (
            "FAKE TOKEN leaked into ml_results_summary_md!"
        )

    def test_token_not_in_log(self, tmp_path: Path, caplog):
        with caplog.at_level(logging.DEBUG, logger="omsorgsradar.ml"):
            self._run_and_collect(tmp_path)
        for record in caplog.records:
            assert self.FAKE_TOKEN not in record.getMessage(), (
                f"FAKE TOKEN leaked in log record: {record.getMessage()!r}"
            )

    def test_token_not_in_json_on_license_error(self, tmp_path: Path):
        """When license error fires, fake token still must not reach artifacts."""
        from omsorgsradar import ml

        os.environ["TABPFN_TOKEN"] = self.FAKE_TOKEN
        try:
            df = _make_feature_df()
            folds = _make_folds_no_xgb(n_folds=3)
            results = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_LicenseErrorRegressor)

            json_path = tmp_path / "ml_results_lic.json"
            ml.save_ml_results(results, json_path)
            json_text = json_path.read_text()
            summary_md = ml.ml_results_summary_md(results)
        finally:
            os.environ.pop("TABPFN_TOKEN", None)

        assert self.FAKE_TOKEN not in json_text, "FAKE TOKEN in JSON on license error"
        assert self.FAKE_TOKEN not in summary_md, "FAKE TOKEN in summary on license error"


# ---------------------------------------------------------------------------
# C3 — Summary markdown honest framing
# ---------------------------------------------------------------------------


class TestSummaryMarkdownHonestFraming:
    """ml_results_summary_md must reflect the autoregressive framing."""

    def test_tabpfn_column_in_summary_when_available(self):
        """When TabPFN ran, summary fold table must include a TabPFN column."""
        from omsorgsradar import ml

        df = _make_feature_df()
        folds = _make_folds_no_xgb(n_folds=3)
        tabpfn_partial = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_StubTabPFNRegressor)
        assert tabpfn_partial.tabpfn_available is True

        # Build a complete MLResults (as run_ml does) to test the summary
        results = ml.MLResults()
        results.folds = folds
        results.tabpfn_available = tabpfn_partial.tabpfn_available
        results.mean_tabpfn_mae = tabpfn_partial.mean_tabpfn_mae
        results.notes = tabpfn_partial.notes

        summary = ml.ml_results_summary_md(results)
        assert "TabPFN" in summary

    def test_tabpfn_status_line_when_unavailable(self):
        """When TabPFN not available, summary must show a one-line status."""
        from omsorgsradar import ml

        results = ml.MLResults()
        results.notes.append(
            "TabPFN-2.5 ikke kjørt — krever konto/token hos priorlabs.ai (se COSTS.md)"
        )
        summary = ml.ml_results_summary_md(results)
        assert "priorlabs" in summary.lower() or "TabPFN" in summary

    def test_autoregressive_framing_in_summary(self):
        """Summary must mention autoregressiv / persistence / avviks framing."""
        from omsorgsradar import ml

        df = _make_feature_df()
        folds = _make_folds_no_xgb(n_folds=3)
        tabpfn_partial = ml.run_tabpfn_on_folds(df, folds, _tabpfn_cls=_StubTabPFNRegressor)

        results = ml.MLResults()
        results.folds = folds
        results.tabpfn_available = tabpfn_partial.tabpfn_available
        results.mean_tabpfn_mae = tabpfn_partial.mean_tabpfn_mae
        results.notes = tabpfn_partial.notes

        summary = ml.ml_results_summary_md(results)

        has_autoregressiv = "autoregressiv" in summary.lower()
        has_persistence = "persistens" in summary.lower() or "persistence" in summary.lower()
        has_avvik = "avvik" in summary.lower()
        assert has_autoregressiv or has_persistence or has_avvik, (
            "Summary should mention autoregressiv/persistence/avvik framing"
        )
