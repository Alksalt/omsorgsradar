# LIMITATIONS.md — Kommunal Omsorgsradar

## Deskriptivt, ikke kausalt

Press-indeksen er et **deskriptivt planleggingsverktøy**. Den identifiserer kommuner med en kombinasjon av rask demografisk vekst og lav tjenestedekning i dag — men den forklarer **ikke** hvorfor dekningen er lav, og den predikerer ikke faktiske framtidige behov med nøyaktighet.

En lav dekning kan reflektere:
- Reell underdekning av omsorgstjenester
- Ulik alderssammensetning innen 80+-kohorten
- Sterk uformell omsorg (familie/frivillige)
- Kjøp av private tjenester utenom KOSTRA-rapportering
- Datamangler i KOSTRA

Indeksen bør brukes som **startpunkt for videre analyse**, ikke som beslutningsgrunnlag alene.

## Datakvalitetsbegrensninger

### KOSTRA-data
- KOSTRA 12209 rapporterer kommunale andeler (% av 80+ som bruker tjenester) — ikke absolutte brukertall. Analysen bruker prosent-andel som proxy for dekningsrate.
- Noen kommuner har manglende KOSTRA-data for enkeltår. Kommuner uten rapporterte data er ekskludert fra rankingen (press_index = NaN).
- Rapporteringsdefinisjoner kan ha endret seg over tid (særlig i 2020-bølgen av kommunesammenslåinger).

### Kommunesammenslåinger
- Merger-tabellen dekker **2020-bølgen** (de ~50 viktigste absorpsjonene). 
- 2024-bølgen (noen nye sammenslåinger) er **ikke** dekket ennå.
- Pre-2020 historiske koder fra KOSTRA-serien håndteres korrekt; eldre data kan ha gjenværende mismatches for kommuner som ble slått sammen i 2017–2019.

### Befolkningsframskrivinger
- Analysen bruker SSB-tabell 12880 (nasjonale framskrivinger) i mangel av offentlig tilgjengelige kommunevise projections via PxWebAPI v2.
- SSB kommune-nivå projections (tabell 13873) returnerte 400-feil fra den offentlige API-en under innhentingen — dokumentert i `docs/api_drift.md`.
- Den valgte veksttakten (3,5% p.a.) er basert på nasjonal SSB-trend for 80+-kohorten 2010–2024. Kommunevis vekst vil avvike — bykommuner kan ha lavere vekst, distriktskommuner høyere.
- Fremskrivinger er usikre utover 5 år. 2035-tallene bør leses som planleggingshorisonter, ikke presise prediksjoner.

### FHI NOKKEL
- FHI NOKKEL-endepunktet (`/api/open/v1/datakilder/nokkel/indikatorer`) returnerte 404 under innhenting (2026-06-11). Socioøkonomisk kontekst (levekårsindeks, sosial ulikhet) er **ikke** inkludert i denne versjonen.
- Planlagt: integrering av FHI NOKKEL-data når API-endepunktet er tilgjengelig igjen.

## ML-begrensninger

- Prediksjonsmodellen (XGBoost) predikerer kommunal hjemmetjenestedekning i år Y+1 basert på historiske KOSTRA-andeler. Dette er **planleggingsstøtte**, ikke klinisk beslutningsstøtte.
- Datasett: ~850 kommuner × 9 år = ~3600 rader. For lite for dype neurale nettverk (ingen dyp læring er brukt — med rette).
- Walk-forward CV med 3 vinduer tester generaliserbarhet over tid, men 3 folds er begrenset statistisk evidens.
- TabPFN-2.5 kan nå kjøres over de samme 3 walk-forward-foldene som XGBoost. Status vises i rapporten — se COSTS.md for token-oppsett.
- MAE på ~2 prosentpoeng er moderat. Kommunal dekning er sterkt autoregressiv: lag-1 (forrige år) er den dominerende prediktoren, og modellens tillegg over naiv persistens (~0.2 pp) er beskjedent. Modellens verdi er avviksflagging — kommuner som avviker fra sin egen historiske trend — ikke punktprediksjon.

