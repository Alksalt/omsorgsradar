"""brfss-demo instance stages — diabetes-prevalence from anonymized microdata.

Shadows core analyze/verify/report for this analysis only (G0 extension point).
All numbers in the report come from brfss_findings.json, which the verify stage
independently recomputes from brfss_anonymized.csv (tool receipts — never calls
analyze compute functions).

Framing throughout: «anonymisering med målt restrisiko» — anonymisation technique
is k-anonymity with generalisation; residual risk is measured against all three
EU Art-29 WP216 criteria, never claimed to be zero.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from omsorgsradar.core.contracts import (
    register_schema,
    validate_artifact,
    write_manifest,
)
from omsorgsradar.core.registry import PipelineGateError, StageContext, StageRegistry

logger = logging.getLogger(__name__)

# ── schema ───────────────────────────────────────────────────────────────────

BRFSS_FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["classes", "overall", "n_released"],
    "properties": {
        "classes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["state", "age_band", "sex", "n", "prevalence"],
                "properties": {
                    "state": {"type": "string"},
                    "age_band": {"type": "string"},
                    "sex": {"type": "integer"},
                    "n": {"type": "integer"},
                    "prevalence": {"type": "number"},
                },
            },
        },
        "overall": {
            "type": "object",
            "required": ["n", "prevalence"],
            "properties": {
                "n": {"type": "integer"},
                "prevalence": {"type": "number"},
            },
        },
        "n_released": {"type": "integer"},
        "identifiability_verdict": {"type": "string"},
    },
}
register_schema("brfss_findings", BRFSS_FINDINGS_SCHEMA)


# ── compute core (pure functions) ────────────────────────────────────────────

def compute_prevalence_by_class(
    df: pd.DataFrame,
    quasi_identifiers: list[str],
    sensitive: str,
    min_class_for_report: int,
) -> list[dict[str, Any]]:
    """Compute diabetes prevalence per equivalence class from k-anon frame.

    Only classes with n >= min_class_for_report are emitted (additional
    practical disclosure control beyond the k guarantee).
    """
    classes = []
    for keys, group in df.groupby(quasi_identifiers):
        n = len(group)
        if n < min_class_for_report:
            continue
        prevalence = round(float(group[sensitive].mean()), 4)
        state, age_band, sex = (str(keys[0]), str(keys[1]), int(keys[2]))
        classes.append({
            "state": state,
            "age_band": age_band,
            "sex": sex,
            "n": int(n),
            "prevalence": prevalence,
        })
    return sorted(classes, key=lambda r: (r["state"], r["age_band"], r["sex"]))


def compute_overall(df: pd.DataFrame, sensitive: str) -> dict[str, Any]:
    return {
        "n": int(len(df)),
        "prevalence": round(float(df[sensitive].mean()), 4),
    }


# ── analyze stage ─────────────────────────────────────────────────────────────

def stage_analyze_brfss(ctx: StageContext) -> None:
    """Compute diabetes prevalence per equivalence class from the k-anon frame.

    The frame in ctx.state['datasets']['brfss'] has already been anonymized
    by the core anonymize stage: PII redacted, QIs generalized, small classes
    suppressed. Raw microdata is gone.
    """
    df = ctx.state["datasets"]["brfss"]
    params = ctx.config.params
    anon_cfg = dict(params.get("anonymize", {}))
    min_class = int(params.get("min_class_for_report", 10))

    quasi_identifiers = list(anon_cfg.get("quasi_identifiers", ["state", "age", "sex"]))
    sensitive = str(anon_cfg.get("sensitive", "diabetes"))

    # age column is now a category/object band label; convert to str for stable groupby
    df = df.copy()
    if "age" in df.columns:
        df["age"] = df["age"].astype(str)

    classes = compute_prevalence_by_class(df, quasi_identifiers, sensitive, min_class)
    overall = compute_overall(df, sensitive)

    # Carry WP216 receipt verdict into findings for report traceability
    identifiability = ctx.state.get("identifiability", {})
    verdict = identifiability.get("verdict", "UNKNOWN")

    findings: dict[str, Any] = {
        "classes": classes,
        "overall": overall,
        "n_released": int(len(df)),
        "identifiability_verdict": verdict,
    }

    findings_path = ctx.data_dir / "brfss_findings.json"
    findings_path.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validate_artifact("brfss_findings", findings)
    write_manifest(
        findings_path,
        artifact="brfss_findings",
        producer="analyze",
        inputs=[str(ctx.artifacts.get("anonymized_table", ""))],
    )
    ctx.state["brfss_findings"] = findings
    ctx.artifacts["findings"] = findings_path
    logger.info(
        "brfss analyze: %d equivalence classes published, n_released=%d, overall_prevalence=%.4f",
        len(classes), len(df), overall["prevalence"],
    )


# ── verify stage (tool receipts: INDEPENDENT recompute from disk) ─────────────

def _check(claims: list[dict[str, Any]], name: str, expected: Any, actual: Any,
           tol: float = 1e-4) -> None:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(float(expected) - float(actual)) <= tol
    else:
        ok = (expected == actual)
    claims.append({"claim": name, "expected": expected, "actual": actual, "ok": ok})


def stage_verify_brfss(ctx: StageContext) -> None:
    """Independently recompute every published number from brfss_anonymized.csv.

    Does NOT call the analyze compute functions — reads the on-disk artifact
    and re-derives all claims from scratch. This is the tool-receipts gate.
    """
    findings_path = ctx.data_dir / "brfss_findings.json"
    findings = json.loads(findings_path.read_text(encoding="utf-8"))

    # Load the anonymized CSV from disk — the single source of truth for verification
    anon_path = ctx.data_dir / "brfss_anonymized.csv"
    df = pd.read_csv(anon_path, dtype={"state": str})

    # Re-derive: age column may be stored as categorical label strings
    if "age" in df.columns:
        df["age"] = df["age"].astype(str)

    params = ctx.config.params
    anon_cfg = dict(params.get("anonymize", {}))
    min_class = int(params.get("min_class_for_report", 10))
    quasi_identifiers = list(anon_cfg.get("quasi_identifiers", ["state", "age", "sex"]))
    sensitive = str(anon_cfg.get("sensitive", "diabetes"))

    claims: list[dict[str, Any]] = []

    # Verify n_released
    _check(claims, "n_released", findings["n_released"], len(df))

    # Verify overall
    overall_expected = findings["overall"]
    _check(claims, "overall.n", overall_expected["n"], len(df))
    _check(claims, "overall.prevalence", overall_expected["prevalence"],
           round(float(df[sensitive].mean()), 4))

    # Recompute per-class stats from the anonymized CSV directly
    class_map: dict[tuple, dict] = {}
    for keys, group in df.groupby(quasi_identifiers):
        state, age_band, sex = (str(keys[0]), str(keys[1]), int(keys[2]))
        n = len(group)
        if n < min_class:
            continue
        class_map[(state, age_band, sex)] = {
            "n": int(n),
            "prevalence": round(float(group[sensitive].mean()), 4),
        }

    # Cross-check every published class
    for cls in findings["classes"]:
        key = (cls["state"], cls["age_band"], cls["sex"])
        if key not in class_map:
            claims.append({
                "claim": f"class {key} exists in anon CSV",
                "expected": True, "actual": False, "ok": False,
            })
            continue
        actual = class_map[key]
        prefix = f"class({cls['state']},{cls['age_band']},{cls['sex']})"
        _check(claims, f"{prefix}.n", cls["n"], actual["n"])
        _check(claims, f"{prefix}.prevalence", cls["prevalence"], actual["prevalence"])

    # Check no extra classes were omitted (findings should include all qualifying classes)
    published_keys = {(c["state"], c["age_band"], c["sex"]) for c in findings["classes"]}
    for key in class_map:
        if key not in published_keys:
            claims.append({
                "claim": f"class {key} published in findings",
                "expected": True, "actual": False, "ok": False,
            })

    failed = [c for c in claims if not c["ok"]]
    payload = {
        "verdict": "PASS" if not failed else "FAIL",
        "total_claims": len(claims),
        "passed": len(claims) - len(failed),
        "failed": len(failed),
        "failures": [
            f"{c['claim']}: findings={c['expected']!r} recomputed={c['actual']!r}"
            for c in failed
        ],
    }

    path = ctx.data_dir / "verification.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    validate_artifact("verification", payload)
    write_manifest(
        path, artifact="verification", producer="verify",
        inputs=[str(findings_path), str(anon_path)],
    )
    ctx.artifacts["verification"] = path
    ctx.state["brfss_verification"] = payload

    if payload["verdict"] != "PASS":
        raise PipelineGateError(
            f"brfss verify FAIL: {payload['failed']}/{payload['total_claims']} claims — "
            f"{payload['failures'][:3]}"
        )
    logger.info(
        "brfss verify PASS: %d/%d claims OK",
        payload["passed"], payload["total_claims"],
    )


# ── report stage (bokmål; numbers ONLY from findings + identifiability artifacts) ──

def stage_report_brfss(ctx: StageContext) -> None:
    """Write bokmål markdown report.

    Refuses to run without a green verification. All numbers come from
    brfss_findings.json and identifiability.json on disk — never recomputed here.
    """
    verification = ctx.state.get("brfss_verification")
    if verification is None or verification.get("verdict") != "PASS":
        raise PipelineGateError(
            "brfss report requires a green verification artifact "
            "(stage_verify_brfss must run first)"
        )

    findings = ctx.state["brfss_findings"]
    params = ctx.config.params
    min_class = int(params.get("min_class_for_report", 10))

    # Load identifiability receipt from disk (the authoritative artifact)
    ident_path = ctx.data_dir / "identifiability.json"
    ident = json.loads(ident_path.read_text(encoding="utf-8"))

    k_info = ident.get("k_anonymity", {})
    k_target = k_info.get("k_target", "?")
    n_suppressed = k_info.get("n_suppressed", "?")
    suppression_rate = k_info.get("suppression_rate", 0.0)
    n_released = k_info.get("n_records_released", "?")
    n_classes = k_info.get("n_classes", "?")

    so = ident.get("singling_out", {})
    lk = ident.get("linkability", {})
    inf = ident.get("inference", {})

    overall = findings["overall"]
    classes = findings["classes"]
    verdict = ident.get("verdict", "?")

    # Prevalence table (only classes with n >= min_class_for_report)
    table_rows = "\n".join(
        f"| {c['state']} | {c['age_band']} | {c['sex']} | {c['n']} | {c['prevalence']:.1%} |"
        for c in classes
    )
    if not table_rows:
        table_rows = "| — | — | — | — | — |"

    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.reports_dir / "brfss-demo_rapport.md"
    path.write_text(
        f"""# BRFSS-demo: demografi-stratifisert diabetes-prevalens med målt restrisiko

