# Kommunal Omsorgsradar — concept (scaffolded 2026-06-11)

Chosen as concept A of three researched options (B/C below). Research base + all source URLs:
wiki `growth/agentic-helsedata-portfolio-2026` (created 2026-06-11).

## The question it answers

Hvilke kommuner får den hardeste skvisen mellom **aldrende befolkning** og **dagens omsorgskapasitet**
fram mot 2035 — og hvor stor er den? Output: en rangert «press-indeks» per kommune + bokmål rapport med
figurer og kart. Universally recognized by kommunehelsesjefer, Helsedir analysts, velferdsteknologi teams.

## Datasets (all open, no application barrier)

| Source | What | Access |
|---|---|---|
| SSB PxWebAPI v2, tabell 12209 + `pleie`-serien | omsorgskapasitet per kommune (institusjonsplasser, hjemmetjenestetimer, brukere 67+/80+), 2007– | GET, CC BY 4.0, JSON-stat2/CSV |
| SSB befolkningsframskrivinger + befolkning | aldersfordeling nå + framskrevet 2025–2035 per kommune | PxWebAPI v2 |
| FHI OpenAPI, kilde `NOKKEL` (folkehelsestatistikk) | sosioøkonomisk/levekår-kontekst per kommune | `statistikk-data.fhi.no/api/open/v1/`, no auth, JSON-stat2/Parquet |

⚠️ Kommunehelsa/Norgeshelsa ble nedlagt 2025-11-10 — bruk alltid `NOKKEL`-navnet (gamle navn daterer
prosjektet). ⚠️ Kommunesammenslåinger (2020-bølgen) krever lookup-tabell i ingest — dette er den klassiske
norske datafellen og en SYNLIG kvalitetsdetalj i README.

## Agent pipeline (the portfolio point)

1. **Ingest-agent** — queries SSB PxWebAPI v2 + FHI NOKKEL, normalizes kommune-IDs via merger lookup,
   persists to DuckDB. Scripted end-to-end: clone → run → same conclusion.
2. **Profile-agent** — data quality audit as a first-class step: missing rates, outliers, definition
   changes across years; structured JSON quality report, published in README.
3. **Analyse-agent** — computes elderly-share projections per kommune, current coverage rates
   (brukere per 1000 80+), pressure index = projected demand growth vs current capacity; ALL numeric
   findings written to structured intermediate JSON (not held in LLM context).
4. **Verifiserings-agent** — the 2026 differentiator ("tool receipts"): recomputes every statistic
   claimed in the narrative from the dataframe and flags discrepancies. The LLM narrates; it never
   calculates. `tests/` includes a test where the verifier catches a deliberately planted hallucinated
   statistic.
5. **Rapport-agent** — bokmål markdown report + matplotlib figures + kommune-kart (Kartverket grenser),
   explicit «deskriptivt, ikke kausalt» caveat block.

Built on Claude Agent SDK + MCP tools — honest framing: «bygget med samme agent-infrastruktur som
hikari-agent», ties the portfolio together.

## Optional ML layer (honest, non-ML-engineer)

- XGBoost regression: predict brukere-per-1000-80+ in year Y+1; **walk-forward CV** (3 windows,
  2007–2021 train → 2022–2024 test) — never shuffle-split on time series.
- SHAP feature importance (bridges the black-box skepticism of Norwegian health-sector readers).
- Calibration/derivation honesty: naive baseline (last-year value) reported even if the model barely wins.
- TabPFN-2.5 as a no-training in-context baseline (signals 2025 SOTA awareness without ML posing).
- Framing: **«planning support»**, never clinical decision support (MDR/CE territory).
- No deep learning on a 356-row × ~15-year tabular dataset — instant credibility loss with reviewers.

## Repo packaging (signals production-mindedness)

README with Mermaid architecture diagram + bokmål summary section · `LIMITATIONS.md` (data caveats,
non-causality, aggregate-only) · `COSTS.md` (LLM cost per full run, e.g. «$0.X/run») · `tests/` incl. the
verifier-catches-hallucination test · data quality profile published · reports in bokmål (differentiator
vs international portfolios).

## Scope estimate

4–6 days total: ingest+clean 1–2d · agent pipeline 2d · ML 1d · verification+README 1d. Fastest of the
three concepts (PxWebAPI v2 is the most accessible source); B/C can reuse the same agent framework later.

## Rejected-for-now alternatives

- **B. Smittestopp-Analyse** — MSIS × LMR (antibiotika J01) × SYSVAK trend briefs; maps to Nasjonal
  handlingsplan mot antibiotikaresistens. ~4–5d. Strong second project on the same framework.
- **C. Helsekvalitets-Agent** — Helsedir kvalitetsindikatorer (Excel scraping, no API) + NOKKEL/KOSTRA
  context; RAG-status, anomaly flags, below-target prediction. Most impressive, most work (~5–7d).
