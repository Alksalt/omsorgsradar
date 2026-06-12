"""Default stage implementations wrapping the existing modules.

Each stage: read from ``ctx.state``/``ctx.artifacts``, compute via the
existing module functions, write file artifacts + manifests, fill ``ctx``.
The pipeline executor (pipeline.py) does the journaling.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from .core.contracts import validate_artifact, write_manifest
from .core.registry import PipelineGateError, StageContext, StageRegistry

logger = logging.getLogger(__name__)


def stage_ingest(ctx: StageContext) -> None:
    from .ingest import load_from_duckdb, run_ingest

    db_path = ctx.data_dir / f"{ctx.config.name}.duckdb"
    if ctx.state.get("skip_ingest"):
        datasets: dict[str, pd.DataFrame] = {}
        for src in ctx.config.sources:
            try:
                datasets[src["id"]] = load_from_duckdb(src["id"], db_path=db_path)
            except Exception as exc:  # missing table → empty df, same as v1
                logger.warning("Could not load %s: %s", src["id"], exc)
                datasets[src["id"]] = pd.DataFrame()
    else:
        datasets = run_ingest(
            ctx.config.sources,
            db_path=db_path,
            cache_dir=ctx.data_dir / "cache",
            base_dir=ctx.config.analysis_dir,
        )
    ctx.state["datasets"] = datasets
    ctx.artifacts["duckdb"] = db_path


def stage_profile(ctx: StageContext) -> None:
    from .profile import profile_all, save_quality_report

    quality = profile_all(ctx.state["datasets"], sources=ctx.config.sources)
    path = ctx.data_dir / "quality_profile.json"
    save_quality_report(quality, path=path)
    validate_artifact("quality_profile", quality)
    write_manifest(path, artifact="quality_profile", producer="profile")
    ctx.state["quality_report"] = quality
    ctx.artifacts["quality_profile"] = path
    # Realness gate (DECISIONS.md): FAIL aborts — but only after the verdict
    # is on disk so the failure is inspectable.
    failed = [
        name
        for name, ds in quality["datasets"].items()
        if isinstance(ds, dict) and ds.get("realness", {}).get("verdict") == "FAIL"
    ]
    if failed:
        raise PipelineGateError(
            f"realness gate FAIL for dataset(s): {', '.join(sorted(failed))} — "
            f"see {path}"
        )


def stage_analyze(ctx: StageContext) -> None:
    from .analyze import result_to_dict, run_analysis, save_findings

    datasets = ctx.state["datasets"]
    result = run_analysis(
        df_kostra=datasets.get("kostra_pleie", pd.DataFrame()),
        df_pop=datasets.get("befolkning", pd.DataFrame()),
        df_proj=datasets.get("framskrivinger"),
    )
    path = ctx.data_dir / "findings.json"
    save_findings(result, path=path)
    validate_artifact("findings", result_to_dict(result))
    write_manifest(
        path,
        artifact="findings",
        producer="analyze",
        inputs=[str(ctx.artifacts.get("quality_profile", ""))],
    )
    ctx.state["result"] = result
    ctx.artifacts["findings"] = path


def stage_verify(ctx: StageContext) -> None:
    from .verify import Verifier, build_standard_claims

    result = ctx.state["result"]
    claims = build_standard_claims(result)
    vreport = Verifier(result).verify_all(claims)
    payload = {
        "verdict": vreport.verdict,
        "total_claims": vreport.total_claims,
        "passed": vreport.passed,
        "failed": vreport.failed,
        "failures": [r.message for r in vreport.results if not r.passes],
    }
    path = ctx.data_dir / "verification.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validate_artifact("verification", payload)
    write_manifest(
        path,
        artifact="verification",
        producer="verify",
        inputs=[str(ctx.artifacts.get("findings", ""))],
    )
    ctx.state["verification"] = vreport
    ctx.artifacts["verification"] = path
    if vreport.verdict != "PASS":
        raise PipelineGateError(vreport.summary())


def stage_anonymize(ctx: StageContext) -> None:
    """Redact direct identifiers, k-anonymize quasi-identifiers, publish a
    measured-residual-risk receipt (WP216). Raw microdata is consumed here and
    dropped from state; only the anonymized aggregate flows downstream."""
    from .core.anonymize import assess_identifiability, generalize, k_suppress
    from .core.anonymize.pii import redact_pii, scan_pii

    acfg = dict(ctx.config.params.get("anonymize", {}))
    if not acfg:
        raise PipelineGateError("anonymize stage requires [params.anonymize] config")
    src_id = acfg["source"]
    datasets = ctx.state["datasets"]
    raw = datasets[src_id]

    text_cols = list(acfg.get("text_columns", []))
    spacy_model = acfg.get("spacy_model")
    pii_summary = {"total_redacted": 0, "entity_types": []}
    work = raw
    if text_cols:
        scanned = scan_pii(raw, text_cols, spacy_model=spacy_model)
        work, n = redact_pii(raw, text_cols, spacy_model=spacy_model)
        types = sorted({t for row in scanned["entity_types"] for t in row})
        pii_summary = {"total_redacted": int(n), "entity_types": types}

    generalized = generalize(work, acfg)
    kres = k_suppress(generalized, acfg)
    receipt = assess_identifiability(kres, generalized, acfg)
    receipt["pii"] = pii_summary

    # Data minimisation: free-text columns are scanned/redacted for the PII receipt
    # but NOT released — offline regex+checksum redaction cannot catch every direct
    # identifier (names, addresses, e-mails), and the WP216 receipt does not measure
    # residual free-text risk. Drop them unless explicitly opted-in.
    if text_cols and not acfg.get("keep_text_columns", False):
        drop = [c for c in text_cols if c in kres.frame.columns]
        if drop:
            kres.frame = kres.frame.drop(columns=drop)

    anon_path = ctx.data_dir / f"{src_id}_anonymized.csv"
    kres.frame.to_csv(anon_path, index=False)
    write_manifest(anon_path, artifact="anonymized_table", producer="anonymize")

    rpath = ctx.data_dir / "identifiability.json"
    rpath.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    validate_artifact("identifiability", receipt)
    write_manifest(rpath, artifact="identifiability", producer="anonymize",
                   inputs=[str(anon_path)])

    datasets[src_id] = kres.frame           # raw replaced; never left in state
    ctx.state["identifiability"] = receipt
    ctx.artifacts["anonymized_table"] = anon_path
    ctx.artifacts["identifiability"] = rpath
    if receipt["verdict"] == "FAIL":
        raise PipelineGateError(
            f"identifiability gate FAIL — singling_out={receipt['singling_out']['verdict']} "
            f"linkability={receipt['linkability']['verdict']} "
            f"inference={receipt['inference']['verdict']} (see {rpath})")


def stage_report(ctx: StageContext) -> None:
    from .report import run_report

    vreport = ctx.state.get("verification")
    if vreport is None or vreport.verdict != "PASS":  # defense in depth
        raise PipelineGateError("report stage requires a green verification artifact")
    report_path, cost_info = run_report(
        result=ctx.state["result"],
        quality_report=ctx.state["quality_report"],
        report_dir=ctx.reports_dir,
        use_llm=ctx.state.get("use_llm"),
    )
    ctx.state["cost_info"] = cost_info
    ctx.artifacts["report"] = report_path


def stage_ml(ctx: StageContext) -> None:
    from .ml import ml_results_summary_md, run_ml, save_ml_results

    datasets = ctx.state["datasets"]
    ml_results = run_ml(
        df_kostra=datasets.get("kostra_pleie", pd.DataFrame()),
        df_pop=datasets.get("befolkning", pd.DataFrame()),
        figures_dir=ctx.reports_dir / "figures",
    )
    path = ctx.data_dir / "ml_results.json"
    save_ml_results(ml_results, path=path)
    write_manifest(path, artifact="ml_results", producer="ml")
    ctx.artifacts["ml_results"] = path
    report_path = ctx.artifacts.get("report")
    if report_path is not None and report_path.exists():
        section = ml_results_summary_md(ml_results)
        existing = report_path.read_text(encoding="utf-8")
        marker = "---\n\n*Rapporten er generert"
        if marker in existing:
            existing = existing.replace(
                marker, section + "\n\n---\n\n*Rapporten er generert"
            )
        else:
            existing = existing + "\n\n" + section
        report_path.write_text(existing, encoding="utf-8")


def build_default_registry() -> StageRegistry:
    registry = StageRegistry()
    registry.register("ingest", stage_ingest)
    registry.register("profile", stage_profile)
    registry.register("anonymize", stage_anonymize)
    registry.register("analyze", stage_analyze)
    registry.register("verify", stage_verify)
    registry.register("report", stage_report)
    registry.register("ml", stage_ml)
    return registry