**Spørsmål:** {ctx.config.analysis['analysis']['question']}

## Metode

Analysen anvender **anonymisering med målt restrisiko** i henhold til EU Art-29
Working Party Opinion 05/2014 (WP216) og EDPB 01/2025 / Datatilsynets veiledning.

Trinnene er:

1. **PII-rensing** — fødselsnummer (fnr/D-nummer), telefonnummer og kontonummer
   oppdages via regex + mod-11-sjekksum og erstattes med `<ENTITY_TYPE>` i fritekstfelter.
2. **Generalisering** — kontinuerlig alder binnes til aldersintervaller
   (18–29, 30–44, 45–59, 60–74, 75+).
3. **k-anonymitet (k = {k_target})** — ekvivalensklasser med færre enn {k_target} rader
   undertrykkes. {n_suppressed} rader ble undertrykt
   (undertrykkelses­rate: {suppression_rate:.1%}).
   {n_released} rader i {n_classes} ekvivalensklasser ble frigitt.
4. **WP216-risikovurdering** — tre kriterier måles uavhengig.

> **Merk:** Pseudonymisering ≠ anonymisering. Residual re-identifikasjonsrisiko
> er *målt, ikke eliminert*. Framing: «anonymisering med målt restrisiko»
> (Datatilsynet; EDPB 01/2025; WP216).

