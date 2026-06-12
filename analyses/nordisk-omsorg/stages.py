"""nordisk-omsorg instance stages — NO/SE/FI ageing vs home-care capacity.

Shadows core analyze/verify/report for this analysis only (G0 extension
point). All numbers in the report come from nordic_findings.json, which the
verify stage independently recomputes from nordic_table.csv (tool receipts).

Comparability (hard caveat, repeated in the report): NO/SE coverage is 80+,
FI is 75+; definitions differ per country. Squeeze scores are therefore
z-normalized WITHIN country; only patterns are compared across countries.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

import numpy as np
import pandas as pd

from omsorgsradar.core.contracts import (
    register_schema,
    validate_artifact,
    write_manifest,
)
from omsorgsradar.core.geo import make_geo_id
from omsorgsradar.core.registry import PipelineGateError, StageContext, StageRegistry
from omsorgsradar.kommune_mergers import MIXED_SOURCE_KNRS, normalize_knr_series

logger = logging.getLogger(__name__)

COUNTRY_AGE_CUT = {"NO": "80+", "SE": "80+", "FI": "75+"}

NORDIC_FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["countries", "analysis_years"],
    "properties": {
        "analysis_years": {
            "type": "object",
            "required": ["base", "latest"],
            "properties": {"base": {"type": "integer"}, "latest": {"type": "integer"}},
        },
        "countries": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["n_municipalities", "n_dropped", "coverage_median",
                             "growth_median", "high_squeeze_share", "age_cut",
                             "top_squeeze"],
                "properties": {
                    "n_municipalities": {"type": "integer"},
                    "n_dropped": {"type": "integer"},
                    "coverage_median": {"type": "number"},
                    "growth_median": {"type": "number"},
                    "high_squeeze_share": {"type": "number"},
                    "age_cut": {"type": "string"},
                    "top_squeeze": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["geo_id", "geo_name", "squeeze",
                                         "coverage", "growth_pct", "rank"],
                        },
                    },
                },
            },
        },
        "comparison": {
            "type": "object",
            "required": ["lowest_high_squeeze_share_country"],
        },
        "context": {"type": "object"},
    },
}
register_schema("nordic_findings", NORDIC_FINDINGS_SCHEMA)


# ── compute core (pure functions, unit-tested) ───────────────────────────────

def _z(series: pd.Series) -> pd.Series:
    std = float(series.std(ddof=0))
    if std == 0.0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def squeeze_table(df: pd.DataFrame) -> pd.DataFrame:
    """Add growth_pct, z-scores, squeeze, rank. Drops rows missing either
    metric; the drop count is in ``out.attrs['n_dropped']``."""
    out = df.copy()
    out["growth_pct"] = (
        (out["elderly_latest"] - out["elderly_base"]) / out["elderly_base"] * 100
    )
    n_before = len(out)
    out = out.dropna(subset=["coverage", "growth_pct"]).copy()
    out = out[np.isfinite(out["growth_pct"])]
    out.attrs["n_dropped"] = n_before - len(out)
    out["z_coverage"] = _z(out["coverage"])
    out["z_growth"] = _z(out["growth_pct"])
    out["squeeze"] = out["z_growth"] - out["z_coverage"]
    out = out.sort_values("squeeze", ascending=False).reset_index(drop=True)
    out["rank"] = out.index + 1
    return out


def findings_from_tables(
    tables: Mapping[str, pd.DataFrame],
    params: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    countries: dict[str, Any] = {}
    for country, t in sorted(tables.items()):
        cov_med = float(t["coverage"].median())
        gro_med = float(t["growth_pct"].median())
        high = ((t["growth_pct"] > gro_med) & (t["coverage"] < cov_med))
        top_n = int(params.get("top_n", 10))
        countries[country] = {
            "n_municipalities": int(len(t)),
            "n_dropped": int(t.attrs.get("n_dropped", 0)),
            "coverage_median": round(cov_med, 2),
            "growth_median": round(gro_med, 2),
            "high_squeeze_share": round(float(high.mean()), 4),
            "age_cut": COUNTRY_AGE_CUT.get(country, "?"),
            "top_squeeze": [
                {
                    "geo_id": r.geo_id,
                    "geo_name": r.geo_name,
                    "squeeze": round(float(r.squeeze), 3),
                    "coverage": round(float(r.coverage), 2),
                    "growth_pct": round(float(r.growth_pct), 2),
                    "rank": int(r.rank),
                }
                for r in t.head(top_n).itertuples()
            ],
        }
    lowest = min(countries, key=lambda c: countries[c]["high_squeeze_share"])
    return {
        "analysis_years": {"base": int(params["base_year"]),
                           "latest": int(params["latest_year"])},
        "countries": countries,
        "comparison": {"lowest_high_squeeze_share_country": lowest},
        "context": dict(context),
    }


# ── country table builders ───────────────────────────────────────────────────

def _no_table(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> pd.DataFrame:
    kostra = datasets["no_kostra"]
    pop = datasets["no_befolkning"]
    region_col = next(c for c in kostra.columns
                      if "region" in c.lower() and not c.endswith("_label"))
    k = kostra[kostra[region_col].astype(str).str.fullmatch(r"\d{4}")].copy()
    k["knr"] = normalize_knr_series(k[region_col].astype(str).str.zfill(4))
    k["aar"] = pd.to_numeric(k["Tid"], errors="coerce")
    k["value"] = pd.to_numeric(k["value"], errors="coerce")
    # Build coverage WITHOUT dropping NaN — suppressed values must flow into
    # squeeze_table so its dropna counts them in n_dropped.
    cov = (k[k["aar"] == latest]
           .groupby("knr")
           .agg(coverage=("value", "mean"),
                geo_name=(f"{region_col}_label", "first"))
           .reset_index())

    p = pop[pop["Region"].astype(str).str.fullmatch(r"\d{4}")].copy()
    p["knr"] = normalize_knr_series(p["Region"].astype(str).str.zfill(4))
    p["aar"] = pd.to_numeric(p["Tid"], errors="coerce")
    p["value"] = pd.to_numeric(p["value"], errors="coerce")
    # groupby sums across Alder AND Kjonn (07459 has no gender total)
    sums = p.groupby(["knr", "aar"])["value"].sum().unstack()
    eld = pd.DataFrame({
        "knr": sums.index,
        "elderly_base": sums.get(base),
        "elderly_latest": sums.get(latest),
    }).reset_index(drop=True)

    # Inner-merge on population: only municipalities with a population row in
    # the latest year are "current". Defunct historical codes (no population)
    # are silently excluded here. Municipalities WITH population but missing
    # coverage retain NaN coverage and will be counted by squeeze_table.
    out = cov.merge(eld, on="knr", how="inner")
    out["geo_id"] = out["knr"].map(lambda c: make_geo_id("NO", c))
    # Mixed-source codes: post-reform municipality is the target of BOTH a
    # 1-to-1 rename AND a split — the 2019 baseline covers only the renamed
    # predecessor, not the split portion.  Growth would be inflated.  Set
    # elderly_base to NaN so squeeze_table counts them in n_dropped.
    mixed_mask = out["knr"].isin(MIXED_SOURCE_KNRS)
    out.loc[mixed_mask, "elderly_base"] = float("nan")
    # Strip SSB era suffixes from names:
    #   "Ålesund (2020-2023)" -> "Ålesund"
    #   "Hamarøy - Hábmer (-2019)" -> "Hamarøy - Hábmer"
    out["geo_name"] = out["geo_name"].str.replace(
        r"\s*\(-?\d{4}[^)]*\)$", "", regex=True
    )
    return out[["geo_id", "geo_name", "coverage", "elderly_base", "elderly_latest"]]


def _se_table(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> pd.DataFrame:
    hem = datasets["se_hemtjanst"]
    pop = datasets["se_befolkning"]
    cov = (hem[hem["aar"] == latest][["geo_id", "geo_name", "value"]]
           .rename(columns={"value": "coverage"}))

    p = pop[pop["Region"].astype(str).str.fullmatch(r"\d{4}")].copy()
    p["aar"] = pd.to_numeric(p["Tid"], errors="coerce")
    p["value"] = pd.to_numeric(p["value"], errors="coerce")
    p["geo_id"] = p["Region"].map(lambda c: make_geo_id("SE", c))
    sums = p.groupby(["geo_id", "aar"])["value"].sum().unstack()
    eld = pd.DataFrame({
        "geo_id": sums.index,
        "elderly_base": sums.get(base),
        "elderly_latest": sums.get(latest),
    }).reset_index(drop=True)

    return cov.merge(eld, on="geo_id", how="inner")[
        ["geo_id", "geo_name", "coverage", "elderly_base", "elderly_latest"]
    ]


def _fi_table(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> pd.DataFrame:
    care = datasets["fi_homecare"]
    share = datasets["fi_elderly_share"]
    popn = datasets["fi_population"]
    cov = (care[care["aar"] == latest][["geo_id", "geo_name", "value"]]
           .rename(columns={"value": "coverage"}))

    merged = share[["geo_id", "aar", "value"]].rename(columns={"value": "share"}).merge(
        popn[["geo_id", "aar", "value"]].rename(columns={"value": "pop"}),
        on=["geo_id", "aar"], how="inner",
    )
    merged["elderly"] = merged["share"] * merged["pop"] / 100.0
    sums = merged.pivot_table(index="geo_id", columns="aar", values="elderly")
    eld = pd.DataFrame({
        "geo_id": sums.index,
        "elderly_base": sums.get(base),
        "elderly_latest": sums.get(latest),
    }).reset_index(drop=True)

    return cov.merge(eld, on="geo_id", how="inner")[
        ["geo_id", "geo_name", "coverage", "elderly_base", "elderly_latest"]
    ]


def build_country_tables(
    datasets: Mapping[str, pd.DataFrame], params: Mapping[str, Any]
) -> dict[str, pd.DataFrame]:
    base, latest = int(params["base_year"]), int(params["latest_year"])
    return {
        "NO": _no_table(datasets, base, latest),
        "SE": _se_table(datasets, base, latest),
        "FI": _fi_table(datasets, base, latest),
    }


def kuhr_context(datasets: Mapping[str, pd.DataFrame], base: int, latest: int) -> tuple[dict[str, Any], dict[int, float]]:
    """National KUHR context: GP consultation volume (takst 2ad) and change.

    Returns (context dict for findings, per-year sums for the verify sidecar).
    """
    k = datasets.get("no_kuhr")
    if k is None or k.empty:
        return {}, {}
    by_year = k.groupby("aar")["antall_regninger"].sum()
    sums = {int(y): float(v) for y, v in by_year.items()}
    if base not in sums or latest not in sums:
        return {}, sums
    v_base, v_latest = sums[base], sums[latest]
    return {
        "kuhr_konsultasjoner_latest": int(v_latest),
        "kuhr_konsultasjoner_change_pct": round((v_latest - v_base) / v_base * 100, 1),
    }, sums


# ── analyze stage ────────────────────────────────────────────────────────────

def stage_analyze_nordisk(ctx: StageContext) -> None:
    params = ctx.config.params
    datasets = ctx.state["datasets"]
    tables = build_country_tables(datasets, params)
    # B2: per-country non-empty guard — an empty frame means the source failed
    # silently; raise loudly so a zero-data report is never published.
    _SOURCE_FOR_COUNTRY = {"NO": "no_kostra/no_befolkning", "SE": "se_hemtjanst/se_befolkning", "FI": "fi_homecare/fi_elderly_share"}
    for country, t in tables.items():
        if t.empty:
            src = _SOURCE_FOR_COUNTRY.get(country, country)
            raise PipelineGateError(
                f"nordisk analyze: empty frame for country '{country}' "
                f"(source: {src}) — ingest may have returned no rows"
            )
    squeezed = {c: squeeze_table(t) for c, t in tables.items()}

    full = pd.concat(
        [t.assign(country=c) for c, t in squeezed.items()], ignore_index=True
    )
    table_path = ctx.data_dir / "nordic_table.csv"
    full.to_csv(table_path, index=False)
    drops = {c: int(t.attrs.get("n_dropped", 0)) for c, t in squeezed.items()}
    (ctx.data_dir / "nordic_drops.json").write_text(
        json.dumps(drops), encoding="utf-8"
    )
    write_manifest(table_path, artifact="nordic_table", producer="analyze")

    context, kuhr_sums = kuhr_context(
        datasets, int(params["base_year"]), int(params["latest_year"])
    )
    (ctx.data_dir / "nordic_context.json").write_text(
        json.dumps({"by_year": {str(y): v for y, v in kuhr_sums.items()},
                    **context}, ensure_ascii=False),
        encoding="utf-8",
    )
    findings = findings_from_tables(squeezed, params, context)
    findings_path = ctx.data_dir / "nordic_findings.json"
    findings_path.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validate_artifact("nordic_findings", findings)
    write_manifest(findings_path, artifact="nordic_findings", producer="analyze",
                   inputs=[str(table_path)])
    ctx.state["nordic_findings"] = findings
    ctx.artifacts["nordic_table"] = table_path
    ctx.artifacts["findings"] = findings_path


# ── verify stage (tool receipts: independent recompute from disk) ────────────

def _check(claims: list[dict[str, Any]], name: str, expected: Any, actual: Any,
           tol: float = 1e-6) -> None:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        ok = abs(float(expected) - float(actual)) <= tol
    else:
        ok = expected == actual
    claims.append({"claim": name, "expected": expected, "actual": actual, "ok": ok})


def stage_verify_nordisk(ctx: StageContext) -> None:
    findings = ctx.state.get("nordic_findings")
    if findings is None:
        findings = json.loads(
            (ctx.data_dir / "nordic_findings.json").read_text(encoding="utf-8")
        )
    table = pd.read_csv(ctx.data_dir / "nordic_table.csv")
    drops = json.loads(
        (ctx.data_dir / "nordic_drops.json").read_text(encoding="utf-8")
    )

    claims: list[dict[str, Any]] = []
    for country, c in findings["countries"].items():
        t = table[table["country"] == country]
        _check(claims, f"{country}.n_municipalities", c["n_municipalities"], len(t))
        _check(claims, f"{country}.n_dropped", c["n_dropped"], drops.get(country, 0))
        _check(claims, f"{country}.coverage_median", c["coverage_median"],
               round(float(t["coverage"].median()), 2), tol=0.005)
        _check(claims, f"{country}.growth_median", c["growth_median"],
               round(float(t["growth_pct"].median()), 2), tol=0.005)
        gro_med = float(t["growth_pct"].median())
        cov_med = float(t["coverage"].median())
        high = float(((t["growth_pct"] > gro_med) & (t["coverage"] < cov_med)).mean())
        _check(claims, f"{country}.high_squeeze_share", c["high_squeeze_share"],
               round(high, 4), tol=0.0005)
        t_sorted = t.sort_values("squeeze", ascending=False).reset_index(drop=True)
        for row in c["top_squeeze"]:
            i = int(row["rank"]) - 1
            if i >= len(t_sorted):
                _check(claims, f"{country}.top{row['rank']}.exists",
                       row["geo_id"], "<missing>")
                continue
            actual = t_sorted.iloc[i]
            _check(claims, f"{country}.top{row['rank']}.geo_id",
                   row["geo_id"], str(actual["geo_id"]))
            _check(claims, f"{country}.top{row['rank']}.geo_name",
                   row["geo_name"], str(actual["geo_name"]))
            _check(claims, f"{country}.top{row['rank']}.squeeze",
                   row["squeeze"], round(float(actual["squeeze"]), 3), tol=0.005)
            _check(claims, f"{country}.top{row['rank']}.coverage",
                   row["coverage"], round(float(actual["coverage"]), 2), tol=0.005)
            _check(claims, f"{country}.top{row['rank']}.growth_pct",
                   row["growth_pct"], round(float(actual["growth_pct"]), 2), tol=0.005)

    shares = {k: v["high_squeeze_share"] for k, v in findings["countries"].items()}
    _check(claims, "comparison.lowest_high_squeeze_share_country",
           findings["comparison"]["lowest_high_squeeze_share_country"],
           min(shares, key=shares.get))

    ctx_f = findings.get("context", {})
    if ctx_f.get("kuhr_konsultasjoner_latest") is not None:
        side = json.loads(
            (ctx.data_dir / "nordic_context.json").read_text(encoding="utf-8")
        )
        by_year = {int(k): float(v) for k, v in side["by_year"].items()}
        latest = int(findings["analysis_years"]["latest"])
        base = int(findings["analysis_years"]["base"])
        _check(claims, "context.kuhr_konsultasjoner_latest",
               ctx_f["kuhr_konsultasjoner_latest"], int(by_year[latest]))
        _check(claims, "context.kuhr_konsultasjoner_change_pct",
               ctx_f["kuhr_konsultasjoner_change_pct"],
               round((by_year[latest] - by_year[base]) / by_year[base] * 100, 1),
               tol=0.05)

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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    validate_artifact("verification", payload)
    write_manifest(path, artifact="verification", producer="verify",
                   inputs=[str(ctx.data_dir / "nordic_findings.json"),
                           str(ctx.data_dir / "nordic_table.csv")])
    ctx.artifacts["verification"] = path
    ctx.state["nordic_verification"] = payload
    if payload["verdict"] != "PASS":
        raise PipelineGateError(
            f"nordisk verify FAIL: {payload['failed']}/{payload['total_claims']} "
            f"claims — {payload['failures'][:3]}"
        )


# ── report stage (bokmål; numbers ONLY from findings dict) ───────────────────

def _fig_scatter(table: pd.DataFrame, out_dir) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), sharey=False)
    for ax, country in zip(axes, ("NO", "SE", "FI")):
        t = table[table["country"] == country]
        ax.scatter(t["coverage"], t["growth_pct"], s=12, alpha=0.6)
        ax.axvline(t["coverage"].median(), ls="--", lw=0.8, color="grey")
        ax.axhline(t["growth_pct"].median(), ls="--", lw=0.8, color="grey")
        ax.set_title(f"{country} ({COUNTRY_AGE_CUT[country]})")
        ax.set_xlabel("Dekning hjemmetjeneste (%)")
    axes[0].set_ylabel("Vekst eldre befolkning (%)")
    fig.suptitle("Dekning vs. aldring per kommune (høy skvis = oppe til venstre)")
    fig.tight_layout()
    p = out_dir / "nordisk_scatter.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def _fig_box(table: pd.DataFrame, out_dir) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    data = [table[table["country"] == c]["squeeze"] for c in ("NO", "SE", "FI")]
    ax.boxplot(data, tick_labels=["NO (80+)", "SE (80+)", "FI (75+)"])
    ax.set_ylabel("Skvis-skår (z-differanse, innen land)")
    ax.set_title("Fordeling av skvis-skår per land")
    fig.tight_layout()
    p = out_dir / "nordisk_skvis_fordeling.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def _fig_top_no(table: pd.DataFrame, out_dir, top_n: int) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = (table[table["country"] == "NO"]
         .sort_values("squeeze", ascending=False).head(top_n).iloc[::-1])
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(t["geo_name"], t["squeeze"])
    ax.set_xlabel("Skvis-skår")
    ax.set_title(f"Topp {top_n} norske kommuner etter skvis-skår")
    fig.tight_layout()
    p = out_dir / "nordisk_topp_no.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    return p.name


def _country_section(name_nb: str, c: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {r['rank']} | {r['geo_name']} (`{r['geo_id']}`) | {r['squeeze']} "
        f"| {r['coverage']} | {r['growth_pct']} |"
        for r in c["top_squeeze"]
    )
    return f"""### {name_nb} (aldersgrense {c['age_cut']})

