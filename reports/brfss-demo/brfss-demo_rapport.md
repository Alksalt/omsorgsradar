# BRFSS-demo: demografi-stratifisert diabetes-prevalens med målt restrisiko

**Spørsmål:** Hvordan kan vi publisere demografi-stratifisert diabetes-prevalens fra mikrodata med målt gjenidentifiseringsrisiko?

## Metode

Analysen anvender **anonymisering med målt restrisiko** i henhold til EU Art-29
Working Party Opinion 05/2014 (WP216) og EDPB 01/2025 / Datatilsynets veiledning.

Trinnene er:

1. **PII-rensing** — fødselsnummer (fnr/D-nummer), telefonnummer og kontonummer
   oppdages via regex + mod-11-sjekksum og erstattes med `<ENTITY_TYPE>` i fritekstfelter.
2. **Generalisering** — kontinuerlig alder binnes til aldersintervaller
   (18–29, 30–44, 45–59, 60–74, 75+).
3. **k-anonymitet (k = 10)** — ekvivalensklasser med færre enn 10 rader
   undertrykkes. 111 rader ble undertrykt
   (undertrykkelses­rate: 18.5%).
   489 rader i 35 ekvivalensklasser ble frigitt.
4. **WP216-risikovurdering** — tre kriterier måles uavhengig.

> **Merk:** Pseudonymisering ≠ anonymisering. Residual re-identifikasjonsrisiko
> er *målt, ikke eliminert*. Framing: «anonymisering med målt restrisiko»
> (Datatilsynet; EDPB 01/2025; WP216).

## WP216-vurdering

**Samlet WP216-dom: PASS**

| Kriterium | Resultat | Nøkkeltall |
|-----------|----------|------------|
| Singling-out | **PASS** | min_class_size = 10, prosecutor_risk = 0.1 |
| Linkability | **PASS** | unique_qi_share_pre_suppression = 0.0, threshold = 0.5 |
| Inference | **PASS** | min_l_diversity = 2, max_attacker_adv = 0.386031, threshold = 0.5 |

Alle tre verdier er hentet fra `data/identifiability.json`, produsert av anonymize-steget.

## Diabetes-prevalens per stratum

Totalt frigitt: **489 observasjoner**, samlet prevalens: **46.0%**.

Tabellen viser kun klasser med n ≥ 10 (ytterligere praktisk personvern ut over k-garantien):

| Stat (FIPS) | Aldersband | Kjønn (1=M, 2=F) | n | Prevalens |
|-------------|------------|-------------------|---|-----------|
| 06 | 18-29 | 2 | 12 | 50.0% |
| 06 | 30-44 | 2 | 15 | 13.3% |
| 06 | 45-59 | 1 | 12 | 25.0% |
| 06 | 45-59 | 2 | 19 | 47.4% |
| 06 | 60-74 | 1 | 20 | 40.0% |
| 06 | 60-74 | 2 | 12 | 50.0% |
| 06 | 75+ | 1 | 12 | 58.3% |
| 06 | 75+ | 2 | 13 | 76.9% |
| 12 | 18-29 | 1 | 12 | 41.7% |
| 12 | 45-59 | 1 | 11 | 45.5% |
| 12 | 45-59 | 2 | 12 | 33.3% |
| 12 | 60-74 | 1 | 12 | 50.0% |
| 12 | 60-74 | 2 | 13 | 30.8% |
| 12 | 75+ | 1 | 20 | 45.0% |
| 12 | 75+ | 2 | 16 | 50.0% |
| 17 | 18-29 | 1 | 11 | 54.5% |
| 17 | 30-44 | 1 | 13 | 69.2% |
| 17 | 30-44 | 2 | 18 | 38.9% |
| 17 | 45-59 | 2 | 16 | 50.0% |
| 17 | 60-74 | 1 | 14 | 28.6% |
| 17 | 75+ | 1 | 13 | 46.2% |
| 17 | 75+ | 2 | 12 | 33.3% |
| 36 | 18-29 | 1 | 13 | 30.8% |
| 36 | 45-59 | 1 | 12 | 50.0% |
| 36 | 45-59 | 2 | 18 | 38.9% |
| 36 | 60-74 | 1 | 13 | 84.6% |
| 36 | 60-74 | 2 | 18 | 50.0% |
| 36 | 75+ | 1 | 22 | 36.4% |
| 36 | 75+ | 2 | 13 | 46.2% |
| 48 | 18-29 | 1 | 11 | 54.5% |
| 48 | 18-29 | 2 | 10 | 50.0% |
| 48 | 30-44 | 1 | 10 | 50.0% |
| 48 | 60-74 | 1 | 10 | 50.0% |
| 48 | 75+ | 1 | 19 | 42.1% |
| 48 | 75+ | 2 | 12 | 75.0% |

Alle tall er beregnet av kode og kontrollregnet av en uavhengig verifiseringsmodul
(73/73 kontroller OK) før denne
rapporten ble generert.

## Datakilde

**CDC BRFSS** (US Behavioral Risk Factor Surveillance System):
[cdc.gov/brfss](https://www.cdc.gov/brfss/annual_data/annual_data.htm).
Denne analysen benytter en **syntetisk fixture** med BRFSS-form (600 rader,
seeded med numpy RNG seed=42) — ingen ekte persondata.
Real nedlasting dokumenteres i `analyses/brfss-demo/microdata/make_fixture.py`.

## Forbehold

- Syntetisk fixture: fordelingene gjenspeiler ikke den virkelige BRFSS-populasjonen.
- Aldersintervaller og k-verdi er tunet for demonstrasjonsformål.
- Undertrykkelses­rate på 18.5% betyr at 18.5% av radene
  ikke inngår i den frigitte tabellen.
- Pseudonymisering er ikke anonymisering: selv med WP216-godkjente verdier gjenstår
  en målbar restrisiko (se tabellen over).

---

*Rapporten er generert av omsorgsradar-pipelinen; alle tall kommer fra
`brfss_findings.json` og `identifiability.json`, verifisert mot `brfss_anonymized.csv`.*
