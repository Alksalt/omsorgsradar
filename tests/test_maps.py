"""Tests for src/omsorgsradar/maps.py — choropleth rendering.

All tests are fully offline:
- B1: synthetic GeoJSON fixture written to tmp_path
- B3: committed asset validation
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# ---------------------------------------------------------------------------
# Synthetic GeoJSON fixture (3 features: 2 Polygon, 1 MultiPolygon)
# Property key matches the real asset: "kommunenummer"
# ---------------------------------------------------------------------------

SYNTHETIC_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"kommunenummer": "0301", "kommunenavn": "Oslo"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [10.6, 59.8],
                        [10.9, 59.8],
                        [10.9, 60.0],
                        [10.6, 60.0],
                        [10.6, 59.8],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {"kommunenummer": "5001", "kommunenavn": "Trondheim"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [10.2, 63.3],
                        [10.6, 63.3],
                        [10.6, 63.6],
                        [10.2, 63.6],
                        [10.2, 63.3],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {"kommunenummer": "5616", "kommunenavn": "Hasvik"},
            # MultiPolygon: two small boxes
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [22.0, 70.4],
                            [22.2, 70.4],
                            [22.2, 70.5],
                            [22.0, 70.5],
                            [22.0, 70.4],
                        ]
                    ],
                    [
                        [
                            [23.0, 70.5],
                            [23.2, 70.5],
                            [23.2, 70.6],
                            [23.0, 70.6],
                            [23.0, 70.5],
                        ]
                    ],
                ],
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# B1 — render_choropleth() contract
# ---------------------------------------------------------------------------


class TestRenderChoropleth:
    @pytest.fixture()
    def geojson_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "test_kommuner.geojson"
        p.write_text(json.dumps(SYNTHETIC_GEOJSON), encoding="utf-8")
        return p

    def test_writes_png(self, geojson_path: Path, tmp_path: Path) -> None:
        from omsorgsradar.maps import render_choropleth

        out_png = tmp_path / "choropleth.png"
        values = {"0301": 0.9, "5001": 0.3}  # 5616 is missing → should be grey
        result = render_choropleth(
            geojson_path,
            values,
            out_png,
            title="Test koropleth",
            value_label="Press-indeks",
            attribution="Kartgrunnlag: Kartverket (CC BY 4.0)",
        )

        assert out_png.exists(), "PNG file was not created"
        magic = out_png.read_bytes()[:8]
        assert magic == PNG_MAGIC, f"File is not a valid PNG (magic={magic!r})"

    def test_returns_correct_counts(self, geojson_path: Path, tmp_path: Path) -> None:
        from omsorgsradar.maps import render_choropleth

        out_png = tmp_path / "choropleth2.png"
        values = {"0301": 0.9, "5001": 0.3}  # 5616 missing
        result = render_choropleth(
            geojson_path,
            values,
            out_png,
            title="Test",
            value_label="Press-indeks",
            attribution="Attr",
        )

        assert isinstance(result, dict), "render_choropleth must return a dict"
        assert result["plotted"] == 2, f"Expected 2 plotted, got {result['plotted']}"
        assert result["missing"] == 1, f"Expected 1 missing, got {result['missing']}"

    def test_multipolygon_handled(self, geojson_path: Path, tmp_path: Path) -> None:
        """All 3 features rendered (2 plotted with values, 1 grey) — no crash on MultiPolygon."""
        from omsorgsradar.maps import render_choropleth

        out_png = tmp_path / "choropleth3.png"
        # Provide values for all 3 — no missing
        values = {"0301": 1.0, "5001": 0.5, "5616": 0.1}
        result = render_choropleth(
            geojson_path,
            values,
            out_png,
            title="Test",
            value_label="Press-indeks",
            attribution="Attr",
        )
        assert result["plotted"] == 3
        assert result["missing"] == 0

    def test_empty_values_all_grey(self, geojson_path: Path, tmp_path: Path) -> None:
        from omsorgsradar.maps import render_choropleth

        out_png = tmp_path / "choropleth4.png"
        result = render_choropleth(
            geojson_path,
            {},  # no values → all grey
            out_png,
            title="Test",
            value_label="Press-indeks",
            attribution="Attr",
        )
        assert out_png.exists()
        assert result["plotted"] == 0
        assert result["missing"] == 3


# ---------------------------------------------------------------------------
# B3 — committed asset validation
# ---------------------------------------------------------------------------

ASSET_PATH = (
    Path(__file__).parent.parent / "assets" / "geo" / "kommuner_simplified.geojson"
)

REQUIRED_CODES = {"0301", "5001", "5616"}


class TestCommittedAsset:
    def test_asset_exists(self) -> None:
        assert ASSET_PATH.exists(), f"Asset not found: {ASSET_PATH}"

    def test_parses_as_geojson(self) -> None:
        data = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
        assert data["type"] == "FeatureCollection"
        assert "features" in data

    def test_feature_count_at_least_350(self) -> None:
        data = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
        count = len(data["features"])
        assert count >= 350, f"Expected ≥350 features, got {count}"

    def test_required_codes_present(self) -> None:
        data = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
        codes = {
            f["properties"].get("kommunenummer")
            for f in data["features"]
            if f.get("properties")
        }
        missing = REQUIRED_CODES - codes
        assert not missing, f"Missing required kommunenummer codes: {missing}"

    def test_file_under_5mb(self) -> None:
        size = ASSET_PATH.stat().st_size
        assert size < 5 * 1024 * 1024, f"Asset too large: {size/1024/1024:.1f} MB"

    def test_kommunenummer_property_key(self) -> None:
        """Confirms the property key is 'kommunenummer' (as documented in PROVENANCE.md)."""
        data = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
        first = data["features"][0]["properties"]
        assert "kommunenummer" in first, f"Property 'kommunenummer' not found, got: {list(first.keys())}"
