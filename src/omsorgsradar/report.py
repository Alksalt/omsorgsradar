"""Report module — bokmål markdown report + matplotlib figures.

Two rendering paths:
1. **LLM path** (requires ``ANTHROPIC_API_KEY``): narrates pre-computed
   findings JSON into a polished bokmål report using the Anthropic API.
2. **Template path** (key-free): deterministic template renderer produces
   the same report from the same structured JSON.

The choice is made at runtime; both paths produce the same schema.

Figures:
- ``press_index_bar.png``: top-20 kommuner by press index (horizontal bar chart)
- ``coverage_scatter.png``: coverage rate vs 80+ growth rate scatter plot
- ``national_trend.png``: national 80+ population trend + projection
- ``press_index_choropleth.png``: choropleth map of press index per kommune
"""

from __future__ import annotations

import json
import logging
from datetime import date
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend for server-side rendering
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from .analyze import AnalysisResult, KommuneMetrics
from .verify import Verifier, build_standard_claims, VerificationReport

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent / "reports"
FIGURES_DIR = REPORT_DIR / "figures"
REPORT_MD_PATH = REPORT_DIR / "omsorgsradar_rapport.md"


# ──────────────────────────────────────────────────────────────────────────────
# Figures
# ──────────────────────────────────────────────────────────────────────────────


def _package_version() -> str:
    try:
        return _pkg_version("omsorgsradar")
    except PackageNotFoundError:
        return "dev"


def _report_header_line() -> str:
    return (
        f"*Analysedato: {date.today().isoformat()} · "
        f"Kilde: SSB KOSTRA + SSB befolkning · Versjon: {_package_version()}*"
    )


def _safe_name(navn: str, knr: str) -> str:
    """Return a display name: prefer navn, fall back to knr."""
    return navn.strip() if navn.strip() else knr


def plot_press_index_bar(
    result: AnalysisResult,
    n: int = 20,
    out_dir: Path = FIGURES_DIR,
) -> Path:
    """Plot top-*n* kommuner by normalised press index as a horizontal bar chart.

    Args:
        result: Analysis result.
        n: Number of top kommuner to show.
        out_dir: Output directory for the figure.

    Returns:
        Path to the saved figure.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "press_index_bar.png"

    top_n = [km for km in result.kommuner[:n] if not np.isnan(km.press_index_norm)]
    if not top_n:
        logger.warning("No data for press_index_bar plot")
        return out_path

    labels = [_safe_name(km.navn, km.knr) for km in top_n]
    values = [km.press_index_norm for km in top_n]
    colors = plt.cm.RdYlGn_r(np.linspace(0.1, 0.9, len(top_n)))  # type: ignore[arg-type]

    fig, ax = plt.subplots(figsize=(10, max(6, n * 0.4)))
    bars = ax.barh(range(len(top_n)), values, color=colors)
    ax.set_yticks(range(len(top_n)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Press-indeks (normalisert 0–1)", fontsize=11)
    ax.set_title(
        f"Topp {len(top_n)} kommuner — demografisk press-indeks mot 2035",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlim(0, 1.05)
    ax.grid(axis="x", alpha=0.3)

    # Add value labels
    for i, (bar, val) in enumerate(zip(bars, values)):
        ax.text(val + 0.01, i, f"{val:.2f}", va="center", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", out_path)
    return out_path


def plot_coverage_scatter(
    result: AnalysisResult,
    out_dir: Path = FIGURES_DIR,
) -> Path:
    """Scatter plot: coverage rate vs projected 80+ growth rate.

    Args:
        result: Analysis result.
        out_dir: Output directory.

    Returns:
        Path to the saved figure.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "coverage_scatter.png"

    kommuner = [
        km for km in result.kommuner
        if not np.isnan(km.coverage_rate)
        and not np.isnan(km.pop_80plus_growth_pct)
        and not np.isnan(km.press_index_norm)
    ]
    if not kommuner:
        logger.warning("No data for coverage scatter plot")
        return out_path

    x = [km.pop_80plus_growth_pct for km in kommuner]
    y = [km.coverage_rate for km in kommuner]
    colors = [km.press_index_norm for km in kommuner]
    sizes = [40 + km.press_index_norm * 120 for km in kommuner]

    fig, ax = plt.subplots(figsize=(10, 7))
    sc = ax.scatter(x, y, c=colors, s=sizes, cmap="RdYlGn_r", alpha=0.7, edgecolors="gray", linewidths=0.3)
    cbar = fig.colorbar(sc, ax=ax)
    cbar.set_label("Press-indeks (normalisert)", fontsize=10)

    # Annotate top-10 by press index
    top10 = sorted(kommuner, key=lambda k: k.press_index_norm, reverse=True)[:10]
    for km in top10:
        ax.annotate(
            _safe_name(km.navn, km.knr),
            (km.pop_80plus_growth_pct, km.coverage_rate),
            fontsize=7,
            xytext=(3, 3),
            textcoords="offset points",
        )

    ax.set_xlabel("Forventet vekst i 80+-befolkning mot 2035 (%)", fontsize=11)
    ax.set_ylabel("Hjemmetjeneste-brukere per 1000 innbygger 80+ (siste år)", fontsize=11)
    ax.set_title(
        "Omsorgskapasitet vs demografisk press — norske kommuner",
        fontsize=13, fontweight="bold",
    )
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", out_path)
    return out_path


