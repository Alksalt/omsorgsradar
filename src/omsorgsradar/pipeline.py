"""Registry-driven pipeline runner.

Usage::

    uv run python -m omsorgsradar.pipeline                       # omsorgsradar
    uv run python -m omsorgsradar.pipeline analyses/<name>       # any instance

Programmatic::

    from omsorgsradar.pipeline import run_pipeline
    run_pipeline("analyses/omsorgsradar")
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from .core.config import load_run_config
from .core.journal import RunJournal
from .core.registry import (
    PipelineGateError,
    StageContext,
    StageRegistry,
    load_extensions,
    resolve_stage_list,
)
from .stages import build_default_registry

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
DEFAULT_ANALYSIS_DIR = REPO_ROOT / "analyses" / "omsorgsradar"
DEFAULT_WORKFLOW = REPO_ROOT / "workflow.toml"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"


def run_pipeline(
    analysis_dir: Path | str = DEFAULT_ANALYSIS_DIR,
    *,
    workflow_path: Path | str = DEFAULT_WORKFLOW,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    reports_dir: Path | str = DEFAULT_REPORTS_DIR,
    runs_dir: Path | str | None = None,
    registry: StageRegistry | None = None,
    skip_ingest: bool = False,
    skip_ml: bool = False,
    use_llm: bool | None = None,
) -> Path | None:
    """Run one analysis instance through its configured stages.

    Returns the report path if a report stage ran, else None.

    Raises:
        PipelineGateError: verification failed — no report was produced.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_run_config(analysis_dir, workflow_path)

    from .core.adapters import validate_source, validate_source_host

    extra_hosts = frozenset(
        cfg.workflow.get("security", {}).get("extra_allowed_hosts", [])
    )
    for src in cfg.sources:
        validate_source(src)
        validate_source_host(src, extra_hosts)

    data_dir, reports_dir = Path(data_dir), Path(reports_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    reg = registry if registry is not None else build_default_registry()
    load_extensions(cfg.analysis_dir, reg)

    stages = resolve_stage_list(cfg.stage_list)
    if skip_ml and "ml" in stages:
        stages.remove("ml")

    journal = RunJournal.start(
        Path(runs_dir) if runs_dir is not None
        else REPO_ROOT / str(cfg.setting("analysis", "runs_dir", default="runs")),
        analysis=cfg.name,
        config_snapshot={"stages": stages, "workflow": cfg.workflow},
    )
    ctx = StageContext(
        config=cfg, data_dir=data_dir, reports_dir=reports_dir, journal=journal
    )
    ctx.state["skip_ingest"] = skip_ingest
    ctx.state["use_llm"] = use_llm

    current_stage = "<startup>"
    try:
        for name in stages:
            current_stage = name
            before = dict(ctx.artifacts)
            t0 = time.monotonic()
            logger.info("Stage: %s", name)
            reg.get(name)(ctx)
            journal.record_stage(
                name,
                artifacts=[
                    str(p) for k, p in ctx.artifacts.items() if k not in before
                ],
                duration_s=round(time.monotonic() - t0, 3),
            )
    except PipelineGateError as exc:
        journal.record_stage(current_stage, meta={"error": str(exc)})
        journal.finalize("gate_failed")
        raise
    except Exception:
        journal.finalize("error")
        raise

    journal.finalize("ok")
    logger.info("=== Pipeline complete: %s ===", journal.run_dir / "run.json")
    return ctx.artifacts.get("report")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an analysis instance.")
    parser.add_argument(
        "analysis_dir", nargs="?", default=str(DEFAULT_ANALYSIS_DIR),
        help="Path to analyses/<name>/ (default: omsorgsradar)",
    )
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-ml", action="store_true")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                        help="artifact dir for this analysis (default: data/)")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR),
                        help="report dir for this analysis (default: reports/)")
    args = parser.parse_args()
    run_pipeline(
        args.analysis_dir,
        data_dir=args.data_dir,
        reports_dir=args.reports_dir,
        skip_ingest=args.skip_ingest,
        skip_ml=args.skip_ml,
    )


if __name__ == "__main__":
    main()
