"""Top-level pipeline runner.

Runs the full ingest → profile → analyze → verify → report → ML pipeline.
Imports all modules and calls them in sequence.

Usage::

    uv run python -m omsorgsradar.pipeline

Or programmatically::

    from omsorgsradar.pipeline import run_pipeline
    run_pipeline()
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "omsorgsradar.duckdb"


def run_pipeline(
    skip_ingest: bool = False,
    skip_ml: bool = False,
    use_llm: bool | None = None,
) -> None:
    """Run the full omsorgsradar pipeline.

    Args:
        skip_ingest: If True, load data from DuckDB instead of re-fetching.
        skip_ml: If True, skip the ML phase.
        use_llm: If None, auto-detect from ANTHROPIC_API_KEY env var.
    """
    from .ingest import run_ingest, load_from_duckdb
    from .profile import profile_all, save_quality_report, quality_report_summary_md
    from .analyze import run_analysis, save_findings
    from .report import run_report
    from .ml import run_ml, save_ml_results, ml_results_summary_md

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # ── P0: Ingest ────────────────────────────────────────────────────────────
    if skip_ingest:
        logger.info("P0: Loading from DuckDB (skip_ingest=True)")
        import pandas as pd
        datasets = {}
        for table in ("kostra_pleie", "befolkning", "framskrivinger", "fhi_nokkel"):
            try:
                datasets[table] = load_from_duckdb(table, db_path=DB_PATH)
                logger.info("Loaded %s: %d rows", table, len(datasets[table]))
            except Exception as exc:
                logger.warning("Could not load %s: %s", table, exc)
                datasets[table] = pd.DataFrame()
    else:
        logger.info("P0: Running live ingest from SSB/FHI APIs")
        datasets = run_ingest(db_path=DB_PATH, cache_dir=CACHE_DIR)

    # ── P0: Profile ───────────────────────────────────────────────────────────
    logger.info("P0: Data profiling")
    quality_report = profile_all(datasets)
    quality_path = DATA_DIR / "quality_profile.json"
    save_quality_report(quality_report, path=quality_path)
    logger.info("Quality profile: %s", quality_path)

    # ── P1: Analysis ──────────────────────────────────────────────────────────
    logger.info("P1: Running analysis")
    result = run_analysis(
        df_kostra=datasets.get("kostra_pleie", __import__("pandas").DataFrame()),
        df_pop=datasets.get("befolkning", __import__("pandas").DataFrame()),
        df_proj=datasets.get("framskrivinger"),
    )
    save_findings(result, path=DATA_DIR / "findings.json")
    logger.info("Findings: %d kommuner ranked", len(result.kommuner))

    if result.kommuner:
        top3 = result.kommuner[:3]
        for km in top3:
            logger.info(
                "  #%d %s (knr %s): press=%.3f, coverage=%.1f",
                km.rank, km.navn or "—", km.knr, km.press_index_norm, km.coverage_rate
                if km.coverage_rate == km.coverage_rate else 0,
            )

    # ── P3: Report ────────────────────────────────────────────────────────────
    logger.info("P3: Generating report and figures")
    report_path, cost_info = run_report(
        result=result,
        quality_report=quality_report,
        report_dir=REPORTS_DIR,
        use_llm=use_llm,
    )
    logger.info("Report: %s (renderer: %s)", report_path, cost_info.get("renderer"))

    # ── P4: ML ────────────────────────────────────────────────────────────────
    if not skip_ml:
        logger.info("P4: Running ML pipeline")
        ml_results = run_ml(
            df_kostra=datasets.get("kostra_pleie", __import__("pandas").DataFrame()),
            df_pop=datasets.get("befolkning", __import__("pandas").DataFrame()),
            figures_dir=REPORTS_DIR / "figures",
        )
        save_ml_results(ml_results, path=DATA_DIR / "ml_results.json")
        logger.info("ML: XGB MAE=%.2f, naive MAE=%.2f",
                    ml_results.mean_xgb_mae, ml_results.mean_naive_mae)

        # Append ML section to report
        ml_section = ml_results_summary_md(ml_results)
        try:
            existing = report_path.read_text(encoding="utf-8")
            marker = "---\n\n*Rapporten er generert"
            if marker in existing:
                new_content = existing.replace(
                    marker,
                    ml_section + "\n\n---\n\n*Rapporten er generert",
                )
            else:
                new_content = existing + "\n\n" + ml_section
            report_path.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not append ML section to report: %s", exc)

    logger.info("=== Pipeline complete ===")
    logger.info("Report: %s", report_path)
    logger.info("Figures: %s", REPORTS_DIR / "figures")


if __name__ == "__main__":
    run_pipeline()