def plot_national_trend(
    result: AnalysisResult,
    out_dir: Path = FIGURES_DIR,
) -> Path:
    """Bar chart showing national 80+ population baseline vs 2035 projection.

    Args:
        result: Analysis result.
        out_dir: Output directory.

    Returns:
        Path to the saved figure.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "national_trend.png"

    baseline = result.national_80plus_latest
    projected = result.national_80plus_2035
    growth = result.national_growth_rate_2035

    if np.isnan(baseline) or np.isnan(projected):
        logger.warning("No national trend data for plot")
        return out_path

    fig, ax = plt.subplots(figsize=(7, 5))
    years = ["Siste år (data)", "2035 (projeksjon)"]
    values = [baseline / 1000, projected / 1000]
    colors = ["#4C9BE8", "#E85C5C"]
    bars = ax.bar(years, values, color=colors, width=0.5, edgecolor="white")

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{val:,.0f}k",
            ha="center", va="bottom", fontsize=12, fontweight="bold",
        )

    ax.set_ylabel("Antall innbygger 80+ (tusen)", fontsize=11)
    ax.set_title(
        f"Nasjonal 80+-befolkning — vekst til 2035\n(+{growth:.1f}% om SSB-bane opprettholdes)",
        fontsize=12, fontweight="bold",
    )
    ax.set_ylim(0, max(values) * 1.2)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", out_path)
    return out_path


def plot_press_index_choropleth(
    result: AnalysisResult,
    out_dir: Path = FIGURES_DIR,
) -> Path | None:
    """Choropleth map of normalised press index per kommune (figure 4).

    Requires the committed asset ``assets/geo/kommuner_simplified.geojson``.
    If the asset is missing, logs a warning and returns None so the report
    still builds without the map figure.

    Args:
        result: Analysis result containing per-kommune press_index_norm values.
        out_dir: Output directory for the figure.

    Returns:
        Path to the saved PNG, or None if the asset is unavailable.
    """
    from .maps import render_choropleth, DEFAULT_GEO_PATH

    if not DEFAULT_GEO_PATH.exists():
        logger.warning(
            "Geo asset not found (%s) — skipping choropleth figure", DEFAULT_GEO_PATH
        )
        return None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "press_index_choropleth.png"

    # Build values dict: 4-digit zero-padded knr → press_index_norm
    # knr in findings is already a 4-digit string; zfill guards against edge cases
    # Use try/except for isnan to handle int/None from deserialized JSON as well
    def _is_valid(v: Any) -> bool:
        try:
            return not np.isnan(float(v))
        except (TypeError, ValueError):
            return False

    values: dict[str, float] = {
        km.knr.zfill(4): float(km.press_index_norm)
        for km in result.kommuner
        if _is_valid(km.press_index_norm)
    }

    attribution = "Kartgrunnlag: Kartverket via robhop/fylker-og-kommuner (CC BY 4.0)"
    choropleth_result = render_choropleth(
        DEFAULT_GEO_PATH,
        values,
        out_path,
        title="Press-indeks per kommune mot 2035",
        value_label="Press-indeks (normalisert 0–1)",
        attribution=attribution,
    )

    n_missing = choropleth_result["missing"]
    logger.info(
        "Choropleth: %d kommuner plottet, %d uten data (grå)",
        choropleth_result["plotted"],
        n_missing,
    )
    return out_path


# ──────────────────────────────────────────────────────────────────────────────
# Template renderer (deterministic, key-free path)
# ──────────────────────────────────────────────────────────────────────────────


def render_template(
    result: AnalysisResult,
    quality_report: dict[str, Any] | None = None,
    verification: VerificationReport | None = None,
    n_top: int = 20,
) -> str:
    """Render a bokmål markdown report from structured findings (no LLM).

    Args:
        result: Analysis result.
        quality_report: Optional data quality profile dict.
        verification: Optional verification report.
        n_top: Number of top kommuner to include in the ranking table.

    Returns:
        Markdown report string.
    """
    ranked = [km for km in result.kommuner if km.rank]
    top = [km for km in ranked[:n_top] if not np.isnan(km.press_index_norm)]
    n_total = len(result.kommuner)
    n_ranked = len(ranked)
    growth = result.national_growth_rate_2035
    baseline = result.national_80plus_latest
    projected = result.national_80plus_2035

    rank1 = next((km for km in ranked if km.rank == 1), None)
    rank1_name = _safe_name(rank1.navn, rank1.knr) if rank1 else "N/A"

    n_high = sum(
        1 for km in ranked
        if not np.isnan(km.press_index_norm) and km.press_index_norm >= 0.5
    )

    rates = [km.coverage_rate for km in ranked if not np.isnan(km.coverage_rate)]
    mean_rate = np.mean(rates) if rates else float("nan")

    lines: list[str] = []
    lines.append("# Kommunal Omsorgsradar — rapport")
    lines.append("")
    lines.append(_report_header_line())
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Sammendrag")
    lines.append("")
    lines.append(
        f"Analysen rangerer **{n_ranked} kommuner** (av {n_total} koderader — historiske "
        f"kommunenummer er ekskludert fra rangeringen) etter en press-indeks som kombinerer "
        f"forventet vekst i 80+-befolkningen mot 2035 med dagens dekning av hjemmetjenester."
    )
    lines.append("")
    if not np.isnan(growth):
        lines.append(
            f"På nasjonalt nivå vokser 80+-befolkningen med anslagsvis **{growth:.1f}%** "
            f"fra {baseline/1000:,.0f} 000 (siste datapunkt) til {projected/1000:,.0f} 000 i 2035 "
            f"dersom hver kommunes historiske trend (2017–2026) fortsetter. Dette er en "
            f"trendframskriving, ikke SSBs offisielle befolkningsframskriving — SSBs "
            f"hovedalternativ ligger høyere for 80+ (se Begrensninger)."
        )
        lines.append("")
    lines.append(
        f"**{n_high} kommuner** har press-indeks ≥ 0,5 og trenger særskilt planleggingsoppmerksomhet."
    )
    if not np.isnan(mean_rate):
        lines.append(
            f"Gjennomsnittlig dekningsgrad er **{mean_rate:.0f} %** "
            f"(andel innbyggere 80+ som mottar hjemmetjenester)."
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Metodikk og deskriptiv tolkning")
    lines.append("")
    lines.append(
        "Press-indeksen er et **deskriptivt planleggingsverktøy**, ikke et kausalt mål. "
        "Den beregnes som:"
    )
    lines.append("")
    lines.append("```")
    lines.append("press_indeks_rå = (80+_befolkning_2035 / 80+_befolkning_nå) × (1 / (dekningsrate + ε))")
    lines.append("press_indeks_norm = normalisert til [0, 1] på tvers av alle kommuner")
    lines.append("```")
    lines.append("")
    lines.append(
        "Høy indeks = rask vekst i eldre befolkning OG lav dekning av hjemmetjenester i dag. "
        "Tolkes som planleggingsbehov, ikke som klinisk beslutningsstøtte."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Rangering — topp " + str(len(top)) + " kommuner")
    lines.append("")
    lines.append("| Rang | Kommune | Press-indeks | Dekningsrate | Vekst 80+ mot 2035 |")
    lines.append("|------|---------|-------------|-------------|-------------------|")
    for km in top:
        cov = f"{km.coverage_rate:.0f}" if not np.isnan(km.coverage_rate) else "—"
        growth_str = f"{km.pop_80plus_growth_pct:.1f}%" if not np.isnan(km.pop_80plus_growth_pct) else "—"
        lines.append(
            f"| {km.rank} | {_safe_name(km.navn, km.knr)} | {km.press_index_norm:.3f} "
            f"| {cov} | {growth_str} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Figurer")
    lines.append("")
    lines.append("![Press-indeks topp 20](figures/press_index_bar.png)")
    lines.append("")
    lines.append("![Dekning vs vekst](figures/coverage_scatter.png)")
    lines.append("")
    lines.append("![Nasjonal trend](figures/national_trend.png)")
    lines.append("")
    lines.append("![Press-indeks koropleth](figures/press_index_choropleth.png)")
    lines.append("")
    lines.append(
        "*Kartgrunnlag: Kartverket via robhop/fylker-og-kommuner (CC BY 4.0). "
        "Kommuner uten data er vist i grått.*"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Datakvalitet")
    lines.append("")
    if quality_report:
        for ds_name, ds_info in quality_report.get("datasets", {}).items():
            lines.append(f"**{ds_name}**: {ds_info.get('n_rows', 'N/A')} rader "
                         f"· {ds_info.get('n_kommuner', 'N/A')} kommuner "
                         f"· kilde: {ds_info.get('source', 'N/A')}")
    else:
        lines.append("*Datakvalitetsprofil ikke tilgjengelig.*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Verifisering av tall (verktøykvitteringer)")
    lines.append("")
    if verification:
        lines.append(f"**Resultat: {verification.verdict}** — "
                     f"{verification.passed}/{verification.total_claims} påstander verifisert.")
        lines.append("")
        for r in verification.results:
            status = "✓" if r.passes else "✗"
            lines.append(f"- {status} `{r.claim.claim_type}` → {r.message}")
    else:
        lines.append("*Verifisering ikke kjørt.*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Begrensninger")
    lines.append("")
    lines.append(
        "Se [`LIMITATIONS.md`](../LIMITATIONS.md) for fullstendig liste. Viktigste forbehold: "
        "analysen er deskriptiv, ikke kausal; kommunesammenslåinger og omnummereringer håndteres "
        "via tabell regenerert fra SSB KLASS (t.o.m. 2024-bølgen, splittelser ekskludert); "
        "vekst per kommune er en trendframskriving (historisk CAGR 2017–2026 med vakter), ikke "
        "SSBs kommuneframskrivinger (tabell 13873 er ikke offentlig tilgjengelig)."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Rapporten er generert av omsorgsradar-pipeline v{_package_version()}.*")
    lines.append("*Utdannet lege (master i medisin) — Oleksandr Altukhov.*")
    lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# LLM renderer (optional)
# ──────────────────────────────────────────────────────────────────────────────


def render_llm(
    result: AnalysisResult,
    quality_report: dict[str, Any] | None = None,
    verification: VerificationReport | None = None,
    client: Any = None,
    model: str = "claude-sonnet-4-5",
    n_top: int = 20,
) -> tuple[str, dict[str, Any]]:
    """Narrate findings using a pre-built LLM client.

    Args:
        result: Analysis result.
        quality_report: Optional quality report dict.
        verification: Optional verification report.
        client: LLMClient instance (from core.endpoint.build_client).
        model: Model ID to pass to the client.
        n_top: Number of top kommuner to include.

    Returns:
        ``(report_markdown, cost_info)`` tuple.
    """
    from .analyze import result_to_dict

    findings_dict = result_to_dict(result)
    top_kommuner = findings_dict["kommuner"][:n_top]

    # Build a concise JSON payload for the LLM
    summary_payload = {
        "n_kommuner_total": len(result.kommuner),
        "national_80plus_latest": result.national_80plus_latest,
        "national_80plus_2035": result.national_80plus_2035,
        "national_growth_rate_2035": result.national_growth_rate_2035,
        "top_20_kommuner": [
            {
                "rank": km["rank"],
                "knr": km["knr"],
                "navn": km["navn"],
                "press_index_norm": km["press_index_norm"],
                "coverage_rate": km["coverage_rate"],
                "pop_80plus_growth_pct": km["pop_80plus_growth_pct"],
            }
            for km in top_kommuner
        ],
        "quality_notes": quality_report.get("datasets", {}) if quality_report else {},
        "verification_verdict": verification.verdict if verification else "NOT RUN",
    }

    prompt = f"""Du er dataanalytiker med ekspertise på norsk kommunehelsetjeneste.
