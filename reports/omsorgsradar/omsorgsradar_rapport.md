# Kommunal Omsorgsradar — rapport

*Analysedato: 2026-06-11 · Kilde: SSB KOSTRA + FHI NOKKEL · Versjon: 0.1.0*

---

## Sammendrag

Analysen dekker **908 kommuner** og beregner en press-indeks som kombinerer forventet vekst i 80+-befolkningen mot 2035 med dagens dekning av hjemmetjenester.

På nasjonalt nivå vil 80+-befolkningen vokse med anslagsvis **36.3%** fra 285 000 (siste datapunkt) til 388 000 i 2035 dersom SSB-trenden holder seg.

**91 kommuner** har press-indeks ≥ 0,5 og trenger særskilt planleggingsoppmerksomhet.
Gjennomsnittlig dekning er **29 hjemmebaserte brukere per 1 000 innbygger 80+**.

---

## Metodikk og deskriptiv tolkning

Press-indeksen er et **deskriptivt planleggingsverktøy**, ikke et kausalt mål. Den beregnes som:

```
press_indeks_rå = (80+_befolkning_2035 / 80+_befolkning_nå) × (1 / (dekningsrate + ε))
press_indeks_norm = normalisert til [0, 1] på tvers av alle kommuner
```

Høy indeks = rask vekst i eldre befolkning OG lav dekning av hjemmetjenester i dag. Tolkes som planleggingsbehov, ikke som klinisk beslutningsstøtte.

---

## Rangering — topp 20 kommuner

| Rang | Kommune | Press-indeks | Dekningsrate | Vekst 80+ mot 2035 |
|------|---------|-------------|-------------|-------------------|
| 1 | Hasvik | 1.000 | 16 | 36.3% |
| 2 | Bjerkreim | 0.965 | 16 | 36.3% |
| 3 | Tydal | 0.965 | 16 | 36.3% |
| 4 | Sørreisa | 0.923 | 16 | 36.3% |
| 5 | Flakstad | 0.915 | 16 | 36.3% |
| 6 | Frogn | 0.908 | 17 | 36.3% |
| 7 | Lom | 0.900 | 17 | 36.3% |
| 8 | Tysvær | 0.870 | 17 | 36.3% |
| 9 | Lørenskog | 0.841 | 18 | 36.3% |
| 10 | Rælingen | 0.780 | 18 | 36.3% |
| 11 | Horten | 0.774 | 18 | 36.3% |
| 12 | Hvaler | 0.749 | 19 | 36.3% |
| 13 | Lunner | 0.743 | 19 | 36.3% |
| 14 | Bokn | 0.743 | 19 | 36.3% |
| 15 | Sandnes | 0.737 | 19 | 36.3% |
| 16 | Klepp | 0.737 | 19 | 36.3% |
| 17 | Skaun | 0.731 | 19 | 36.3% |
| 18 | Karmøy | 0.720 | 19 | 36.3% |
| 19 | Gran | 0.714 | 20 | 36.3% |
| 20 | Sarpsborg | 0.708 | 20 | 36.3% |

*Vekst 80+ bruker nasjonal framskrivingstakt for alle kommuner — kommunenivå-projeksjon er ikke tilgjengelig i datakilden (se forbehold).*

---

## Figurer

![Press-indeks topp 20](figures/press_index_bar.png)

![Dekning vs vekst](figures/coverage_scatter.png)

![Nasjonal trend](figures/national_trend.png)

---

## Datakvalitet

**kostra_pleie**: 39204 rader · 849 kommuner · kilde: SSB KOSTRA table 12209
**befolkning**: 237750 rader · 908 kommuner · kilde: SSB table 07459 — folkemengde etter alder
**framskrivinger**: 258 rader · N/A kommuner · kilde: SSB population projections
**fhi_nokkel**: 0 rader · 0 kommuner · kilde: FHI NOKKEL (folkehelsestatistikk)

---

## Verifisering av tall (verktøykvitteringer)

**Resultat: PASS** — 5/5 påstander verifisert.

- ✓ `top_kommune_rank1_press_index` → OK
- ✓ `top_kommune_name` → OK
- ✓ `national_growth_rate_2035` → OK
- ✓ `kommuner_above_threshold` → OK
- ✓ `coverage_rate_mean` → OK

---

## Begrensninger

Se [LIMITATIONS.md](https://github.com/Alksalt/omsorgsradar/blob/main/LIMITATIONS.md) for fullstendig liste. Viktigste forbehold: analysen er deskriptiv, ikke kausal; kommunesammenslåingstabell dekker 2020-bølgen; framskrivinger er basert på nasjonal veksttakt, ikke kommunenivå-projeksjon.

## ML-analyse — XGBoost walk-forward CV

**Mål:** coverage_rate  
**Ramme:** planleggingsstøtte — ikke klinisk beslutningsstøtte

**Gjennomsnittlig MAE:** XGBoost 2.08 vs naiv baseline 2.28

| Fold | Testår | XGB MAE | Naiv MAE |
|------|--------|---------|----------|
| 1 | 2023 | 2.17 | 2.28 |
| 2 | 2024 | 2.02 | 2.25 |
| 3 | 2025 | 2.05 | 2.30 |

**SHAP — viktigste features:**

- `coverage_rate_lag1`: mean |SHAP| = 5.0287
- `year`: mean |SHAP| = 0.7645
- `coverage_rate_lag2`: mean |SHAP| = 0.4152
- `log_pop_80plus`: mean |SHAP| = 0.4143
- `inst_per_1000_80plus`: mean |SHAP| = 0.3043

**Merknader:**
- TabPFN-2.5: ikke kjørt (krever lisensregistrering hos PriorLabs) — XGBoost-resultatene presenteres alene.


---

*Rapporten er generert av omsorgsradar-pipeline v0.1.0.*
*Utdannet lege (master i medisin) — Oleksandr Altukhov.*
