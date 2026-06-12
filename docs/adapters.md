# Dataset adapters — `[[sources]]` reference

Adapters live in `src/omsorgsradar/core/adapters/`; dispatch is by `adapter` key
(legacy v1 ids `kostra_pleie`/`befolkning`/`framskrivinger`/`fhi_nokkel` keep bespoke
fetchers in `ingest.py`). Required fields are validated at pipeline startup via
`validate_source`. All HTTP adapters cache raw JSON to `data/cache/` (never read it
into model context — hook-enforced).

Nordic adapters emit the tidy contract: `country, geo_code, geo_id, geo_name, aar,
indicator, value` with `geo_id` = `NO-1505` / `SE-0180` / `FI-091` (`core/geo.py`).
Some adapters add extra columns beyond the contract (noted below).

---

## pxweb (SSB; FOHM/DST share the shape)

Required source fields: `base_url`, `table`. Optional: `query` (JSON-stat2 POST body),
`cache_key` (overrides the default table-id key), `use_codes` (bool, default false —
emit dimension codes instead of labels), `label_columns` (bool, default false — when
`use_codes` is true, also add `<dim>_label` columns alongside code columns).

The adapter POSTs a JSON-stat2 query to `{base_url}/{table}` and parses the
response into a DataFrame. Used for legacy v1 SSB sources (KOSTRA, population,
projections). Does not emit the Nordic tidy contract — column names match the
SSB dimension names from the raw response.

**Note on `cache_key`:** tables with `/` in the path (SCB-style) and all
explicit-query sources MUST set `cache_key` — slashes are rejected by the
cache-key sanitizer.

---

## sotkanet — THL, Finland (CC BY 4.0)

Required: `indicators` (list of int indicator ids), `years` (list of int or str years).
Optional: `genders` (str, default `"total"`), `base_url`.

API: `https://sotkanet.fi/rest/1.1`
- `/json?indicator=<id>&years=<y>…&genders=total` — indicator data
- `/regions` — municipality catalogue (KUNTA rows only; MAAKUNTA etc. are excluded)

The `region` field in data rows is an internal integer id; the adapter joins against
`/regions` to resolve 3-digit kunta codes and Finnish names. `aar` is an Int64 year.

Cache keys: `sotkanet_regions` (region catalogue), `sotkanet_{ind}_{y0}_{y1}_{gender}`
per indicator.

Extra column beyond the tidy contract: `gender`.

**Note:** The API returns HTTP 403 without a `User-Agent` header. The adapter always
sends `User-Agent: omsorgsradar/1.0 (research; github.com/Alksalt)`.

---

## socialstyrelsen — Sweden (statistikdatabas)

Required: `amne` (topic slug, e.g. `skadorochskadehandelserisverigeskommunerochlan`),
`matt` (int measure id).
Optional: `years` (list of strings, e.g. `["1995-1997"]`), `per_sida` (page size,
default 1000), `max_pages` (hard page cap, default 2000).

API: `https://sdb.socialstyrelsen.se/api/v1/sv`

**Important deviations from the API's own documentation (verified live 2026-06-12):**

- **No server-side filtering.** Path segments for region or year filtering (e.g.
  `/region/…` or `/ar/…`) return 404. Query parameters for filtering are also
  silently ignored. The adapter fetches the complete paginated dataset and filters
  client-side.
- **`years` is a post-fetch filter**, not a query parameter. It restricts which rows
  are kept in the output after the full dataset is downloaded. It does NOT reduce
  network traffic.
- **`regionId` is a string**, not an int. The adapter filters to 4-digit numeric
  strings for kommuner (2-digit = lan, other = non-standard regions excluded).
- **`aar` is a raw period string** (e.g. `"1995-1997"` or `"2022"`) from the `ar`
  field. It is NOT cast to a numeric year. The generic profiler cannot derive a
  numeric `year_range` for SE — downstream SE consumption in G2 uses the csv
  adapter, which carries integer `aar`.
- **`varde` uses Swedish decimal commas** (`"39,3"` → `39.3`). Suppressed values
  (`"X"`, `".."`) → `NaN`. The raw string is kept in `value_raw`; the parsed float
  is in `value`.
- **Per-topic dimension columns**: output includes `typId`, `konId`, `alderId`
  (fields that appear on the skador topic). There is no generic `variabelId` column.