Skriv en faglig bokmålsrapport basert på følgende forhåndsberegnede funn (du skal IKKE beregne noe selv):

```json
{json.dumps(summary_payload, ensure_ascii=False, indent=2)}
```

Rapporten skal:
1. Starte med en faglig sammendrag (3–4 setninger)
2. Gi en kortfattet metodebeskrivelse med eksplisitt «deskriptivt, ikke kausalt»-forbehold
3. Kommentere topp-10 kommuner (ikke liste alle 20 — rapporten inneholder allerede tabellen)
4. Avslutte med et kort avsnitt om planleggingsimplikasjoner for kommuner og Helsedirektoratet
5. Bruke presist fagspråk, unngå klisjeer, holde seg strengt til tallene i JSON-en

Ikke repeter tabellen. Ikke hallusiner nye tall. All tekst på bokmål."""

    resp = client.complete(prompt, model=model, max_tokens=2000)
    llm_text = resp.text
    from .core.endpoint import estimate_cost
    cost_info = {
        "model": model,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "estimated_cost_usd": estimate_cost(model, resp.input_tokens, resp.output_tokens),
    }

    # Combine: LLM intro + template table + verification block
    template_report = render_template(result, quality_report, verification, n_top)
    # Replace the summary section with LLM narration
    report = f"""# Kommunal Omsorgsradar — rapport