{c['n_municipalities']} kommuner i analysen ({c['n_dropped']} rader utelatt:
manglende/supprimerte verdier eller historiske kommunenummer). Median dekning: **{c['coverage_median']} %**. Median vekst i
eldre befolkning: **{c['growth_median']} %**. Andel kommuner i
høy-skvis-kvadranten: **{c['high_squeeze_share']}**.

| # | Kommune | Skvis | Dekning (%) | Eldrevekst (%) |
|---|---------|-------|-------------|----------------|
{rows}
"""


def stage_report_nordisk(ctx: StageContext) -> None:
    verification = ctx.state.get("nordic_verification")
    if verification is None or verification.get("verdict") != "PASS":
        raise PipelineGateError(
            "nordisk report requires a green verification artifact"
        )
    findings = ctx.state["nordic_findings"]
    table = pd.read_csv(ctx.data_dir / "nordic_table.csv")
    # B2: per-country non-empty guard at report stage
    _SOURCE_FOR_COUNTRY = {"NO": "no_kostra/no_befolkning", "SE": "se_hemtjanst/se_befolkning", "FI": "fi_homecare/fi_elderly_share"}
    for country in ("NO", "SE", "FI"):
        t = table[table["country"] == country]
        if t.empty:
            src = _SOURCE_FOR_COUNTRY.get(country, country)
            raise PipelineGateError(
                f"nordisk report: empty frame for country '{country}' "
                f"(source: {src}) — cannot produce a credible report"
            )
    fig_dir = ctx.reports_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    top_n = int(ctx.config.params.get("top_n", 10))
    figs = [_fig_scatter(table, fig_dir), _fig_box(table, fig_dir),
            _fig_top_no(table, fig_dir, top_n)]

    f = findings
    years = f["analysis_years"]
    comp = f["comparison"]["lowest_high_squeeze_share_country"]
    comp_nb = {"NO": "Norge", "SE": "Sverige", "FI": "Finland"}[comp]
    ctx_block = ""
    if f.get("context", {}).get("kuhr_konsultasjoner_latest"):
        n_kons = f"{f['context']['kuhr_konsultasjoner_latest']:,}".replace(",", " ")
        chg_pct_raw = f['context']['kuhr_konsultasjoner_change_pct']
        # nb-NO number formatting: comma decimal, minus sign prefix
        chg_pct_nb = f"{chg_pct_raw:+.1f}".replace(".", ",").replace("+", "").replace("-", "−")
        ctx_block = (
            f"\nKontekst (KUHR, åpne helserefusjonsdata): {n_kons} "
            f"fastlegekonsultasjoner (takst 2ad) i {years['latest']}, en endring på "
            f"{chg_pct_nb} % siden {years['base']}. "
            f"Fastlegekonsultasjonsvolum brukes her som kontekst-proxy for trykket på "
            f"kommunal primærhelsetjeneste — nedgang kan reflektere økt kapasitet, men "
            f"kan også gjenspeile endret behov eller rapporteringsendringer.\n"
        )

    sections = "\n".join(
        _country_section(nb, f["countries"][cc])
        for cc, nb in (("NO", "Norge"), ("SE", "Sverige"), ("FI", "Finland"))
    )
    report = f"""# Nordisk omsorgsradar: aldring vs. hjemmetjenestekapasitet

