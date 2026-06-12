# Dataset registry — ranked open health-data sources

The `/magic-analyze` shell resolves free-text questions against this registry
(Tier 1 first). Adapter column = what `[[sources]]` needs; per-adapter fields in
`docs/adapters.md`. Hosts must be in the engine allowlist
(`core/adapters/__init__.py::ALLOWED_BASE_URL_HOSTS` + workflow.toml
`[security].extra_allowed_hosts`).

## Tier 1 — adapter exists, API verified live

| Source | Land | Innhold | Adapter | Base URL | Verifisert |
|---|---|---|---|---|---|
| SSB PxWebAPI v2 | NO | KOSTRA pleie/omsorg (12209), befolkning (07459), framskrivinger (12880) — kommune | `pxweb` | `https://data.ssb.no/api/v0/no/table` | 2026-06-11/12 |
| SCB PxWeb | SE | Befolkning per kommun/ålder (BefolkningNy) m.fl. | `pxweb` (+`cache_key`, `use_codes`) | `https://api.scb.se/OV0104/v1/doris/sv/ssd/...` | 2026-06-12 |
| THL Sotkanet | FI | ~3 700 indikatorer per kunta; kotihoito 75+ = **5513** (3216 er død), 75+-andel = 171, befolkning = 127, prognoser 745/757. CC BY 4.0 | `sotkanet` | `https://sotkanet.fi/rest/1.1` (krever User-Agent) | 2026-06-12 |
| Kolada (RKA) | SE | Kommunale KPI-er; hemtjänst 80+ = **N21704** (Socialstyrelsen/SCB-data republisert) | `kolada` | `https://api.kolada.se/v3` | 2026-06-12 |
| KUHR helserefusjon | NO | Takstbruk per kommune/år (fastlege m.fl.), 2015– | `kuhr` | `https://opne-data-api.helserefusjon.no/v1` | 2026-06-12 |
| Socialstyrelsen sdb | SE | Helse-emner (amning, diagnoser, läkemedel, skador per kommun, dödsorsaker). ⚠ INGEN äldreomsorg-topic — bruk Kolada | `socialstyrelsen` | `https://sdb.socialstyrelsen.se/api/v1/sv` | 2026-06-12 |
| FHI NOKKEL | NO | Folkehelseindikatorer per kommune. ⚠ Discovery-endepunkt 404 2026-06-11 (`docs/api_drift.md`) | legacy fetcher (id `fhi_nokkel`) | `https://statistikk-data.fhi.no/api/open/v1` | delvis |

## Tier 2 — adapter-ready, IKKE verifisert (research 2026-06-11, wiki
`tech/agentic-healthcare-analysis-workflow-2026`)

| Source | Land | Innhold | Nærmeste adapter | Notat |
|---|---|---|---|---|
| Danmarks Statistik StatBank | DK | Hjemmesygepleje per kommune m.m. | NY (`api.statbank.dk/v1` er egen JSON-API, ikke PxWeb) | /add-dataset-kandidat |
| Folkhälsomyndigheten | SE | Folkhälsodata (PxWeb) | trolig `pxweb` | verifiser dialekt først |
| NHS English Prescribing Dataset | EN | GP-praksis × legemiddel × måned, >2,2 mrd rader, CKAN `datastore_search_sql`, OGL v3 | NY (`ckan`) | størst åpne forskrivningsdata |
| CDC BRFSS | US | Reell mikrodata (helseatferd), XPT-filer | `csv` etter konvertering | anonymiserings-demo (G4) |
| CMS Medicare Part D | US | Forskrivning per lege/legemiddel | NY | data.cms.gov API |

## Regler

- Nye kilder: `/add-dataset` — én prøvespørring, så `[[sources]]`-blokk eller ny
  adapter + fixture + known-value-test (G1-mønsteret). Aldri endre eksisterende
  adapteres oppførsel.
- Nye verter: legg til i `ALLOWED_BASE_URL_HOSTS` (kodeendring + review) eller
  midlertidig i workflow.toml `[security].extra_allowed_hosts` (eier-beslutning).
- Realness-gates kjører uansett kilde; csv krever eksplisitt `[sources.provenance]`.