{_report_header_line()}

---

{llm_text}

---

## Rangering — topp {len(top_kommuner)} kommuner

| Rang | Kommune | Press-indeks | Dekningsrate | Vekst 80+ mot 2035 |
|------|---------|-------------|-------------|-------------------|
"""
    for km in result.kommuner[:n_top]:
        if np.isnan(km.press_index_norm):
            continue
        cov = f"{km.coverage_rate:.0f}" if not np.isnan(km.coverage_rate) else "—"
        growth_str = f"{km.pop_80plus_growth_pct:.1f}%" if not np.isnan(km.pop_80plus_growth_pct) else "—"
        report += (
            f"| {km.rank} | {_safe_name(km.navn, km.knr)} | {km.press_index_norm:.3f} "
            f"| {cov} | {growth_str} |\n"
        )

    report += """
---

## Figurer

![Press-indeks topp 20](figures/press_index_bar.png)

![Dekning vs vekst](figures/coverage_scatter.png)

![Nasjonal trend](figures/national_trend.png)

---

*Rapporten er generert av omsorgsradar-pipeline v0.1.0 med LLM-narrasjon.*
*Utdannet lege (master i medisin) — Oleksandr Altukhov.*
"""

    return report, cost_info


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────────


def run_report(
    result: AnalysisResult,
    quality_report: dict[str, Any] | None = None,
    report_dir: Path = REPORT_DIR,
    use_llm: bool | None = None,
    workflow: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Generate the full report: figures + markdown.

    Args:
        result: Analysis result.
        quality_report: Optional quality report dict.
        report_dir: Output directory for the report.
        use_llm: If False, force template path. If None, defer to workflow config.
        workflow: Workflow config dict (from workflow.toml). If None, use template path.

    Returns:
        ``(report_path, cost_info)`` tuple.
    """
    report_dir = Path(report_dir)
    figures_dir = report_dir / "figures"
    report_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    # Generate figures
    plot_press_index_bar(result, out_dir=figures_dir)
    plot_coverage_scatter(result, out_dir=figures_dir)
    plot_national_trend(result, out_dir=figures_dir)
    plot_press_index_choropleth(result, out_dir=figures_dir)

    # Verify findings
    verifier = Verifier(result)
    claims = build_standard_claims(result)
    verification = verifier.verify_all(claims)

    from .core.endpoint import build_client
    cost_info: dict[str, Any] = {"path": "key-free template renderer", "renderer": "template"}

    client, model = (None, None)
    if workflow is not None and use_llm is not False:
        client, model = build_client(workflow, role="report")

    if client is not None and model is not None:
        try:
            report_md, cost_info = render_llm(result, quality_report, verification,
                                              client=client, model=model)
            cost_info["renderer"] = "llm"
        except Exception as exc:
            logger.warning("LLM renderer failed (%s); falling back to template", exc)
            report_md = render_template(result, quality_report, verification)
            cost_info = {"renderer": "template_fallback", "error": str(exc)}
    else:
        report_md = render_template(result, quality_report, verification)

    report_path = report_dir / "omsorgsradar_rapport.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("Report written to %s", report_path)

    return report_path, cost_info
