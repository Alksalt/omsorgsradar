# API drift log — omsorgsradar

Documents cases where SSB or FHI API metadata differed from expectations,
requiring runtime discovery rather than hardcoded identifiers.

## SSB PxWebAPI v2

### KOSTRA table 12209 — region variable code

- **Expected:** `Region` (standard PxWebAPI v2 dimension code)
- **Actual:** `KOKkommuneregion0000` (table-specific code)
- **Discovery method:** `GET /api/v0/no/table/12209` metadata endpoint
- **Fix:** `fetch_kostra_pleie()` discovers the region variable by checking for `"region"` in the code (case-insensitive) rather than hardcoding `"Region"`.

### KOSTRA table 12209 — variable codes

KOSTRA 12209 uses internal SSB variable codes (e.g. `KOShjtj80aarover0001`) rather than human-readable codes. Variable mapping:

| Internal code | Meaning |
|---|---|
| `KOShjtj80aarover0001` | Andel innbyggere 80+ som bruker hjemmetjenester (%) |
| `KOSsykhjand80aar0000` | Andel 80+ med institusjonsopphold (%) |
| `KOSaarsvbrukerom0000` | Årsverk per bruker |
| `KOSbduFKG9innbyg0000` | Utgifter per innbygger (kr) |

These codes are fetched from the metadata endpoint and used as-is. The mapping is configured in `analyses/omsorgsradar/analysis.toml` under `[sources.var_map]` and passed at runtime via `RunConfig.sources`.

### Population projection table 13873

- **Status:** Returns HTTP 400 via the public API (2026-06-11)
- **Fallback:** Table 12880 (national-level projections, years 2024–2029)
- **Impact:** Municipality-level projections unavailable via public API. National growth rate used as uniform proxy for all municipalities. See LIMITATIONS.md.

### Age dimension in table 07459

- **Format:** 3-digit zero-padded codes (`"080"`, `"081"`, ..., `"104"`) with labels ("80 år", "81 år", ..., "104 år")
- **80+ filter:** codes ≥ 080 (integer comparison after stripping to numeric)

## FHI NOKKEL

- **Base URL:** `https://statistikk-data.fhi.no/api/open/v1/`
- **Status:** `/datakilder/nokkel/indikatorer` returns 404 (2026-06-11)
- **Impact:** FHI socioeconomic context (levekårsindeks, sosial ulikhet per kommune) not included in v0.1. Handled gracefully (empty DataFrame, warning logged).
- **Note:** FHI's public API was previously at `kommunehelsa.fhi.no` and `norgeshelsa.no` — both decommissioned 2025-11-10. The new NOKKEL branding endpoint may require updated path discovery.
