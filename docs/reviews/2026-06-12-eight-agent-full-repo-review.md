# Eight-agent full-repo review — 2026-06-12

> **STATUS (post-G8, same day):** all P0–P4 findings (N1–N27) and the actionable P5 minors are
> FIXED — commits `2d13ff5`/`b25c29b`/`c9bdfa1` (tasks B/A/C), `07461ce`/`ef4dc98` (controller
> pass + republish), `dc98a89` (panel-fix round: nordisk nb-NO formatting, SSB discovery GET
> through safe_request). Re-review panel: correctness PASS, security PASS (residual
> `_discover_ssb_table` closed in dc98a89), domain BLOCK→fixed (nordisk nb-NO) → verified live.
> Remaining open (deliberate): dependency CVE pass (owner call), interactive map,
> absolute-headcount column (owner decision), security observation «https→http downgrade on
> same-host redirect» (optional hardening), N13 residual: instance stages.py can shadow the
> anonymize stage — accepted, since authoring stages.py is already code execution.
> Tests 382 → 445 offline + 5 live.

**Method:** 8 independent agents over the entire repo + live site. Four **blind** (no access to
status.md / plans / review history — judged the artifact cold): correctness, security,
fresh-user DX, Norwegian domain credibility (kommunehelsesjef + SSB-statistiker personas). Four
**informed** (full context, pointed at what G7 did NOT cover): correctness of untouched areas,
security-invariant sweep, silent-failure hunt, docs-vs-code drift.

**Verdicts:** blind-correctness PASS · blind-security PASS · blind-DX **BLOCK** ·
blind-domain **BLOCK** · informed-correctness **BLOCK** · informed-security **BLOCK** ·
silent-failure **BLOCK** · docs-drift **BLOCK**.

**One-line summary:** the math is right and the repo leaks nothing — but one published report is
stale (retired kommune codes live on the site), the headline figure misattributes the trend to
SSB, the figures' color semantics are inverted, and the docs/quick-start drifted behind the code.

---

## Part 1 — Problems found and FIXED earlier today (G7 session, for the record)

| # | Problem | Status |
|---|---------|--------|
| F1 | Hand-written merger table error (1504→1506) — v1 published numbers wrong | fixed (KLASS regen) + republished |
| F2 | KLASS mappings not chained across waves (0111→3011 stopped before →3110) → split series → Hvaler +252% growth artifact at rank #1 | fixed (transitive closure, 468 mappings) |
| F3 | Dead/historical kommune codes ranked as municipalities (613 "ranked", Norway has 357) | fixed (354 ranked, living+computable only) |
| F4 | Uniform national 3.5% growth for every kommune (identical-36% column) | fixed (per-kommune CAGR + guards) |
| F5 | CAGR explosion on short windows (no min-window/clamp guards) | fixed (config-driven guards) |
| F6 | **Verifier was tautological** — claims verified against the same in-memory object they came from; could never fail in production | fixed (independent DB receipts from disk + DuckDB, planted-corruption tests) |
| F7 | "SSB implies faster growth" asserted but never computed — and table 12880 turned out to be SSB macro accounts, not projections | fixed (table 13599 MMM: 46.5% computed and cited) |
| F8 | 3 phantom-ranked kommuner with no computable press index | fixed (rank 0) |
| F9 | Terminal codes carried predecessor names (Hemne/Orkdal/Ballangen for Heim/Orkland/Narvik); SSB validity suffixes («Frogn (-2019)») in names | fixed |
| F10 | Absolute `/Users/ol/...` paths leaked in committed manifest sidecars | fixed (repo-relative) |
| F11 | `load_findings` dropped `growth_method` on round-trip | fixed |
| F12 | Report template: stale date, FHI listed as source, "dekker 483 kommuner", "per 1 000" for a percent | fixed |

---

## Part 2 — NEW findings (this panel), by priority

### P0 — published content is wrong or stale (fix before anything else)

**N1 · BLOCK · nordisk-omsorg published artifacts are stale — retired kommune codes live on the site.**
G7 re-ran only `analyses/omsorgsradar`; `reports/nordisk-omsorg/` + `data/nordisk-omsorg/` were
generated with the pre-G7 (358-entry) merger table. **5 of the published NO top-10 geo_ids are
SSB-retired 2024-wave codes** (3019→3216 Vestby, 3022→3214 Frogn, 3028→3220 Enebakk,
3031→3232 Nittedal, 5417→5522 Salangen — confirmed against KLASS changes API); `n_dropped=157`
is computed under the superseded table. LIMITATIONS' «alle publiserte tall ble regenerert
2026-06-12» is false for this analysis.
Fix: `uv run python -m omsorgsradar.pipeline analyses/nordisk-omsorg --data-dir
data/nordisk-omsorg --reports-dir reports/nordisk-omsorg` (offline-capable from committed
cache) → confirm terminal codes + new n_dropped → commit + rebuild site + redeploy.

