# Provenance — kommuner_simplified.geojson

## Source

**Repository:** https://github.com/robhop/fylker-og-kommuner  
**File:** `Kommuner-S.topojson` (Small/simplified quality level)  
**Commit/branch:** `main` (accessed 2026-06-12)  
**Upstream data:** Kartverket administrative boundary data, updated 2024  
**Upstream metadata page:** https://kartkatalog.geonorge.no/metadata/administrative-enheter-kommuner/041f1e6e-bdbc-4091-b48f-8a5990f3cc5b

## License

**CC BY 4.0** — Creative Commons Attribution 4.0 International  
Source repo states: *«Basert på Kartverkets data under CC BY 4.0»*  
Full license text: https://creativecommons.org/licenses/by/4.0/

## Download date

2026-06-12

## What was done

1. Downloaded `Kommuner-S.topojson` (991 KB) from the robhop/fylker-og-kommuner GitHub repository.
2. Converted from TopoJSON to GeoJSON using the Python `topojson` library (ephemeral dev dependency, `uv run --with topojson`) — not added to pyproject.toml.
3. Wrote compact GeoJSON (no extra whitespace) to `kommuner_simplified.geojson`.

The source file is already simplified (the "S" = small/simplified quality level, coastline-clipped). No additional coordinate rounding or Douglas-Peucker simplification was applied — the topojson library's `to_geojson()` output was used directly.

## Asset properties

- **Feature count:** 357
- **Coordinate system:** WGS84 / EPSG:4326 (longitude/latitude degrees)
- **Longitude range:** 4.64° to 31.15° E
- **Latitude range:** 57.97° to 71.19° N
- **File size:** 1.2 MB (well under the 5 MB cap)
- **Kommune code property key:** `kommunenummer` (4-digit zero-padded string, e.g. `"0301"` for Oslo)
- **Verified codes present:** 0301 (Oslo), 5001 (Trondheim), 5616 (Hasvik)
- **Geometry types:** Polygon and MultiPolygon

## Attribution line for figure captions

«Kartgrunnlag: Kartverket via robhop/fylker-og-kommuner (CC BY 4.0)»
