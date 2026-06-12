"""Choropleth rendering for Norwegian municipality data.

Uses only stdlib (json, pathlib) + matplotlib (PolyCollection) + numpy.
No geopandas, fiona, pyogrio, or shapely in runtime imports.

Coordinate system note:
  The committed asset ``assets/geo/kommuner_simplified.geojson`` uses
  WGS84 / EPSG:4326 (longitude/latitude in degrees). Aspect correction
  ``ax.set_aspect(1 / cos(radians(65)))`` is applied so that Norway
  renders with the correct east-west/north-south ratio at ~65°N latitude.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.collections as mcollections
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import numpy as np

logger = logging.getLogger(__name__)

# Committed GeoJSON asset (relative to this file's package root)
_ASSETS_DIR = Path(__file__).parent.parent.parent / "assets" / "geo"
DEFAULT_GEO_PATH = _ASSETS_DIR / "kommuner_simplified.geojson"

# Property key for 4-digit municipality code in the committed asset
KOMMUNENUMMER_KEY = "kommunenummer"

# Grey fill for municipalities with no value
MISSING_COLOR = "#cccccc"

# Central latitude for WGS84 aspect correction (Norway ~65°N)
_LAT_CENTRE_DEG = 65.0
_WGS84_ASPECT = 1.0 / math.cos(math.radians(_LAT_CENTRE_DEG))


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------


def _polygon_coords(geometry: dict[str, Any]) -> list[np.ndarray]:
    """Return a flat list of numpy (N, 2) arrays — one per ring across all parts.

    Handles both Polygon and MultiPolygon. The exterior ring of each polygon
    part is returned; interior rings (holes) are skipped for rendering purposes
    (they are visible as gaps in the filled polygons but are small in practice).
    """
    geom_type = geometry["type"]
    coords_list: list[np.ndarray] = []
    if geom_type == "Polygon":
        # Each element of geometry["coordinates"] is a ring: [lon, lat] pairs
        for ring in geometry["coordinates"]:
            arr = np.asarray(ring, dtype=float)  # (N, 2)
            coords_list.append(arr)
    elif geom_type == "MultiPolygon":
        for polygon in geometry["coordinates"]:
            for ring in polygon:
                arr = np.asarray(ring, dtype=float)
                coords_list.append(arr)
    else:
        logger.warning("Unsupported geometry type '%s' — skipped", geom_type)
    return coords_list


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_choropleth(
    geojson_path: Path,
    values: dict[str, float],
    out_png: Path,
    *,
    title: str,
    value_label: str,
    attribution: str,
    cmap_name: str = "Reds",
    figsize: tuple[float, float] = (10, 14),
    dpi: int = 150,
    vmin: float | None = None,
    vmax: float | None = None,
) -> dict[str, int]:
    """Render a choropleth map of Norwegian municipalities and save as PNG.

    Args:
        geojson_path: Path to a GeoJSON FeatureCollection whose features carry
            a ``kommunenummer`` property (4-digit string).
        values: Mapping from kommunenummer (4-digit zero-padded string) to a
            numeric value. Features whose code is absent are drawn in grey.
        out_png: Destination path for the output PNG.
        title: Figure title (bokmål).
        value_label: Colorbar label (bokmål, e.g. «Press-indeks»).
        attribution: Attribution text rendered in small print at bottom of figure.
        cmap_name: Matplotlib colormap name (default: "viridis").
        figsize: Figure size in inches (width, height).
        dpi: Output resolution (default 150).
        vmin: Lower clamp for colormap normalization (default: min of values).
        vmax: Upper clamp for colormap normalization (default: max of values).

    Returns:
        Dict with keys:
            ``plotted`` — number of features whose code was found in *values*
            ``missing`` — number of features drawn grey (code absent from *values*)
    """
    geojson_path = Path(geojson_path)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    with geojson_path.open(encoding="utf-8") as fh:
        geo = json.load(fh)

    features = geo.get("features", [])

    # Normalize value keys to ensure 4-digit zero-padding
    normed_values: dict[str, float] = {
        str(k).zfill(4): float(v) for k, v in values.items()
    }

    # Determine color normalization range
    if normed_values:
        all_vals = list(normed_values.values())
        v_lo = vmin if vmin is not None else float(np.nanmin(all_vals))
        v_hi = vmax if vmax is not None else float(np.nanmax(all_vals))
    else:
        v_lo, v_hi = 0.0, 1.0

    # Guard against degenerate range (all values identical)
    if v_lo == v_hi:
        v_hi = v_lo + 1.0

    norm = mcolors.Normalize(vmin=v_lo, vmax=v_hi)
    cmap = matplotlib.colormaps[cmap_name]

    # Build lists: polygon coordinate arrays + face colours
    plotted_polys: list[np.ndarray] = []
    plotted_colors: list[Any] = []
    missing_polys: list[np.ndarray] = []

    plotted_count = 0
    missing_count = 0

    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        if geom is None:
            continue
        knr = str(props.get(KOMMUNENUMMER_KEY, "")).zfill(4)

        rings = _polygon_coords(geom)

        if knr in normed_values:
            colour = cmap(norm(normed_values[knr]))
            for ring in rings:
                plotted_polys.append(ring)
                plotted_colors.append(colour)
            plotted_count += 1
        else:
            for ring in rings:
                missing_polys.append(ring)
            missing_count += 1

    # Render
    fig, ax = plt.subplots(figsize=figsize)

    # WGS84 coordinates → correct aspect for Norway at ~65°N
    ax.set_aspect(_WGS84_ASPECT)

    if missing_polys:
        coll_grey = mcollections.PolyCollection(
            missing_polys,
            facecolors=MISSING_COLOR,
            edgecolors="white",
            linewidths=0.3,
            zorder=1,
        )
        ax.add_collection(coll_grey)

    if plotted_polys:
        coll_data = mcollections.PolyCollection(
            plotted_polys,
            facecolors=plotted_colors,
            edgecolors="white",
            linewidths=0.3,
            zorder=2,
        )
        ax.add_collection(coll_data)

        # Colorbar
        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])  # required for ScalarMappable without a plot object
        cbar = fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.02)
        cbar.set_label(value_label, fontsize=10)

    # Autoscale axes to fit all polygons
    ax.autoscale_view()

    # Styling: no axis ticks/frame
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)

    # Attribution in small text at bottom
    fig.text(
        0.01, 0.005,
        attribution,
        ha="left", va="bottom",
        fontsize=7, color="#555555",
        transform=fig.transFigure,
    )

    fig.tight_layout()
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info("Choropleth saved: %s (plotted=%d, missing=%d)", out_png, plotted_count, missing_count)

    return {"plotted": plotted_count, "missing": missing_count}


# ---------------------------------------------------------------------------
# Labelled choropleth (A3: top-10 + anchor annotations at centroids)
# ---------------------------------------------------------------------------


def _compute_centroid(rings: list[np.ndarray]) -> tuple[float, float] | None:
    """Return mean (lon, lat) centroid across all polygon rings' points."""
    all_pts: list[np.ndarray] = []
    for ring in rings:
        if len(ring) > 0:
            all_pts.append(ring)
    if not all_pts:
        return None
    pts = np.vstack(all_pts)
    return float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1]))