## Aggregert nivå — ingen individdata

All analyse er på **kommunalt aggregatnivå** over offentlige aggregatstatistikker. Ingen individdata, ingen pasientdata. Ingen REK-godkjenning er nødvendig.

## Anonymisering med målt restrisiko (anonymize-steget)

`anonymize`-steget (demo: `analyses/brfss-demo/`) behandler radnivå-mikrodata og publiserer
en k-anonymisert aggregat sammen med en **målt** restrisiko-kvittering. Viktige forbehold:

- **Restrisikoen er målt, ikke eliminert.** Kvitteringen rapporterer de tre EU Art-29-WP216-kriteriene
  (singling-out / linkability / inference) med standard SDC-mål. En PASS betyr at risikoen er under de
  konfigurerte tersklene — ikke at datasettet er «fullstendig anonymt».
- **Pseudonymisering ≠ anonymisering** (EDPB 01/2025, Datatilsynet). Fjerning av direkte identifikatorer
  alene gjør ikke data anonyme; gjenidentifisering via kvasi-identifikatorer er fortsatt mulig uten
  k-anonymisering.
- **k-anonymitet ≠ differensiell personvern.** k-anonymitet beskytter mot singling-out, men gir ingen
  formell garanti mot inferens på tvers av klasser; l-diversitet demper, men løser ikke,
  homogenitets- og bakgrunnskunnskaps-angrep.
- **Generaliseringsvalgene er analytiker-beslutninger** (aldersbånd, k, terskler) — de er
  konfigurasjon, ikke fasit, og påvirker både restrisiko og analytisk nytteverdi (utility/privacy-avveiing).
- **`anonymeter`-pakken brukes ikke** (uinstallérbar på numpy 2; laget for syntetiske data). De tre
  kriteriene er vendoret med SDC-matematikk i `core/anonymize/risk.py` — se `docs/anonymize.md`.
- **BRFSS-demoen bruker et syntetisk, BRFSS-formet fixture** (deterministisk generert). Den ekte
  CDC BRFSS-mikrodatafilen er dokumentert, men ikke inkludert i repoet.

## Kartkoplinger (fremtidig arbeid)

Kartverket GeoJSON-grenser for kommuner (WFS/REST) er **ikke** inkludert i v0.1. Et koropletkart ville øke visualiseringsverdien. Ikke ekskludert av tekniske grunner — nedprioritert for framdrift.

## «Utdannet lege (master i medisin)» som forfatter

Analysen er laget av en lege med helseinformatikk-kompetanse, ikke en dedikert statistiker eller økonom. Metodologiske valg (press-indeksformel, veksttakt-proxy, feature engineering) er fornuftige men ikke ekspert-validert. Framtidige versjoner bør inkludere peer review fra helsestatistiker.

## Offentlig nettsted (report site)

Det offentlige nettstedet på https://alksalt.github.io/omsorgsradar/ viser **kun aggregerte
rapporter, bokmål-tekst og figurer**. Ingen rad-nivå- eller individdata publiseres — nettstedet
er bygd fra committede `*_rapport.md`-filer og `figures/*.png`-bilder via en CI-pipeline som
aldri berører rådata. Nettstedet bygges automatisk ved push og er reproducerbart fra committede
artefakter.

## Kommunesammenslåinger — v1-tall (2026-06-11)

v1-artefaktene (`data/findings.json`, «Key findings» i README) ble beregnet med en
håndskrevet sammenslåingstabell som hadde minst én feil (1504 → 1506; gamle Ålesund
ble tilskrevet Molde). Tabellen er fra 2026-06-12 regenerert fra SSB KLASS
(klassifikasjon 131, 358 endringer, splitter ekskludert). Tall for
sammenslåtte kommuner i v1-artefaktene er upålitelige inntil v1-analysen kjøres
på nytt; nordisk-omsorg-analysen bruker den korrigerte tabellen.
