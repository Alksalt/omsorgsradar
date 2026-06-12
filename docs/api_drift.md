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

- **Status (2026-06-11):** Returns HTTP 400 via the public PxWebAPI v0 (`/api/v0/no/table/13873`).
- **Re-checked (2026-06-12):** Still HTTP 400 from v0; HTTP 404 from v2 (`/api/v2/no/table/13873`). Table 99999 (nonexistent) also returns 400 from v0, confirming 13873 is not accessible to anonymous callers via the public API. The SSB Statbank web UI at `www.ssb.no/statbank/table/13873/` returns 200 HTML (SPA shell), but that is frontend scaffolding only — no data API behind it.
- **Alternative search (2026-06-12):** Scanned tables 13860–13900 for municipality-level projection tables with years ≥ 2035. Table 13883 (`Framskrevet folkemengde 1. januar, med formalisert usikkerhet`) exists and is accessible but contains national-level projections only (no Region variable). No municipality-level projection table accessible via the public API was found.
- **Resolution:** Per-kommune 80+ growth rates now derived from **historical CAGR** using the existing SSB table 07459 population data (years available per code, typically 2020–2026 for post-merger codes; longer for stable codes). This replaces the uniform national proxy with genuine per-kommune variation. See `analyze.py: _compute_kommune_growth_rates()`.
- **Fallback chain:** kommune historical CAGR → national rate from 12880 → 3.5% default.

### Age dimension in table 07459

- **Format:** 3-digit zero-padded codes (`"080"`, `"081"`, ..., `"104"`) with labels ("80 år", "81 år", ..., "104 år")
- **80+ filter:** codes ≥ 080 (integer comparison after stripping to numeric)

## FHI NOKKEL

- **Base URL:** `https://statistikk-data.fhi.no/api/open/v1/`
- **Status (2026-06-11):** `/datakilder/nokkel/indikatorer` returns 404.
- **Re-checked (2026-06-12):** All paths under `/api/open/v1` return 404. The base URL `/api` returns 401 (authentication required). Paths `/api/public`, `/api/v1`, `/api/v2` all return 401. `statistikk.fhi.no` resolves but serves an HTML SPA (no REST API). `norgeshelsa.no` redirects to a Helsedirektoratet information page explaining that the service has moved.
- **Conclusion:** FHI's open statistics API at `statistikk-data.fhi.no/api/open/v1` no longer exists. No replacement public REST API was found. `statistikk.fhi.no` appears to be a frontend-only portal without a machine-readable API.
- **Impact:** FHI socioeconomic context (levekårsindeks, sosial ulikhet per kommune) not included. Handled gracefully (empty DataFrame, warning logged).
