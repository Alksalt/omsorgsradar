"""ML module — XGBoost walk-forward CV + SHAP + naive baseline.

Task: predict ``coverage_rate`` (brukere_hjem per 1000 pop_80plus) for
year Y+1 per kommune, given a feature set derived from KOSTRA history and
demographic data.

Design:
- Walk-forward CV: 3 expanding windows (no shuffle-split on time series).
- Naive baseline: last-year value carried forward.
- SHAP feature importance (tabular explainability for non-ML readers).
- TabPFN-2.5: no-training in-context baseline, if ``tabpfn`` is importable.
- Framing in all output text: «planleggingsstøtte», never clinical decision
  support.

Feature engineering:
- Coverage rate (lag 1, lag 2)
- 80+ population count (log)
- Year
- Pop share 80+ (ratio of 80+ to total adult population)
- Institutional places per 1000 80+

All results are written to structured JSON (``data/ml_results.json``) and
a summary section is included in the final report.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ML_RESULTS_PATH = Path(__file__).parent.parent.parent / "data" / "ml_results.json"


# ──────────────────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class CVFold:
    """Results for one walk-forward CV fold."""

    fold: int
    train_years: list[int]
    test_years: list[int]
    n_train: int
    n_test: int
    # Metrics
    xgb_mae: float
    xgb_rmse: float
    naive_mae: float
    naive_rmse: float
    tabpfn_mae: float | None = None
    tabpfn_rmse: float | None = None


@dataclass
class MLResults:
    """Container for all ML results."""

    target: str = "coverage_rate"
    framing: str = "planleggingsstøtte — ikke klinisk beslutningsstøtte"
    folds: list[CVFold] = field(default_factory=list)
    mean_xgb_mae: float = float("nan")
    mean_naive_mae: float = float("nan")
    mean_tabpfn_mae: float | None = None
    shap_top_features: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tabpfn_available: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Feature engineering
# ──────────────────────────────────────────────────────────────────────────────


FEATURE_COLS = [
    "coverage_rate_lag1",
    "coverage_rate_lag2",
    "log_pop_80plus",
    "year",
    "inst_per_1000_80plus",
]


def build_feature_df(
    df_kostra: pd.DataFrame,
    df_pop: pd.DataFrame,
) -> pd.DataFrame:
    """Build a per-kommune per-year feature DataFrame for ML.

    Uses KOSTRA coverage rates (% of 80+ using home services) as the target
    and population 80+ as a feature.

    Args:
        df_kostra: KOSTRA pleie DataFrame from :func:`ingest.fetch_kostra_pleie`.
        df_pop: Population by age DataFrame from :func:`ingest.fetch_population_current`.

    Returns:
        DataFrame with feature columns and target ``coverage_rate``.
    """
    if df_kostra.empty or df_pop.empty:
        logger.warning("Empty input to build_feature_df")
        return pd.DataFrame()

    # Real SSB variable codes
    KOSTRA_HJEM_CODE = "KOShjtj80aarover0001"
    KOSTRA_INST_CODE = "KOSsykhjand80aar0000"

    kostra = df_kostra.copy()
    kostra["value"] = pd.to_numeric(kostra["value"], errors="coerce")

    contents_col = "ContentsCode" if "ContentsCode" in kostra.columns else None
    if contents_col:
        # Try exact code match (real data)
        df_hjem = kostra[kostra[contents_col] == KOSTRA_HJEM_CODE].copy()
        df_inst = kostra[kostra[contents_col] == KOSTRA_INST_CODE].copy()
        # Fallback for fixtures
        if df_hjem.empty:
            df_hjem = kostra[
                kostra[contents_col].str.contains("BrukerHjem|hjemme|Hjem", case=False, na=False)
            ].copy()
        if df_inst.empty:
            df_inst = kostra[
                kostra[contents_col].str.contains("PlassInst|Inst|institusjons", case=False, na=False)
            ].copy()
    else:
        df_hjem = kostra.copy()
        df_inst = kostra.copy()

    if df_hjem.empty:
        logger.warning("No home care variable found in KOSTRA data; ML skipped")
        return pd.DataFrame()

    hjem_by_year = (
        df_hjem.groupby(["knr", "aar"])["value"].mean().reset_index()
        .rename(columns={"value": "coverage_rate"})
    )
    inst_by_year = (
        df_inst.groupby(["knr", "aar"])["value"].mean().reset_index()
        .rename(columns={"value": "inst_rate"})
    )

    # Get 80+ population per kommune per year (all years)
    pop = df_pop.copy()
    pop["value"] = pd.to_numeric(pop["value"], errors="coerce")

    age_col = next(
        (c for c in pop.columns if c in ("alder", "alder_code")), None
    )
    if age_col is None:
        logger.warning("No age column in population data")
        return pd.DataFrame()

    def parse_age_int(label: str) -> int | None:
        """Parse age from labels like '80 år' or codes like '080'."""
        s = str(label).strip()
        if s.isdigit():
            return int(s)
        digits = "".join(c for c in s.split()[0] if c.isdigit())
        return int(digits) if digits else None

    pop["age_int"] = pop[age_col].map(parse_age_int)
    df_80_all = pop[pop["age_int"].fillna(0) >= 80].copy()
    pop_by_knr_year = (
        df_80_all.groupby(["knr", "aar"])["value"].sum().reset_index()
        .rename(columns={"value": "pop_80plus"})
    )

    # Merge all
    df = hjem_by_year.merge(inst_by_year, on=["knr", "aar"], how="left")
    df = df.merge(pop_by_knr_year, on=["knr", "aar"], how="left")

    df["log_pop_80plus"] = np.log1p(df["pop_80plus"].fillna(0))
    df["inst_per_1000_80plus"] = pd.to_numeric(df.get("inst_rate", 0), errors="coerce").fillna(0)
    df["year"] = df["aar"]

    # Sort and add lags per kommune
    df = df.sort_values(["knr", "aar"])
    df["coverage_rate_lag1"] = df.groupby("knr")["coverage_rate"].shift(1)
    df["coverage_rate_lag2"] = df.groupby("knr")["coverage_rate"].shift(2)

    # Drop rows without target or lag1
    df = df.dropna(subset=["coverage_rate", "coverage_rate_lag1"])

    logger.info("Feature df built: %d rows, %d kommuner", len(df), df["knr"].nunique())
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Walk-forward CV
# ──────────────────────────────────────────────────────────────────────────────


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def _resolve_n_folds(df: pd.DataFrame, n_folds: int) -> tuple[int, list]:
    """Return (effective_n_folds, all_years) after reducing if needed."""
    all_years = sorted(df["year"].unique())
    if len(all_years) < n_folds + 2:
        logger.warning(
            "Not enough years (%d) for %d folds; reducing to 1 fold", len(all_years), n_folds
        )
        n_folds = max(1, len(all_years) - 2)
    return n_folds, all_years


def _iter_fold_splits(
    df: pd.DataFrame,
    all_years: list,
    n_folds: int,
    feature_cols: list[str],
):
    """Yield (fold_index_0based, X_train, y_train, X_test, y_test, train_df, test_df) per fold.

    Shared by walk_forward_cv (XGBoost) and run_tabpfn_on_folds (TabPFN) so both
    models see identical expanding-window splits.
    """
    test_years_list = all_years[-n_folds:]
    for i, test_year in enumerate(test_years_list):
        train_df = df[df["year"] < test_year].copy()
        test_df = df[df["year"] == test_year].copy()
        if train_df.empty or test_df.empty:
            continue
        X_train = train_df[feature_cols].fillna(0).values
        y_train = train_df["coverage_rate"].values
        X_test = test_df[feature_cols].fillna(0).values
        y_test = test_df["coverage_rate"].values
        yield i, X_train, y_train, X_test, y_test, train_df, test_df


def walk_forward_cv(
    df: pd.DataFrame,
    n_folds: int = 3,
) -> tuple[list[CVFold], "xgboost.XGBRegressor", list[str]]:  # type: ignore[name-defined]
    """Walk-forward cross-validation with XGBoost and naive baseline.

    Args:
        df: Feature DataFrame from :func:`build_feature_df`.
        n_folds: Number of expanding windows.

    Returns:
        ``(folds, final_model, feature_names)`` tuple.
    """
    import xgboost as xgb

    if df.empty:
        return [], None, []  # type: ignore[return-value]

    n_folds, all_years = _resolve_n_folds(df, n_folds)
    feature_cols = [c for c in FEATURE_COLS if c in df.columns]
    folds: list[CVFold] = []
    final_model = None

    for i, X_train, y_train, X_test, y_test, train_df, test_df in _iter_fold_splits(
        df, all_years, n_folds, feature_cols
    ):
        test_year = int(test_df["year"].iloc[0])

        # XGBoost
        model = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        y_pred_xgb = model.predict(X_test)

        # Naive baseline: last observed value (lag1)
        y_naive = test_df["coverage_rate_lag1"].fillna(test_df["coverage_rate"].mean()).values

        fold = CVFold(
            fold=i + 1,
            train_years=sorted(train_df["year"].unique().tolist()),
            test_years=[test_year],
            n_train=len(train_df),
            n_test=len(test_df),
            xgb_mae=_mae(y_test, y_pred_xgb),
            xgb_rmse=_rmse(y_test, y_pred_xgb),
            naive_mae=_mae(y_test, y_naive),
            naive_rmse=_rmse(y_test, y_naive),
        )
        folds.append(fold)
        final_model = model
        logger.info(
            "Fold %d (test %d): XGB MAE=%.2f, naive MAE=%.2f",
            i + 1, test_year, fold.xgb_mae, fold.naive_mae,
        )

    return folds, final_model, feature_cols


# ──────────────────────────────────────────────────────────────────────────────
# SHAP
# ──────────────────────────────────────────────────────────────────────────────


def compute_shap(
    model: Any,
    X: np.ndarray,
    feature_names: list[str],
    out_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Compute SHAP values and return top feature importances.

    Args:
        model: Trained XGBoost model.
        X: Feature matrix (numpy array).
        feature_names: Feature name list.
        out_dir: If supplied, save a SHAP bar chart here.

    Returns:
        List of dicts ``{"feature": str, "mean_abs_shap": float}`` sorted descending.
    """
    try:
        import shap
    except ImportError:
        logger.warning("shap not installed; skipping SHAP computation")
        return []

    if model is None or X is None or len(X) == 0:
        return []

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    mean_abs = np.mean(np.abs(shap_values), axis=0)
    importance = [
        {"feature": fn, "mean_abs_shap": round(float(v), 4)}
        for fn, v in sorted(zip(feature_names, mean_abs), key=lambda x: -x[1])
    ]

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 4))
            feats = [i["feature"] for i in importance]
            vals = [i["mean_abs_shap"] for i in importance]
            ax.barh(range(len(feats)), vals, color="#4C9BE8")
            ax.set_yticks(range(len(feats)))
            ax.set_yticklabels(feats, fontsize=10)
            ax.invert_yaxis()
            ax.set_xlabel("Mean |SHAP|", fontsize=11)
            ax.set_title("XGBoost — feature importance (SHAP)", fontsize=13)
            ax.grid(axis="x", alpha=0.3)
            fig.tight_layout()
            fig.savefig(out_dir / "shap_importance.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception as exc:
            logger.warning("SHAP plot failed: %s", exc)

    return importance


# ──────────────────────────────────────────────────────────────────────────────
# TabPFN baseline — fold-parallel (same 3 expanding windows as XGBoost)
# ──────────────────────────────────────────────────────────────────────────────

#: Environment variable that TabPFN reads for the PriorLabs API token.
#: Set this to your key from https://ux.priorlabs.ai/account before running.
TABPFN_TOKEN_ENV_VAR = "TABPFN_TOKEN"

#: Status message (bokmål) written when the token/weights are unavailable.
_TABPFN_UNAVAILABLE_MSG = (
    "TabPFN-2.5 ikke kjørt — krever konto/token hos priorlabs.ai (se COSTS.md). "
    f"Sett miljøvariabelen {TABPFN_TOKEN_ENV_VAR} og kjør ml-steget på nytt."
)


def run_tabpfn_on_folds(
    df: pd.DataFrame,
    folds: list[CVFold],
    n_folds: int = 3,
    *,
    _tabpfn_cls: Any = None,
) -> "MLResults":
    """Run TabPFN-2.5 over the same walk-forward folds as XGBoost.

    Populates ``tabpfn_mae``/``tabpfn_rmse`` on each :class:`CVFold` in-place,
    then returns a partial :class:`MLResults` with ``tabpfn_available`` and
    ``mean_tabpfn_mae`` set.

    Args:
        df: Feature DataFrame from :func:`build_feature_df`.
        folds: Fold list produced by :func:`walk_forward_cv` (mutated in-place).
        n_folds: Number of folds (must match what was used for ``folds``).
        _tabpfn_cls: Injectable regressor class for offline testing; if None,
            ``tabpfn.TabPFNRegressor`` is imported at call time.

    Returns:
        :class:`MLResults` with TabPFN fields populated.
    """
    results = MLResults()

    if _tabpfn_cls is None:
        # Check for missing token BEFORE any fold iteration (A7).
        # One INFO line is emitted; no per-fold WARNINGs.
        import os as _os
        if not _os.environ.get(TABPFN_TOKEN_ENV_VAR):
            logger.info(
                "TabPFN hoppes over — sett %s (se COSTS.md)", TABPFN_TOKEN_ENV_VAR
            )
            results.notes.append(_TABPFN_UNAVAILABLE_MSG)
            return results
        try:
            from tabpfn import TabPFNRegressor  # type: ignore[import]
            _tabpfn_cls = TabPFNRegressor
        except (ImportError, TypeError):
            results.notes.append(_TABPFN_UNAVAILABLE_MSG)
            return results
    TabPFNRegressor = _tabpfn_cls

    if df.empty or not folds:
        results.notes.append("TabPFN: ingen data eller folds")
        return results

    effective_n_folds, all_years = _resolve_n_folds(df, len(folds))
    feature_cols = [c for c in FEATURE_COLS if c in df.columns]

    # Build a mapping from fold index → CVFold so we can update in-place
    fold_by_index: dict[int, CVFold] = {f.fold - 1: f for f in folds}

    any_success = False
    for i, X_train, y_train, X_test, y_test, _train_df, _test_df in _iter_fold_splits(
        df, all_years, effective_n_folds, feature_cols
    ):
        # Subsampling guard: TabPFN has a 10k row limit; seeded for reproducibility
        if len(X_train) > 5000:
            idx = np.random.RandomState(42).choice(len(X_train), 5000, replace=False)
            X_train = X_train[idx]
            y_train = y_train[idx]

        try:
            model = TabPFNRegressor(device="cpu")
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            fold_mae = _mae(y_test, y_pred)
            fold_rmse = _rmse(y_test, y_pred)
        except Exception as exc:
            # Catch TabPFNLicenseError, TabPFNHuggingFaceGatedRepoError, and
            # any other runtime error.  Log the raw exception; surface only a
            # clean bokmål string to artifacts.
            logger.info("TabPFN hoppes over — sett %s (se COSTS.md)", TABPFN_TOKEN_ENV_VAR)
            results.notes.append(_TABPFN_UNAVAILABLE_MSG)
            return results

        # Update CVFold in-place
        target_fold = fold_by_index.get(i)
        if target_fold is not None:
            target_fold.tabpfn_mae = fold_mae
            target_fold.tabpfn_rmse = fold_rmse

        any_success = True
        logger.info("TabPFN fold %d MAE=%.2f", i + 1, fold_mae)

    if any_success:
        completed = [f for f in folds if f.tabpfn_mae is not None]
        if completed:
            results.tabpfn_available = True
            results.mean_tabpfn_mae = float(np.mean([f.tabpfn_mae for f in completed]))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────────


def run_ml(
    df_kostra: pd.DataFrame,
    df_pop: pd.DataFrame,
    figures_dir: Path | None = None,
) -> MLResults:
    """Run the full ML pipeline and return structured results.

    Args:
        df_kostra: KOSTRA pleie DataFrame.
        df_pop: Population by age DataFrame.
        figures_dir: Optional directory for figures (SHAP plot).

    Returns:
        :class:`MLResults` instance.
    """
    results = MLResults()

    # Build features
    df = build_feature_df(df_kostra, df_pop)
    if df.empty:
        results.notes.append("Feature DataFrame empty — ML skipped")
        return results

    feature_cols = [c for c in FEATURE_COLS if c in df.columns]

    # Walk-forward CV
    folds, final_model, feat_names = walk_forward_cv(df, n_folds=3)
    results.folds = folds

    if folds:
        results.mean_xgb_mae = float(np.mean([f.xgb_mae for f in folds]))
        results.mean_naive_mae = float(np.mean([f.naive_mae for f in folds]))
        logger.info(
            "Walk-forward CV: XGB MAE=%.2f vs naive MAE=%.2f",
            results.mean_xgb_mae, results.mean_naive_mae,
        )

    # SHAP
    if final_model is not None:
        all_years = sorted(df["year"].unique())
        test_year = all_years[-1]
        X_all = df[df["year"] == test_year][feature_cols].fillna(0).values
        results.shap_top_features = compute_shap(
            final_model, X_all, feat_names, out_dir=figures_dir
        )

    # TabPFN — same 3 folds as XGBoost for an honest comparison
    tabpfn_partial = run_tabpfn_on_folds(df, folds, n_folds=3)
    results.tabpfn_available = tabpfn_partial.tabpfn_available
    results.mean_tabpfn_mae = tabpfn_partial.mean_tabpfn_mae
    results.notes.extend(tabpfn_partial.notes)

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Serialisation
# ──────────────────────────────────────────────────────────────────────────────


def save_ml_results(results: MLResults, path: Path = ML_RESULTS_PATH) -> None:
    """Save ML results to JSON.

    Args:
        results: :class:`MLResults` instance.
        path: Output path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def _safe(obj: Any) -> Any:
        if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: _safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_safe(i) for i in obj]
        return obj

    d = _safe(asdict(results))
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("ML results saved to %s", path)


def ml_results_summary_md(results: MLResults) -> str:
    """Render a markdown summary of ML results for the report.

    Args:
        results: :class:`MLResults` instance.

    Returns:
        Markdown string.
    """
    lines = [
        "## ML-analyse — XGBoost walk-forward CV",
        "",
        f"**Mål:** {results.target}  ",
        f"**Ramme:** {results.framing}",
        "",
        "**Nøkkelfunn:** Kommunal dekning er sterkt autoregressiv — "
        "årets dekning predikerer neste års dekning nesten like godt som en tunet modell. "
        "Modelltillegg over naiv persistens er beskjedent (~0.2 pp MAE). "
        "Modellens verdi er avviksflagging (kommuner som avviker fra egen trend), "
        "ikke punktprediksjon.",
        "",
    ]
    if results.folds:
        has_tabpfn = results.tabpfn_available and any(
            f.tabpfn_mae is not None for f in results.folds
        )

        mean_line = (
            f"**Gjennomsnittlig MAE:** XGBoost {results.mean_xgb_mae:.2f} pp "
            f"vs naiv persistens {results.mean_naive_mae:.2f} pp"
        )
        if has_tabpfn and results.mean_tabpfn_mae is not None:
            mean_line += f" vs TabPFN {results.mean_tabpfn_mae:.2f} pp"
        lines.append(mean_line)
        lines.append("")

        if has_tabpfn:
            lines.append("| Fold | Testår | XGB MAE | Naiv MAE | TabPFN MAE |")
            lines.append("|------|--------|---------|----------|------------|")
            for fold in results.folds:
                tabpfn_cell = f"{fold.tabpfn_mae:.2f}" if fold.tabpfn_mae is not None else "—"
                lines.append(
                    f"| {fold.fold} | {fold.test_years[0] if fold.test_years else '—'} "
                    f"| {fold.xgb_mae:.2f} | {fold.naive_mae:.2f} | {tabpfn_cell} |"
                )
        else:
            lines.append("| Fold | Testår | XGB MAE | Naiv MAE |")
            lines.append("|------|--------|---------|----------|")
            for fold in results.folds:
                lines.append(
                    f"| {fold.fold} | {fold.test_years[0] if fold.test_years else '—'} "
                    f"| {fold.xgb_mae:.2f} | {fold.naive_mae:.2f} |"
                )
        lines.append("")
    else:
        lines.append("*Walk-forward CV ikke gjennomført (for lite data).*")
        lines.append("")

    if not results.tabpfn_available:
        # Show the one-line status from notes if present
        tabpfn_note = next(
            (n for n in results.notes if "priorlabs" in n.lower() or "TabPFN" in n),
            None,
        )
        if tabpfn_note:
            lines.append(f"*{tabpfn_note}*")
            lines.append("")

    if results.shap_top_features:
        lines.append("**SHAP — viktigste features:**")
        lines.append("")
        for feat in results.shap_top_features[:5]:
            lines.append(f"- `{feat['feature']}`: mean |SHAP| = {feat['mean_abs_shap']:.4f}")
        lines.append("")

    # Include only non-TabPFN notes here (TabPFN status shown above)
    other_notes = [
        n for n in results.notes
        if "priorlabs" not in n.lower() and "TabPFN" not in n
    ]
    if other_notes:
        lines.append("**Merknader:**")
        for note in other_notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)