**Spørsmål:** {ctx.config.analysis['analysis']['question']}

**Metode.** For hver kommune beregner vi (1) dekning av hjemmetjenester blant
eldre, (2) prosentvis vekst i eldre befolkning {years['base']}–{years['latest']},
og (3) en skvis-skår: z-skår for eldrevekst minus z-skår for dekning,
normalisert **innen hvert land**. Høy skår = sterk aldring kombinert med lav
dekning. Alle tall er beregnet av kode og kontrollregnet av en uavhengig
verifiseringsmodul før denne rapporten ble generert
(verifisering: {ctx.state['nordic_verification']['passed']}/{ctx.state['nordic_verification']['total_claims']} kontroller OK —
én uavhengig omregning per rangert kommune pluss nasjonale aggregater per land).

## Funn per land

{sections}

## Sammenligning på tvers — med forbehold

Indikatorene er **ikke direkte sammenlignbare** mellom land: Norge og Sverige
måler dekning for 80+, Finland for 75+, og tjenestedefinisjonene er ulike.
Vi sammenligner derfor bare *mønstre innen land*. Andelen kommuner i
høy-skvis-kvadranten (eldrevekst over median OG dekning under median) er
lavest i **{comp_nb}**.
{ctx_block}
## Forbehold

- Analysen er **deskriptiv, ikke kausal** — rangerer og beskriver; forklarer ikke.
- Aldersgrenser: NO/SE 80+, FI 75+. Definisjoner av hjemmetjeneste varierer.
- Utelatte rader er talt opp per land (se tabellene); for Norge omfatter de
  både kommuner med supprimerte verdier og historiske kommunenummer fra
  KOSTRA-/befolkningshistorikken.
- Datakilder: SSB (KOSTRA 12209, befolkning 07459), Kolada/RKA (N21704,
  Socialstyrelsen-data), SCB (BefolkningNy), THL Sotkanet (5513, 171, 127),
  Helsedirektoratet/NAV KUHR. Åpne data, lisenser tillater viderebruk.

## Figurer

{chr(10).join(f"![figur](figures/{name})" for name in figs)}

---

*Rapporten er generert av omsorgsradar-pipelinen; alle tall kommer fra
`nordic_findings.json` og er verifisert mot `nordic_table.csv`.*
"""
    ctx.reports_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.reports_dir / "nordisk-omsorg_rapport.md"
    path.write_text(report, encoding="utf-8")
    write_manifest(path, artifact="nordic_report", producer="report",
                   inputs=[str(ctx.data_dir / "nordic_findings.json")])
    ctx.artifacts["report"] = path
    logger.info("Nordisk rapport: %s", path)


# ── instance registration (G0 extension point) ───────────────────────────────

def register(registry: StageRegistry) -> None:
    registry.register("analyze", stage_analyze_nordisk, override=True)
    registry.register("verify", stage_verify_nordisk, override=True)
    registry.register("report", stage_report_nordisk, override=True)
