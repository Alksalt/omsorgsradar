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
- TabPFN-2.5 ble ikke kjørt (krever interaktiv lisensgodkjenning hos PriorLabs — se COSTS.md for detaljer).
- MAE på ~2 prosentpoeng er moderat — mye av prediksjonskraften kommer fra lag-1 (forrige år), som er en enkel persistence-heuristikk.

## Aggregert nivå — ingen individdata

All analyse er på **kommunalt aggregatnivå** over offentlige aggregatstatistikker. Ingen individdata, ingen pasientdata. Ingen REK-godkjenning er nødvendig.

## Kartkoplinger (fremtidig arbeid)

Kartverket GeoJSON-grenser for kommuner (WFS/REST) er **ikke** inkludert i v0.1. Et koropletkart ville øke visualiseringsverdien. Ikke ekskludert av tekniske grunner — nedprioritert for framdrift.

## «Utdannet lege (master i medisin)» som forfatter

Analysen er laget av en lege med helseinformatikk-kompetanse, ikke en dedikert statistiker eller økonom. Metodologiske valg (press-indeksformel, veksttakt-proxy, feature engineering) er fornuftige men ikke ekspert-validert. Framtidige versjoner bør inkludere peer review fra helsestatistiker.