def render_choropleth_with_labels(
    geojson_path: Path,
    values: dict[str, float],
    out_png: Path,
    *,
    title: str,
    value_label: str,
    attribution: str,
    cmap_name: str = "Reds",
    figsize: tuple[float, float] = (10, 14),
    dpi: int = 150,
    vmin: float | None = None,
    vmax: float | None = None,
    label_knrs: set[str] | None = None,
    knr_to_name: dict[str, str] | None = None,
) -> dict[str, int]:
    """Render a choropleth with optional polygon-centroid labels.

    Extends :func:`render_choropleth` with text annotations at polygon
    centroids for municipalities in *label_knrs* (top-10 + city anchors).
    Labels are small (fontsize 6), clipped to the axes, and only the first
    label is placed per knr to avoid clutter in MultiPolygons.

    Args:
        geojson_path: Path to GeoJSON FeatureCollection.
        values: ``{kommunenummer: value}`` mapping.
        out_png: Destination PNG path.
        title: Figure title.
        value_label: Colorbar label.
        attribution: Attribution text.
        cmap_name: Matplotlib colormap (default: «Reds»; dark = high press).
        figsize: Figure size in inches.
        dpi: Output resolution.
        vmin: Lower colormap clamp.
        vmax: Upper colormap clamp.
        label_knrs: Set of 4-digit kommunenummer strings to label.
        knr_to_name: Mapping from knr to display name.

    Returns:
        Dict with keys ``plotted`` and ``missing``.
    """
    geojson_path = Path(geojson_path)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    if label_knrs is None:
        label_knrs = set()
    if knr_to_name is None:
        knr_to_name = {}

    with geojson_path.open(encoding="utf-8") as fh:
        geo = json.load(fh)

    features = geo.get("features", [])

    normed_values: dict[str, float] = {
        str(k).zfill(4): float(v) for k, v in values.items()
    }
    normed_label_knrs: set[str] = {str(k).zfill(4) for k in label_knrs}
    normed_knr_to_name: dict[str, str] = {
        str(k).zfill(4): v for k, v in knr_to_name.items()
    }

    if normed_values:
        all_vals = list(normed_values.values())
        v_lo = vmin if vmin is not None else float(np.nanmin(all_vals))
        v_hi = vmax if vmax is not None else float(np.nanmax(all_vals))
    else:
        v_lo, v_hi = 0.0, 1.0

    if v_lo == v_hi:
        v_hi = v_lo + 1.0

    norm = mcolors.Normalize(vmin=v_lo, vmax=v_hi)
    cmap = matplotlib.colormaps[cmap_name]

    plotted_polys: list[np.ndarray] = []
    plotted_colors: list[Any] = []
    missing_polys: list[np.ndarray] = []

    plotted_count = 0
    missing_count = 0

    # Per-knr centroid (first polygon ring centroid per feature)
    label_centroids: dict[str, tuple[float, float]] = {}

    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        if geom is None:
            continue
        knr = str(props.get(KOMMUNENUMMER_KEY, "")).zfill(4)
        rings = _polygon_coords(geom)

        if knr in normed_values:
            colour = cmap(norm(normed_values[knr]))
            for ring in rings:
                plotted_polys.append(ring)
                plotted_colors.append(colour)
            plotted_count += 1
        else:
            for ring in rings:
                missing_polys.append(ring)
            missing_count += 1

        # Compute centroid for label if needed (first encounter only)
        if knr in normed_label_knrs and knr not in label_centroids:
            centroid = _compute_centroid(rings)
            if centroid is not None:
                label_centroids[knr] = centroid

    # Render
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_aspect(_WGS84_ASPECT)

    if missing_polys:
        coll_grey = mcollections.PolyCollection(
            missing_polys,
            facecolors=MISSING_COLOR,
            edgecolors="white",
            linewidths=0.3,
            zorder=1,
        )
        ax.add_collection(coll_grey)

    if plotted_polys:
        coll_data = mcollections.PolyCollection(
            plotted_polys,
            facecolors=plotted_colors,
            edgecolors="white",
            linewidths=0.3,
            zorder=2,
        )
        ax.add_collection(coll_data)

        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.02)
        cbar.set_label(value_label, fontsize=10)

    ax.autoscale_view()

    # Add labels at centroids (clip to axes to avoid overflow)
    if label_centroids:
        ax_xlim = ax.get_xlim()
        ax_ylim = ax.get_ylim()
        for knr, (cx, cy) in label_centroids.items():
            # Skip if centroid is far outside the visible area
            x_margin = (ax_xlim[1] - ax_xlim[0]) * 0.05
            y_margin = (ax_ylim[1] - ax_ylim[0]) * 0.05
            if not (ax_xlim[0] - x_margin <= cx <= ax_xlim[1] + x_margin
                    and ax_ylim[0] - y_margin <= cy <= ax_ylim[1] + y_margin):
                continue
            name = normed_knr_to_name.get(knr, knr)
            ax.text(
                cx, cy, name,
                fontsize=6,
                ha="center", va="center",
                color="black",
                fontweight="bold",
                clip_on=True,
                zorder=5,
                bbox=dict(
                    boxstyle="round,pad=0.1",
                    facecolor="white",
                    edgecolor="none",
                    alpha=0.6,
                ),
            )

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)

    fig.text(
        0.01, 0.005,
        attribution,
        ha="left", va="bottom",
        fontsize=7, color="#555555",
        transform=fig.transFigure,
    )

    fig.tight_layout()
    fig.savefig(out_png, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info(
        "Choropleth (labelled) saved: %s (plotted=%d, missing=%d, labels=%d)",
        out_png, plotted_count, missing_count, len(label_centroids),
    )

    return {"plotted": plotted_count, "missing": missing_count}
