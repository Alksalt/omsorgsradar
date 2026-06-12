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

### Kommunesammenslåinger og omnummereringer
- Tabellen i `kommune_mergers.py` er **regenerert fra SSB KLASS** (klassifikasjon 131,
  2026-06-12): 468 én-til-én-mappinger som dekker både 2020-bølgen og
  2024-omnummereringene (fylkesoppløsningene: Viken 30xx → 31xx/32xx/33xx,
  Telemark 38xx → 40xx, Troms/Finnmark 54xx → 55xx/56xx m.fl.).
- Mappingene er **transitivt oppløst til terminale koder** (gamle Hvaler 0111 → 3011 → mappes
  direkte til 3110), slik at hver kommune har én sammenhengende tidsserie.
- **Ekte splittelser er ekskludert by design** ({1507 Ålesund → 1508 + 1580, 1850 Tysfjord,
  5012 Snillfjord}): historikken før splittelsen kan ikke fordeles entydig på etterfølgerne.
  For disse kommunene starter tidsserien ved splittelsen (Ålesund/Haram: 2024).
- Kun kommuner som finnes i siste dataår rangeres; historiske koderader beholdes i
  datagrunnlaget, men er ekskludert fra rangeringen. En uavhengig strukturell kontroll i
  verifikatoren håndhever dette ved hver kjøring.

### Befolkningsframskrivinger — trendframskriving, ikke SSB-projeksjon
- SSB tabell 13873 (kommunevise framskrivinger) er ikke tilgjengelig via det offentlige
  PxWebAPI (bekreftet re-sjekk 2026-06-12, både v0 og v2) — dokumentert i `docs/api_drift.md`.
- Veksten per kommune er derfor en **historisk trendframskriving**: CAGR per kommune beregnet
  fra SSB tabell 07459 (80+-befolkning 2017–2026), ekstrapolert til 2035. Robusthetsvakter
  (konfigurert i `analysis.toml`): minst 5 års datavindu, og årsrater utenfor et rimelighetsbånd
  faller tilbake på nasjonal rate. `growth_source` per kommune angir hvilken kilde som ble brukt
  («kommune», «national_short_window», «national_outlier_rate», «national», «default»).
- **Metoden undervurderer trolig veksten.** De store etterkrigskullene begynner å passere 80 år
  rundt 2025–2030; historisk CAGR fra 2017–2026 fanger ikke denne akselerasjonen. Aggregert gir
  trendmetoden ~31 % nasjonal 80+-vekst til 2035, mens **SSBs nasjonale hovedalternativ (tabell
  13599, framskrivingsalternativ MMM) gir ~46 %** for 80+ over samme periode (2026→2035; hentet
  og verifisert 2026-06-12, lagret som funn-feltet `ssb_projection_growth_2035`). SSBs
  hovedalternativ impliserer altså vesentlig raskere vekst enn trendmetoden. Den **relative**
  rangeringen mellom kommuner påvirkes mindre enn nivåene, men 2035-nivåene bør leses som nedre
  planleggingsanslag. (Den tidligere refererte tabellen 12880 var feil — det er SSBs
  makroøkonomiske regnskapstabell uten alders- eller framskrivingsdimensjon; se `docs/api_drift.md`.)
- Fremskrivinger er usikre utover 5 år. 2035-tallene er planleggingshorisonter, ikke prediksjoner.

### FHI NOKKEL
- FHI NOKKEL-endepunktet ble re-sjekket 2026-06-12: `statistikk-data.fhi.no/api/open/v1` returnerer fortsatt 404 for alle stier; det finnes ingen kjent offentlig REST-API som erstatter det. FHI-data er ekskludert fra analysen.

## Hva verifikatoren faktisk kontrollerer («tool receipts»)

Verifikasjonssteget gir to lag, og overselger ikke:

- **Narrasjons-troverdighet (claims vs funn):** hver tallpåstand i rapportteksten
  regnes om fra det strukturerte `findings.json` og flagges ved avvik. Dette fanger
  en hallusinert verdi i narrativet, men det er **ikke** et uavhengig bevis på at
  `findings.json` selv er riktig — påstanden og fasiten kommer fra samme objekt.
- **Uavhengige DB-kvitteringer:** verifikatoren laster `findings.json` **fra disk** og
  regner om nøkkeltallene **direkte fra DuckDB-tabellen `befolkning`**, uten å kalle
  analysekoden: (1) nasjonal 80+-sum i siste år mot funnenes `national_80plus_latest`,
  (2) den strukturelle kontrollen at hver rangert kommune lever i siste befolkningsår,
  og (3) per-kommune 80+-vekst for et deterministisk utvalg (topp-10 rangerte + hver
  25. rangerte) for radene som brukte kommune-egen CAGR. Et korrupt `findings.json`
  (feil nasjonal sum, oppblåst kommune-vekst) får verifikasjonen til å **FAILE** og
  stopper pipelinen før rapport skrives. Fallback-rader (national/projection/default
  vekstkilde) sammenlignes ikke per kommune, siden raten der er konfigurert/projisert,
  ikke en ren DB-omregning.

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

## Kartgrunnlag (koropletkartet)

Koropletkartet bruker **forenklede kommunegrenser** (committet GeoJSON, Kartverket-avledet,
CC BY 4.0 — se `assets/geo/PROVENANCE.md`). Forenklingen gjør kystlinjer omtrentlige: kartet er
en visualisering av press-indeksen, ikke et GIS-grunnlag. Kommuner uten data i siste år vises i
grått med antall oppgitt i figurteksten.

## «Utdannet lege (master i medisin)» som forfatter

Analysen er laget av en lege med helseinformatikk-kompetanse, ikke en dedikert statistiker eller økonom. Metodologiske valg (press-indeksformel, veksttakt-proxy, feature engineering) er fornuftige men ikke ekspert-validert. Framtidige versjoner bør inkludere peer review fra helsestatistiker.

## Offentlig nettsted (report site)

Det offentlige nettstedet på https://alksalt.github.io/omsorgsradar/ viser **kun aggregerte
rapporter, bokmål-tekst og figurer**. Ingen rad-nivå- eller individdata publiseres — nettstedet
er bygd fra committede `*_rapport.md`-filer og `figures/*.png`-bilder via en CI-pipeline som
aldri berører rådata. Nettstedet bygges automatisk ved push og er reproducerbart fra committede
artefakter.

## Historikk: v1-tall (2026-06-11) — erstattet

v1-artefaktene ble beregnet med en håndskrevet sammenslåingstabell som hadde minst én feil
(1504 → 1506; gamle Ålesund ble tilskrevet Molde) og en uniform nasjonal vekstrate for alle
kommuner. Begge er rettet: tabellen er regenerert fra SSB KLASS (468 mappinger, transitiv
oppløsning, splittelser ekskludert) og veksten beregnes per kommune. **Alle publiserte tall ble
regenerert 2026-06-12 med den korrigerte metoden** — v1-toppen (Hasvik/Bjerkreim/Tydal) var i
hovedsak et artefakt av uniform vekst kombinert med lav dekning; den korrigerte analysen peker
på Oslo-belte-kommunene (Frogn, Vestby, Lørenskog) der 80+-veksten faktisk er raskest.
