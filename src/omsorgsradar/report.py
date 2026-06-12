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
from .fmt import nb, nb_pct, nb_index
from .core.endpoint import MODEL_PRICING

logger = logging.getLogger(__name__)

REPORT_DIR = Path(__file__).parent.parent.parent / "reports"
FIGURES_DIR = REPORT_DIR / "figures"
REPORT_MD_PATH = REPORT_DIR / "omsorgsradar_rapport.md"


# ──────────────────────────────────────────────────────────────────────────────
# Default model resolution (A6)
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_default_model() -> str:
    """Pick the default LLM model for report narration.

    Prefers ``claude-fable-5`` if present in MODEL_PRICING; otherwise falls
    back to the first key in MODEL_PRICING. Never a bare string literal.
    """
    if "claude-fable-5" in MODEL_PRICING:
        return "claude-fable-5"
    return next(iter(MODEL_PRICING))


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

    Colormap: sequential Reds-family (dark = highest press / worst).
    Value labels use nb_index formatting (same precision as the table).

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

    # Sequential Reds: dark = high press (worst). linspace 0.3→0.95 so the top
    # bar is near-black-red and bottom is pale pink. Invert: first bar (rank 1,
    # highest press) gets the darkest shade.
    cmap = plt.cm.Reds  # type: ignore[attr-defined]
    # We want rank-1 (highest value) → darkest → linspace descending from 0.95 to 0.3
    n_bars = len(top_n)
    # values are already sorted descending (highest press first)
    color_intensities = np.linspace(0.95, 0.3, n_bars)
    colors = [cmap(v) for v in color_intensities]

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

    # Value labels: nb_index (two-decimal, Norwegian format — same precision as table)
    for i, (bar, val) in enumerate(zip(bars, values)):
        ax.text(val + 0.01, i, nb_index(val), va="center", fontsize=8)

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

    Colormap: sequential Reds-family (dark = highest press / worst).
    y-label: «Andel innbyggere 80+ som mottar hjemmetjenester (%)».

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
    # Reds colormap: high press_index_norm → dark red (worst). vmin/vmax anchor semantics.
    sc = ax.scatter(x, y, c=colors, s=sizes, cmap="Reds", alpha=0.7,
                    edgecolors="gray", linewidths=0.3, vmin=0.0, vmax=1.0)
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
    ax.set_ylabel("Andel innbyggere 80+ som mottar hjemmetjenester (%)", fontsize=11)
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
    """Bar chart: national 80+ population baseline vs 2035 trendframskriving.

    Title uses nb-NO formatting for growth rate and SSB MMM rate.
    Right bar labeled «2035 (trendframskriving)».
    Horizontal reference line at SSB-MMM 2035 absolute level (if available).

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

    ssb = result.ssb_projection_growth_2035
    ssb_available = not np.isnan(ssb)

    # Build title with nb-NO formatting
    growth_str = nb_pct(growth)
    if ssb_available:
        title = (
            f"Nasjonal 80+-befolkning — trendframskriving til 2035\n"
            f"(+{growth_str}; SSBs MMM-bane: +{nb_pct(ssb)})"
        )
    else:
        title = (
            f"Nasjonal 80+-befolkning — trendframskriving til 2035\n"
            f"(+{growth_str})"
        )

    fig, ax = plt.subplots(figsize=(7, 5))
    years = ["Siste år (data)", "2035 (trendframskriving)"]
    values = [baseline / 1000, projected / 1000]
    colors = ["#4C9BE8", "#E85C5C"]
    bars = ax.bar(years, values, color=colors, width=0.5, edgecolor="white")

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{nb(val, decimals=0)}k",
            ha="center", va="bottom", fontsize=12, fontweight="bold",
        )

    # SSB MMM reference line at the absolute 2035 level
    if ssb_available:
        ssb_level = baseline / 1000 * (1 + ssb / 100)
        ax.axhline(y=ssb_level, color="#333333", linewidth=1.5, linestyle="--", alpha=0.7)
        ax.text(
            1.02, ssb_level,
            "SSB MMM",
            va="center", ha="left", fontsize=9, color="#333333",
            transform=ax.get_yaxis_transform(),
        )

    ax.set_ylabel("Antall innbyggere 80+ (tusen)", fontsize=11)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_ylim(0, max(values) * 1.25)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", out_path)
    return out_path


def plot_press_index_choropleth(
    result: AnalysisResult,
    out_dir: Path = FIGURES_DIR,
    map_anchor_knrs: list[str] | None = None,
) -> Path | None:
    """Choropleth map of normalised press index per kommune (figure 4).

    Requires the committed asset ``assets/geo/kommuner_simplified.geojson``.
    If the asset is missing, logs a warning and returns None so the report
    still builds without the map figure.

    Colormap: Reds (dark = high press / worst). Top-10 ranked kommuner and
    any codes in *map_anchor_knrs* are labeled at polygon centroids.

    Args:
        result: Analysis result containing per-kommune press_index_norm values.
        out_dir: Output directory for the figure.
        map_anchor_knrs: Optional list of 4-digit kommunenummer strings to label
            as anchor points (e.g. city anchors ["0301","4601","5001","1103"]).
            Defaults to [] when None.

    Returns:
        Path to the saved PNG, or None if the asset is unavailable.
    """
    from .maps import render_choropleth, render_choropleth_with_labels, DEFAULT_GEO_PATH

    if not DEFAULT_GEO_PATH.exists():
        logger.warning(
            "Geo asset not found (%s) — skipping choropleth figure", DEFAULT_GEO_PATH
        )
        return None

    if map_anchor_knrs is None:
        map_anchor_knrs = []

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "press_index_choropleth.png"

    # Build values dict: 4-digit zero-padded knr → press_index_norm
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

    # Collect top-10 knrs by press index
    ranked_with_values = [
        (km.knr.zfill(4), km.rank)
        for km in result.kommuner
        if km.rank and km.rank >= 1 and _is_valid(km.press_index_norm)
    ]
    top10_knrs = {knr for knr, rank in ranked_with_values if rank <= 10}

    # Combine anchor knrs (cities) and top-10 into label set
    label_knrs: set[str] = set(map_anchor_knrs) | top10_knrs

    # Build knr → name map for labels
    knr_to_name: dict[str, str] = {
        km.knr.zfill(4): _safe_name(km.navn, km.knr)
        for km in result.kommuner
    }

    attribution = "Kartgrunnlag: Kartverket via robhop/fylker-og-kommuner (CC BY 4.0)"
    choropleth_result = render_choropleth_with_labels(
        DEFAULT_GEO_PATH,
        values,
        out_path,
        title="Press-indeks per kommune mot 2035",
        value_label="Press-indeks (normalisert 0–1)",
        attribution=attribution,
        cmap_name="Reds",
        label_knrs=label_knrs,
        knr_to_name=knr_to_name,
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
    choropleth_available: bool = True,
) -> str:
    """Render a bokmål markdown report from structured findings (no LLM).

    Args:
        result: Analysis result.
        quality_report: Optional data quality profile dict.
        verification: Optional verification report (gate's report when provided;
            rebuilt from result when None).
        n_top: Number of top kommuner to include in the ranking table.
        choropleth_available: If False, the choropleth img link is omitted
            (prevents dead links when the geo asset is absent).

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
    rank1_name = _safe_name(rank1.navn, rank1.knr) if rank1 else "—"

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
        f"kommunenummer og kommuner uten beregnbar dekningsgrad er ekskludert fra rangeringen) "
        f"etter en press-indeks som kombinerer forventet vekst i 80+-befolkningen mot 2035 med "
        f"dagens dekning av hjemmetjenester."
    )
    lines.append("")
    if not np.isnan(growth):
        proj = result.ssb_projection_growth_2035
        proj_base = result.ssb_projection_baseline_year
        if not np.isnan(proj):
            ssb_clause = (
                f"Dette er en trendframskriving, ikke SSBs offisielle "
                f"befolkningsframskriving: SSBs hovedalternativ (tabell 13599, "
                f"alternativ MMM) gir til sammenligning **~{nb_pct(proj, decimals=0)}** vekst for "
                f"80+ fra {proj_base} til 2035 — vesentlig raskere (se Begrensninger)."
            )
        else:
            ssb_clause = (
                "Dette er en trendframskriving, ikke SSBs offisielle "
                "befolkningsframskriving (se Begrensninger)."
            )
        baseline_k = nb(baseline / 1000, decimals=0)
        projected_k = nb(projected / 1000, decimals=0)
        lines.append(
            f"På nasjonalt nivå vokser 80+-befolkningen med anslagsvis **{nb_pct(growth)} **"
            f"fra {baseline_k} 000 (siste datapunkt) til {projected_k} 000 i 2035 "
            f"dersom hver kommunes historiske trend (2017–2026) fortsetter. {ssb_clause}"
        )
        lines.append("")
    lines.append(
        f"**{n_high} kommuner** har press-indeks ≥ 0,5 og trenger særskilt planleggingsoppmerksomhet."
    )
    if not np.isnan(mean_rate):
        lines.append(
            f"Gjennomsnittlig dekningsgrad er **{nb(mean_rate, decimals=0)} %** "
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
        cov = nb(km.coverage_rate, decimals=0) if not np.isnan(km.coverage_rate) else "—"
        growth_str = nb_pct(km.pop_80plus_growth_pct) if not np.isnan(km.pop_80plus_growth_pct) else "—"
        lines.append(
            f"| {km.rank} | {_safe_name(km.navn, km.knr)} | {nb_index(km.press_index_norm)} "
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
    if choropleth_available:
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
        _render_quality_block(lines, quality_report)
    else:
        lines.append("*Datakvalitetsprofil ikke tilgjengelig.*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Verifisering av tall (verktøykvitteringer)")
    lines.append("")
    _render_verification_block(lines, verification)
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


def _render_quality_block(lines: list[str], quality_report: dict[str, Any]) -> None:
    """Render the Datakvalitet section into *lines* in-place.

    Rules (A4):
    - Zero-row sources are suppressed from the table and replaced by a
      one-sentence bokmål note per suppressed source.
    - «—» instead of «N/A» for missing counts.
    - The «befolkning» row is annotated with koderader and active kommuner counts
      derived from the quality report data.
    """
    datasets = quality_report.get("datasets", {})
    suppressed: list[str] = []
    shown: list[tuple[str, dict[str, Any]]] = []

    for ds_name, ds_info in datasets.items():
        n_rows = ds_info.get("n_rows")
        try:
            rows_val = int(n_rows)
        except (TypeError, ValueError):
            rows_val = -1  # unknown → show

        if rows_val == 0:
            suppressed.append(ds_name)
        else:
            shown.append((ds_name, ds_info))

    # Render the table for non-zero sources
    for ds_name, ds_info in shown:
        n_rows = ds_info.get("n_rows")
        n_kommuner = ds_info.get("n_kommuner")
        source = ds_info.get("source", "—")

        # Format with «—» for None/unknown
        rows_str = str(n_rows) if n_rows is not None else "—"
        kom_str = str(n_kommuner) if n_kommuner is not None else "—"

        # Special annotation for befolkning: show koderader breakdown
        if ds_name == "befolkning" and n_rows is not None and n_kommuner is not None:
            try:
                nr = int(n_rows)
                nk = int(n_kommuner)
                historical = nr - nk
                annotation = f" ({nr} koderader — {nk} aktive kommuner + {historical} historiske koder)"
            except (TypeError, ValueError):
                annotation = ""
            lines.append(
                f"**{ds_name}**: {rows_str} rader{annotation} · kilde: {source}"
            )
        else:
            lines.append(
                f"**{ds_name}**: {rows_str} rader · {kom_str} kommuner · kilde: {source}"
            )

    # One sentence per suppressed source
    for ds_name in suppressed:
        # Map known source names to a bokmål explanation
        if "fhi" in ds_name.lower() or "nokkel" in ds_name.lower():
            lines.append(
                f"FHI NOKKEL er ekskludert — API-et er utilgjengelig."
            )
        else:
            lines.append(
                f"*{ds_name}* er ekskludert — ingen rader mottatt."
            )


def _render_verification_block(lines: list[str], verification: VerificationReport | None) -> None:
    """Render the verification section into *lines* in-place.

    When *verification* is the gate's own report (A8), it renders the full
    passed/total count with a one-clause gloss of what a «kontroll» is.
    When None, shows a «not run» notice.
    """
    if verification is None:
        lines.append("*Verifisering ikke kjørt.*")
        return

    lines.append(
        f"**Resultat: {verification.verdict}** — "
        f"{verification.passed}/{verification.total_claims} kontroller bestått "
        f"(narrasjonssjekker + uavhengige DB-kvitteringer)."
    )
    lines.append("")
    for r in verification.results:
        status = "✓" if r.passes else "✗"
        lines.append(f"- {status} `{r.claim.claim_type}` → {r.message}")


# ──────────────────────────────────────────────────────────────────────────────
# LLM renderer (optional)
# ──────────────────────────────────────────────────────────────────────────────


def render_llm(
    result: AnalysisResult,
    quality_report: dict[str, Any] | None = None,
    verification: VerificationReport | None = None,
    client: Any = None,
    model: str | None = None,
    n_top: int = 20,
) -> tuple[str, dict[str, Any]]:
    """Narrate findings using a pre-built LLM client.

    Args:
        result: Analysis result.
        quality_report: Optional quality report dict.
        verification: Optional verification report.
        client: LLMClient instance (from core.endpoint.build_client).
        model: Model ID to pass to the client. When None, resolved to a key
            that exists in MODEL_PRICING (prefers «claude-fable-5»).
        n_top: Number of top kommuner to include.

    Returns:
        ``(report_markdown, cost_info)`` tuple.
    """
    # A6: resolve default model — never a bare string literal outside MODEL_PRICING
    if model is None:
        model = _resolve_default_model()

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
6. Bruke norsk tallformat: komma som desimaltegn, mellomrom som tusenskilletegn (f.eks. «31,1 %»)

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
    # Build table rows with nb-NO formatting
    table_rows = ""
    for km in result.kommuner[:n_top]:
        if np.isnan(km.press_index_norm):
            continue
        cov = nb(km.coverage_rate, decimals=0) if not np.isnan(km.coverage_rate) else "—"
        growth_str = nb_pct(km.pop_80plus_growth_pct) if not np.isnan(km.pop_80plus_growth_pct) else "—"
        table_rows += (
            f"| {km.rank} | {_safe_name(km.navn, km.knr)} | {nb_index(km.press_index_norm)} "
            f"| {cov} | {growth_str} |\n"
        )

    report = f"""# Kommunal Omsorgsradar — rapport

{_report_header_line()}

---

{llm_text}

---

## Rangering — topp {len(top_kommuner)} kommuner

| Rang | Kommune | Press-indeks | Dekningsrate | Vekst 80+ mot 2035 |
|------|---------|-------------|-------------|-------------------|
{table_rows}
---

## Figurer

![Press-indeks topp 20](figures/press_index_bar.png)

![Dekning vs vekst](figures/coverage_scatter.png)

![Nasjonal trend](figures/national_trend.png)

---

*Rapporten er generert av omsorgsradar-pipeline v{_package_version()} med LLM-narrasjon.*
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
    verification: VerificationReport | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Generate the full report: figures + markdown.

    Args:
        result: Analysis result.
        quality_report: Optional quality report dict.
        report_dir: Output directory for the report.
        use_llm: If False, force template path. If None, defer to workflow config.
        workflow: Workflow config dict (from workflow.toml). If None, use template path.
        verification: Optional gate VerificationReport. When provided, the report's
            verification block renders this report (A8). When None, rebuilds from result.
        params: Optional params dict (e.g. from analysis.toml). Used to extract
            report.map_anchor_knrs for the choropleth.

    Returns:
        ``(report_path, cost_info)`` tuple.

    Raises:
        RuntimeError: If any required figure fails to render or its PNG is missing
            after the call (A5). The choropleth is exempted — it may be skipped when
            the geo asset is absent, but the template then omits its img link.
    """
    report_dir = Path(report_dir)
    figures_dir = report_dir / "figures"
    report_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    # Extract map_anchor_knrs from params (A3)
    map_anchor_knrs: list[str] = []
    if params:
        map_anchor_knrs = list(params.get("report", {}).get("map_anchor_knrs", []))

    # ── Figure generation with guards (A5) ──────────────────────────────────
    # Required figures: bar, scatter, trend. Choropleth is optional (skip-if-no-asset).
    missing_figures: list[str] = []

    def _guarded_plot(fn_name: str, plot_fn, *args, **kwargs) -> Path | None:
        """Call plot_fn(*args, **kwargs). Collect name if PNG absent after call."""
        try:
            out = plot_fn(*args, **kwargs)
        except Exception as exc:
            logger.error("Figure %s raised: %s", fn_name, exc)
            missing_figures.append(fn_name)
            return None
        if out is not None and not Path(out).exists():
            logger.error("Figure %s did not write PNG: %s", fn_name, out)
            missing_figures.append(fn_name)
            return None
        return out

    _guarded_plot("press_index_bar", plot_press_index_bar, result, out_dir=figures_dir)
    _guarded_plot("coverage_scatter", plot_coverage_scatter, result, out_dir=figures_dir)
    _guarded_plot("national_trend", plot_national_trend, result, out_dir=figures_dir)

    # Choropleth: allowed to be skipped (geo asset may be absent). Only raise if
    # the function returned a path but the file is missing (internal failure).
    choropleth_available = False
    try:
        ch_out = plot_press_index_choropleth(
            result, out_dir=figures_dir, map_anchor_knrs=map_anchor_knrs
        )
        if ch_out is not None and Path(ch_out).exists():
            choropleth_available = True
        elif ch_out is not None and not Path(ch_out).exists():
            # Returned a path but didn't write it — treat as internal failure
            missing_figures.append("press_index_choropleth")
    except Exception as exc:
        logger.error("Choropleth raised: %s", exc)
        missing_figures.append("press_index_choropleth")

    if missing_figures:
        raise RuntimeError(
            f"report aborted: figures missing: {', '.join(missing_figures)}"
        )

    # ── Verification (A8) ───────────────────────────────────────────────────
    # When verification is None, rebuild from result (current behavior).
    # When provided (gate's report), pass it through to the template.
    if verification is None:
        verifier = Verifier(result)
        claims = build_standard_claims(result)
        verification = verifier.verify_all(claims)

    # ── Report rendering ─────────────────────────────────────────────────────
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
            report_md = render_template(result, quality_report, verification,
                                        choropleth_available=choropleth_available)
            cost_info = {"renderer": "template_fallback", "error": str(exc)}
    else:
        report_md = render_template(result, quality_report, verification,
                                    choropleth_available=choropleth_available)

    report_path = report_dir / "omsorgsradar_rapport.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("Report written to %s", report_path)

    return report_path, cost_info