Cache key: `sst_{amne}_m{matt}` (NO years suffix — year filter is post-fetch).
Regions cache key: `sst_{amne}_regions`.

`nasta_sida` pagination links come back as `http://` and are rewritten to `https://`
before following.

**⚠ No äldreomsorg topic.** The Socialstyrelsen statistikdatabas has no elder-care
topic (verified live 2026-06-12). Swedish elder-care data for G2 arrives via
Socialstyrelsen open-data CSV files using the csv adapter.

---

## kuhr — Helsedirektoratet/NAV helserefusjon, Norway

Required: `fagomraade` (str, e.g. `"LE"` for fastlege), `fomar` (int, first year
inclusive), `tomar` (int, last year inclusive).
Optional: `takstkoder` (list[str]), `kommuner` (list[str] 4-digit kommune codes),
`praksistyper` (list[str]), `value_field` (str, default `"antall_regninger"`),
`base_url`.

API: `https://opne-data-api.helserefusjon.no/v1/takstbruk/agtakst/kommune/ar`
Docs: [github.com/navikt/Helserefusjon-apne-data](https://github.com/navikt/Helserefusjon-apne-data)

Geography = practitioner's municipality. No auth required.

**No `geo_name` column** — the KUHR API exposes only practitioner kommune codes, not
names. Join downstream on `geo_id` if a name is needed.

Pre-2020 kommune numbers are merger-normalized via `kommune_mergers.normalize_knr_series`
so that historic codes land on their post-merger equivalents.

Cache key: `kuhr_{fagomraade}_{fomar}_{tomar}[_t<takst>][_k<kommuner>][_p<praksistyper>]`
(e.g. `kuhr_LE_2023_2023_t2ad_k1505`).

`value_field` must be one of the known measure columns: `sum_antall_takst`,
`antall_regninger`, `sum_refusjon`, `sum_egenandel_betalt_av_pasient`,
`sum_egenandel_dekket_av_folketrygden`. An unknown value raises `ValueError` at
ingest time.

---

## csv — local files

Required: `path` (str, relative to the analysis dir), `provenance` (dict with
`institution` and `url` — validated at startup and re-checked by the realness gate).
Optional: `sep` (default `","`), `encoding` (default `"utf-8"`), `decimal`
(default `"."`), `dtype` (dict mapping column names to dtypes), `rename` (dict
mapping original → tidy column names).

The realness provenance gate has no known-host fallback for local files, so
`[sources.provenance]` with a named institution and URL is **mandatory** (enforced by
`validate_source` at startup).

`path` must resolve inside the analysis dir — absolute paths and `../` escapes are
rejected (G3 gate).

Example:

```toml
[[sources]]
adapter = "csv"
id = "se_csv"
path = "se_data.csv"
[sources.rename]
kommun = "geo_code"
ar = "aar"
varde = "value"
[sources.provenance]
institution = "Socialstyrelsen (Sverige)"
url = "https://www.socialstyrelsen.se/statistik-och-data/oppna-data/"
```

---

## kolada — RKA, Sweden (municipal KPIs)

Required: `kpi` (e.g. "N21704"), `years` (list). Optional: `gender` ("T"), `base_url`.
API: `api.kolada.se/v3` — `/data/kpi/{kpi}/year/{year}` + `/municipality` (type K only;
riket "0000" and regions excluded). Data origin: Socialstyrelsen/SCB official statistics
republished per kommun by RKA. Used for SE elder-care because the sdb API has no
äldreomsorg topic.

---

## Realness gates (profile stage, mandatory)

Five checks run per dataset in the `profile` stage:

1. **provenance** — resolvable URL/DOI: explicit `[sources.provenance]` wins; else a
   known API host is matched from `KNOWN_HOSTS`; else the adapter's default endpoint.
2. **institution** — named institution in the resolved provenance.
3. **duplicates** — exact-duplicate rate >1% → FAIL.
4. **missingness** — value column ≥95% missing → FAIL; 0 missing in ≥5000 rows → WARN
   (fabrication signature).
5. **distribution** — zero variance across ≥100 rows → FAIL.

Verdict: FAIL > WARN > PASS (all-SKIP data never gates). Written to
`data/quality_profile.json`. A FAIL verdict aborts the pipeline with
`PipelineGateError` **after** the verdict is written (so the file is always readable
post-failure). Thresholds are in `src/omsorgsradar/realness.py`.