## WP216-vurdering

**Samlet WP216-dom: {verdict}**

| Kriterium | Resultat | Nøkkeltall |
|-----------|----------|------------|
| Singling-out | **{so.get('verdict', '?')}** | min_class_size = {so.get('min_class_size', '?')}, prosecutor_risk = {so.get('prosecutor_risk', '?')} |
| Linkability | **{lk.get('verdict', '?')}** | unique_qi_share_pre_suppression = {lk.get('unique_qi_share_pre_suppression', '?')}, threshold = {lk.get('threshold', '?')} |
| Inference | **{inf.get('verdict', '?')}** | min_l_diversity = {inf.get('min_l_diversity', '?')}, max_attacker_adv = {inf.get('max_attacker_adv', '?')}, threshold = {inf.get('threshold', '?')} |

Alle tre verdier er hentet fra `data/identifiability.json`, produsert av anonymize-steget.

## Diabetes-prevalens per stratum

Totalt frigitt: **{overall['n']} observasjoner**, samlet prevalens: **{overall['prevalence']:.1%}**.

Tabellen viser kun klasser med n ≥ {min_class} (ytterligere praktisk personvern ut over k-garantien):

| Stat (FIPS) | Aldersband | Kjønn (1=M, 2=F) | n | Prevalens |
|-------------|------------|-------------------|---|-----------|
{table_rows}