**N2 · BLOCK · national_trend figure attributes the trend number to SSB.**
`reports/omsorgsradar/figures/national_trend.png` title: «vekst til 2035 (+31.1% om SSB-bane
opprettholdes)», right bar «2035 (projeksjon)». The report text explicitly says this is NOT
SSB's projection (SSB MMM = 46%). The headline chart inverts the report's central honesty move.
Fix in `report.py::plot_national_trend`: title «trendframskriving til 2035 (+31,1 %; SSBs
MMM-bane: +46 %)», bar label «2035 (trendframskriving)», add a reference marker at the SSB MMM
level.

**N3 · BLOCK · press-index bar + scatter colormap is inverted — worst kommune is painted green.**
RdYlGn with high press = green: Frogn (worst, 1.00) renders dark green, least-pressed renders
red. Green=OK is universal in Norwegian municipal dashboards.
Fix: `RdYlGn_r` or a sequential `Reds` (dark = high press) in `plot_press_index_bar` and the
scatter colorbar; align the choropleth scale semantics at the same time.

**N4 · BLOCK · landing page: two Norwegian analyses contradict each other with no reconciliation.**
Same kommune, same question, different answers side by side (Vestby growth 116.8% vs 38.18%;
Frogn rank 1 vs 3) — different windows/methods by design, but the site never says so.
Fix: one method+window line per landing card («trendframskriving 2017→2035, press-indeks» /
«historisk 2019–2023, z-skår innen land») + one sentence that rankings differ by design.

### P1 — published-quality (important)

**N5 · Norwegian number formatting violated throughout** — dot decimals everywhere («31.1%»,
«1.000» which a Norwegian reads as one thousand) next to one correct «0,5». Fix: nb-NO
formatting in report template + matplotlib labels («31,1 %», index as «1,00»).
**N6 · Scatter y-axis still mislabeled** «per 1000 innbygger 80+» for a percent axis
(`report.py:169`). Fix label to «Andel innbyggere 80+ som mottar hjemmetjenester (%)».
**N7 · coverage_rate is documented as a per-1000 division the code never performs**
(analyze.py module docstring :11-12, field comment :70, verify.py source_text) — it is KOSTRA
andel-% used directly. Numbers are consistent; the method description is false. Fix docstrings
+ verifier source_text.
**N8 · Choropleth fails the "find my kommune" test** — no city anchors, no fylke borders, no
labels. Fix: annotate top-10 + Oslo/Bergen/Trondheim/Stavanger, faint fylke borders.
**N9 · Report «Datakvalitet» block leaks profiler dump** — «N/A kommuner», «fhi_nokkel: 0
rader» listed as a source, «483 kommuner» unexplained on the public page. Fix: suppress
zero-row sources (one sentence instead), «—» for N/A, annotate «483 koderader (357 aktive)».
**N10 · KUHR fastlege-stat sits in the nordisk report with no relevance bridge** (and «-7.0 %»
needs nb format). Fix: add the one-sentence proxy rationale or delete the block.

### P2 — security (defense-in-depth; nothing exploitable by site visitors, no secrets/PII found)