Alle tall er beregnet av kode og kontrollregnet av en uavhengig verifiseringsmodul
({verification['passed']}/{verification['total_claims']} kontroller OK) før denne
rapporten ble generert.

## Datakilde

**CDC BRFSS** (US Behavioral Risk Factor Surveillance System):
[cdc.gov/brfss](https://www.cdc.gov/brfss/annual_data/annual_data.htm).
Denne analysen benytter en **syntetisk fixture** med BRFSS-form (600 rader,
seeded med numpy RNG seed=42) — ingen ekte persondata.
Real nedlasting dokumenteres i `analyses/brfss-demo/microdata/make_fixture.py`.

## Forbehold

- Syntetisk fixture: fordelingene gjenspeiler ikke den virkelige BRFSS-populasjonen.
- Aldersintervaller og k-verdi er tunet for demonstrasjonsformål.
- Undertrykkelses­rate på {suppression_rate:.1%} betyr at {suppression_rate:.1%} av radene
  ikke inngår i den frigitte tabellen.
- Pseudonymisering er ikke anonymisering: selv med WP216-godkjente verdier gjenstår
  en målbar restrisiko (se tabellen over).

---

*Rapporten er generert av omsorgsradar-pipelinen; alle tall kommer fra
`brfss_findings.json` og `identifiability.json`, verifisert mot `brfss_anonymized.csv`.*
""",
        encoding="utf-8",
    )
    write_manifest(
        path, artifact="brfss_report", producer="report",
        inputs=[str(ctx.data_dir / "brfss_findings.json"),
                str(ident_path)],
    )
    ctx.artifacts["report"] = path
    logger.info("brfss rapport: %s", path)


# ── instance registration (G0 extension point) ────────────────────────────────

def register(registry: StageRegistry) -> None:
    registry.register("analyze", stage_analyze_brfss, override=True)
    registry.register("verify", stage_verify_brfss, override=True)
    registry.register("report", stage_report_brfss, override=True)