**N11 · `run_ingest` bypasses the host allowlist** — validation lives only in `run_pipeline`'s
preamble; the legacy fetchers (`kostra_pleie`, `befolkning`, `framskrivinger`, `fhi_nokkel`)
`requests.get` any config base_url when `run_ingest` is called programmatically. Fix: call
`validate_source_host` inside `run_ingest`'s source loop; add the direct-call test.
**N12 · Adapters follow HTTP redirects** (`allow_redirects` default) — a 302 from an
allowlisted host exits the allowlist; pxweb POST bodies re-sent on 307/308. The per-page
`next_url` host-pinning does not cover HTTP-layer redirects. Fix: `allow_redirects=False` +
shared `safe_get` that re-validates each Location hop.
**N13 · `row_level=true` gate checks anonymize PRESENCE, not ORDERING** — a machine-authored
stage list `[ingest, profile, analyze, anonymize, …]` passes the gate yet runs analyze on raw
rows. Fix: enforce anonymize-index < analyze/ml/report indices in the pipeline gate.
**N14 · On a FAIL identifiability verdict, the insufficiently-anonymized CSV stays on disk** in
model-readable `data/` (written before the gate check; hook doesn't cover `data/*_anonymized.csv`).
Fix: unlink on FAIL + add the pattern to the hook's BLOCKED_PATTERNS.

### P3 — silent failures (published output can be silently wrong/incomplete)

**N15 · Figure generation is unguarded** — empty-input paths log a warning, write NO file, and
the report still embeds the `![…]` link → published broken images, green CI. (Includes the
choropleth `None` return path.) Fix: collect missing figures in `run_report` and abort (or
visibly placeholder) instead of publishing broken links.
**N16 · `fetch_population_projections` swallows every exception** → empty frame → report
silently loses the SSB-46% comparison; no verify claim asserts `ssb_projection_growth_2035` is
present. Fix: surface the fallback in `result.notes` + add a verify claim/flag.
**N17 · No mandatory-source gate** — empty `befolkning`/`kostra_pleie` produces a green
pipeline, trivially-passing verification (claims built from the same empty result), and a
published zero-data report. Fix: `PipelineGateError` in stage_profile for empty mandatory
sources + a verify guard `any(km.rank >= 1)`.
**N18 · `--skip-ingest` swallows DuckDB load errors** into empty frames (catch-all except).
Fix: catch only `duckdb.CatalogException`; re-raise everything else.
**N19 · nordisk report figures lack per-country non-empty guards** — an empty FI frame dies as
a raw matplotlib error with no context. Fix: explicit per-country `PipelineGateError`.
**N20 · `site.main` deletes the just-built site when marimo export fails** (`rmtree` then
re-raise) — CI then fails on a confusing upload error, or worse. Fix: never rmtree on marimo
failure; build the static site, placeholder `/explore/`, warn loudly.

### P4 — docs/DX drift (a newcomer cannot follow the README to the described state)

**N21 · BLOCK(DX) · `uv sync` + `uv run pytest` fails as written** — pytest lives in the `dev`
extra; bare `uv sync` removes it. Fix: README → `uv sync --extra dev`.
**N22 · Output-path docs are wrong** — README says `reports/<name>_rapport.md`; reality is
`reports/<name>/…` produced with an undocumented `--reports-dir`; `docs/site.md` git-add path
mixes both. Default pipeline run also dirties tracked `data/*.json` with no warning. Fix:
document `--data-dir/--reports-dir` per analysis, fix site.md, note artifact regeneration.
**N23 · README site-build command omits `--marimo notebooks/explore_nordisk.py`** — local build
silently lacks the explore page CI produces. Fix: add the flag.
**N24 · No "create a new analysis" guide** anywhere a GitHub reader looks. Fix: README section
or docs page with minimal `analysis.toml` skeleton.
**N25 · CRITICAL(docs) · `docs/dataset-registry.md` still lists table 12880 as framskrivinger**
— the exact wrong-table bug G7 fixed, on the surface `/magic-analyze` reads first. Fix: 13599
(MMM, 80+), per the finding's replacement line.
**N26 · Orientation drift:** `CLAUDE.md` status stops at G3 ("next: G4") and the engine module
list omits endpoint/anonymize/geo/discovery/site/maps; `AGENTS.md` G4 still says "anonymeter"
(rejected, uninstallable) and G5 says `ANTHROPIC_BASE_URL` (no such env var — it's
`[endpoint.local].base_url`, also wrong in DECISIONS.md:21). Fix per finding text.
**N27 · `render_llm` default model `claude-sonnet-4-5`** is not in MODEL_PRICING (cost
silently None on direct calls). Fix default → config-driven/`claude-fable-5`.

### P5 — minor
- Report verification block shows «5/5» while the gate ran 31 checks (report rebuilds its own
  5-claim set) — pass the gate's report through instead. Also gloss what a «kontroll» is
  (nordisk «168/168»).
- `load_findings` uses `raw.get(k) or nan` — a legitimate 0.0 collapses to NaN.
- Bar-chart value labels rounded differently than the table (0.94 vs 0.935).
- nordisk report: «Analysen er deskriptivt, ikke kausalt» → «deskriptiv, ikke kausal».
- CI has no test job (site deploy only) — add a `uv run pytest` job.
- TabPFN no-token path: 7-line WARNING ×3 folds → single INFO with COSTS.md pointer.
- `docs/CONCEPT.md` still presents FHI NOKKEL as functional (concept doc; annotate).
- New deps since v1 (nh3, markdown, jinja2, marimo, presidio×2) — owner CVE pass pending.

---

## Recommended fix order (G8)

1. **N1** — re-run + republish nordisk-omsorg (mechanical, offline; removes live wrong codes).
2. **N2-N4** — figure title, colormap, landing reconciliation (hours; flips the domain verdict).
3. **N5-N10** — nb-NO formatting + label/credibility pass.
4. **N15-N20** — silent-failure gates (mandatory sources, figure guards, site rmtree).
5. **N11-N14** — security defense-in-depth (ingest allowlist, redirects, anonymize ordering, FAIL-CSV).
6. **N21-N27** — docs/DX truth pass.
7. P5 minors opportunistically.
