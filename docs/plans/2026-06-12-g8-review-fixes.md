# G8 — Eight-agent review fixes Implementation Plan

> **For agentic workers:** subagent-driven, sonnet implementers, opus review panel.
> Agent budget ≤10 (memory: agent-budget-frugality). Finding IDs (N1–N27, P5) refer to
> `docs/reviews/2026-06-12-eight-agent-full-repo-review.md` — read it first; it contains
> the concrete fix for every finding.

**Goal:** clear every finding from the 2026-06-12 eight-agent review: stale nordisk artifacts
republished, figures credible to a Norwegian reader (SSB attribution, colormap, nb-NO numbers,
navigable map), silent-failure gates so an empty source can never publish a green zero-data
report, security-ordering gaps closed, docs/DX truth pass.

**Architecture:** three parallel implementers with STRICT disjoint file ownership (A: report
surface · B: nordisk text + docs/DX · C: engine gates + security), then ONE serial controller
pass (cross-file verification threading, omsorgsradar re-render + nordisk re-run, single
republish), then a 3-reviewer re-review targeting the panel's BLOCK verdicts.

---

## File ownership (hard boundaries — an implementer may not touch another's files)

| Task | Owns |
|------|------|
| A | `src/omsorgsradar/report.py`, `src/omsorgsradar/maps.py`, `src/omsorgsradar/fmt.py` (new), `src/omsorgsradar/ml.py`, their tests |
| B | `analyses/nordisk-omsorg/stages.py`, `README.md`, `docs/site.md`, `docs/dataset-registry.md`, `docs/CONCEPT.md`, `CLAUDE.md`, `AGENTS.md`, `DECISIONS.md`, `pyproject.toml`, `.github/workflows/ci.yml` (new), their tests |
| C | `src/omsorgsradar/pipeline.py`, `src/omsorgsradar/stages.py`, `src/omsorgsradar/ingest.py`, `src/omsorgsradar/analyze.py`, `src/omsorgsradar/verify.py`, `src/omsorgsradar/core/config.py`, `src/omsorgsradar/core/adapters/*`, `.claude/hooks/block_raw_data_reads.py`, `analyses/*/analysis.toml`, their tests |
| D (controller, serial) | the one cross-boundary item (P5 verification-block threading), re-runs, republish, LIMITATIONS truth-up |

Shared-doc rule: targeted Edit only, never whole-file rewrites. Commits: explicit paths only.

---

## Task A — Report & figures credibility (N2 N3 N5 N6 N8 N9 N15 N27 + P5 bar-precision, TabPFN verbosity)

- [ ] **A1 · `fmt.py` + nb-NO numbers (N5).** New module: `nb(value, decimals)` → Norwegian
  format (comma decimal, thin/regular space thousands: `31,1`, `288 360`), `nb_pct`,
  `nb_index` (press index as `1,00`, two decimals — `1.000` reads as one thousand). TDD.
  Apply in `render_template`/`render_llm` AND all matplotlib tick/value labels. The «0,5»
  prose threshold stays. Bar value labels use the SAME precision as the table (P5).
- [ ] **A2 · Figure truth + colormap (N2 N3).** `plot_national_trend`: title
  «Nasjonal 80+-befolkning — trendframskriving til 2035 (+31,1 %; SSBs MMM-bane: +46 %)»
  (numbers from `result`, never literal), right bar «2035 (trendframskriving)», horizontal
  reference line at the SSB-MMM 2035 level (from `result.ssb_projection_growth_2035`) labeled
  «SSB MMM». `plot_press_index_bar` + scatter colorbar: sequential `Reds`-family, dark = high
  press (NEVER green for worst). Choropleth scale aligned (same direction/semantics).
- [ ] **A3 · Scatter label + map navigability (N6 N8).** Scatter y-label «Andel innbyggere 80+
  som mottar hjemmetjenester (%)». Choropleth: faint fylke borders (derive from first two
  digits of kommune codes — dissolve boundaries between same-fylke neighbors is overkill; a
  cheap acceptable version: draw the four city anchors + top-10 label callouts only), city
  anchors (Oslo/Bergen/Trondheim/Stavanger) + top-10 kommune labels at polygon centroids
  computed FROM the geojson. Anchor kommune codes live in `analyses/omsorgsradar/analysis.toml`
  `[params.report] map_anchor_knrs = [...]` — wait: analysis.toml is Task C's file. INTERFACE:
  A reads `params["report"]["map_anchor_knrs"]` with a safe default of `[]`; C adds the actual
  config values (see C6). A's tests use the param directly.
- [ ] **A4 · Datakvalitet block (N9).** In the report template: suppress zero-row sources from
  the table (replace with one sentence «FHI NOKKEL er ekskludert — API utilgjengelig»), `—`
  instead of `N/A`, befolkning row annotated «483 koderader (357 aktive kommuner + historiske
  koder)» — counts from data, not literals.
- [ ] **A5 · Figure guards (N15).** `run_report`: every figure call wrapped; a figure that
  raised OR did not write its PNG → collect; if any missing → raise RuntimeError (report must
  never publish broken image links). The choropleth keeps its documented skip-if-asset-missing
  behavior BUT the template must then omit the `![...]` embed (no dead link). Tests: empty
  result set → report raises, not broken-links.
- [ ] **A6 · `render_llm` default model (N27)** → `DEFAULT_REPORT_MODEL` sourced from
  `core/endpoint` (must exist in `MODEL_PRICING`); no bare string literal.
- [ ] **A7 · TabPFN no-token path (P5).** `ml.py`: detect missing token BEFORE the folds, one
  INFO line «TabPFN hoppes over — sett TABPFN_TOKEN (se COSTS.md)», no 3× 7-line WARNING.
- [ ] **A8 ·** `run_report(..., verification: VerificationReport | None = None)` — when given,
  the report's verification block renders THE GATE's report (31/31 incl. DB receipts, with a
  one-clause gloss of what a «kontroll» is); when None, current rebuild behavior. A only adds
  the parameter + rendering; C/D thread the call site. Full pytest, commit
  `G8-A: report credibility — nb-NO, colormap, SSB attribution, figure guards`.

## Task B — Nordisk text + docs/DX truth pass (N10 N19 N21–N26 + P5 doc minors)

- [ ] **B1 · nordisk report text (N10 + P5).** KUHR block: add the bridge sentence (fastlege-
  konsultasjonsvolum som proxy for primærhelse-trykk i kommunene) or drop the block — pick
  bridge sentence; format «−7,0 %» nb-style. Fix «Analysen er deskriptivt, ikke kausalt» →
  «deskriptiv, ikke kausal». Add one-clause gloss to «168/168 kontroller» (one recompute per
  rangert kommune + nasjonale aggregater).
- [ ] **B2 · nordisk per-country guards (N19).** In `stage_report_nordisk` (and analyze if
  apt): empty country frame → `PipelineGateError` naming the country and source. Test.
- [ ] **B3 · DX: dev deps (N21).** Move pytest/dev tooling from
  `[project.optional-dependencies].dev` to `[dependency-groups].dev` (uv installs default
  groups on plain `uv sync`). Verify: fresh `uv sync` → `uv run pytest` green. README needs no
  flag then; remove any `--extra dev` mentions if present.
- [ ] **B4 · Path/docs truth (N22 N23 N24).** README Output-files section →
  `reports/<name>/<name>_rapport.md`; named-analysis quick-start command gains
  `--data-dir data/<name> --reports-dir reports/<name>`; note that the default run regenerates
  committed `data/*.json`; site-build command gains `--marimo notebooks/explore_nordisk.py`;
  `docs/site.md` git-add → `git add reports/<name>/`. NEW README section «Creating a new
  analysis»: minimal `analysis.toml` skeleton + stages list + pointer to docs/adapters.md and
  the magic-analyze skill.
- [ ] **B5 · Registry + orientation (N25 N26 + P5 CONCEPT).** `docs/dataset-registry.md`:
  12880 → 13599 (MMM, 80+, national) per the review's replacement line. `CLAUDE.md`: status →
  G0–G8, engine module list completed (endpoint, anonymize, geo, discovery, site, maps; stages
  incl. anonymize/ml). `AGENTS.md`: G4 «anonymeter» → vendored WP216 wording; G5
  `ANTHROPIC_BASE_URL` → `[endpoint.local].base_url`. `DECISIONS.md:21` same base_url fix
  (replace, don't stack). `docs/CONCEPT.md` FHI row → annotate 404/excluded.
- [ ] **B6 · CI test job (P5).** New `.github/workflows/ci.yml`: on push/PR → `uv sync` +
  `uv run pytest` (offline suite only; least-privilege permissions, no secrets). Do NOT touch
  pages.yml. Full pytest, commit `G8-B: nordisk text guards + docs/DX truth pass + CI tests`.
- [ ] **B7 · Landing-page reconciliation (N4).** `site.py` is Task A's neighbor but the card
  text lives in the INDEX template (`src/omsorgsradar/templates/index.html.j2`) and
  `_SLUG_PRIORITY`/summary plumbing in `site.py` — OWNERSHIP EXCEPTION: B owns
  `src/omsorgsradar/site.py` + `templates/` for this plan (A must not touch them). Add per-card
  method+window line (omsorgsradar: «trendframskriving 2017→2035, press-indeks»; nordisk:
  «historisk 2019–2023, z-skår innen land — sammenlignbar på tvers av Norden»; brfss:
  «anonymiseringsdemo, syntetiske mikrodata») + one site-intro sentence that the two norske
  analysene bruker ulike vinduer/metoder og rangerer ulikt med vilje. ALSO N20 (site rmtree):
  `site.main` must NOT delete the built site on marimo failure — placeholder `/explore/` page +
  loud stderr warning instead. Tests for both.

## Task C — Engine gates + security (N7 N11 N12 N13 N14 N16 N17 N18 + P5 load_findings)

- [ ] **C1 · run_ingest allowlist (N11).** `validate_source_host(src, extra_hosts)` inside
  `run_ingest`'s source loop; thread `extra_hosts` from `stage_ingest`. Test mirroring the
  pipeline-level rejection test but calling `run_ingest` directly.
- [ ] **C2 · Redirect pinning (N12).** Shared `safe_request(method, url, *, allowed_hosts, ...)`
  in `core/adapters/__init__.py`: `allow_redirects=False`, manual hop loop re-validating each
  `Location` host against the allowlist (dot-bounded suffix match, same as
  `validate_source_host`), refuse cross-host redirects. Route ALL adapter requests (pxweb GET/
  POST, sotkanet, socialstyrelsen, kolada, kuhr) through it. Tests: 302 to non-allowlisted host
  → raises; same-host redirect → followed; 307 POST re-validation.
- [ ] **C3 · Anonymize ORDERING gate (N13).** `pipeline.py` row_level check: anonymize present
  AND `index(anonymize) < index(analyze|ml|report)` for any present downstream stage; clear
  PipelineGateError message. Test: stage list with analyze before anonymize → refused at startup.
- [ ] **C4 · FAIL-CSV cleanup (N14).** `stage_anonymize`: on FAIL verdict, `unlink` the
  anonymized CSV before raising (receipt JSON stays — that's the evidence). Add
  `data/[^/]+_anonymized\.csv` to the hook's BLOCKED_PATTERNS (belt: even a PASS table is
  row-derived; model context should read the receipt, not the table). Tests both layers.
- [ ] **C5 · Mandatory-source gate (N17).** Schema: optional `required = true` per `[[sources]]`
  (`core/config.py`, additionalProperties stays strict). `stage_profile`: any required source
  with an empty frame → PipelineGateError. `stage_verify`: hard guard
  `any(km.rank >= 1 for km in result.kommuner)` else FAIL (zero-data report impossible).
  Set `required = true` on kostra_pleie + befolkning (omsorgsradar), the NO/SE/FI core sources
  (nordisk), brfss microdata source. Tests: empty required source → gated; optional
  (fhi_nokkel) empty → run continues as today.
- [ ] **C6 · Projection fallback surfaced (N16).** `fetch_population_projections`: keep
  catching, but log ERROR and return a SENTINEL the caller can distinguish; `run_analysis`
  appends a visible note («SSB-framskriving utilgjengelig — rapporten siterer kun trendtall»)
  AND `verify` gains a claim/flag: if `growth_method` says projection data was expected but
  `ssb_projection_growth_2035` is NaN → verification FAIL (config-driven expectation via the
  `required` flag on the framskrivinger source: required=false but `expected=true`-style —
  simplest: mark framskrivinger `required = true` for omsorgsradar; an SSB outage then fails
  the run loudly instead of silently shipping a weaker report. Document the choice).
  ALSO add `[params.report] map_anchor_knrs = ["0301","4601","5001","1103"]` to
  `analyses/omsorgsradar/analysis.toml` (interface for A3).
- [ ] **C7 · skip-ingest catch (N18) + minors.** `stage_ingest` skip path: catch ONLY
  `duckdb.CatalogException` → empty frame; re-raise everything else. `analyze.py`
  `load_findings`: replace every `raw.get(k) or default` with explicit None-check (P5).
  `analyze.py` module docstring + `coverage_rate` field comment + `verify.py` source_text:
  correct unit description — KOSTRA andel-% used directly, no per-1000 division (N7).
  Full pytest, commit `G8-C: ingest allowlist, redirect pinning, anonymize ordering, mandatory-source gates`.

## Task D — Controller serial pass (N1 + P5 threading + republish)

- [ ] **D1 ·** Thread the gate verification into the report: `stages.py` report stage passes
  `ctx.state["verification"]` to `run_report(verification=...)` (A8's parameter). Run pytest.
- [ ] **D2 ·** Re-run `analyses/omsorgsradar` (`--reports-dir reports/omsorgsradar`, cached
  ingest) — new figures/formatting; verify gate green; VIEW the three regenerated figures
  (Read tool) to confirm: red-dark = worst, nb-decimals, SSB-MMM reference line present.
- [ ] **D3 · N1:** re-run nordisk: `uv run python -m omsorgsradar.pipeline
  analyses/nordisk-omsorg --data-dir data/nordisk-omsorg --reports-dir reports/nordisk-omsorg`
  (offline from committed cache). Confirm terminal codes in top-10 (NO-3216 Vestby, NO-3214
  Frogn, NO-3220 Enebakk, NO-3232 Nittedal, NO-5522 Salangen), n_dropped ≠ 157, verify green.
- [ ] **D4 ·** LIMITATIONS truth-up: «alle publiserte tall…» claim now true again — restate
  with date; note the figure/colormap conventions if useful. Fresh-clone DX check: in /tmp,
  `git clone . && uv sync && uv run pytest` green (N21 proof).
- [ ] **D5 ·** Commit artifacts, push, Pages deploy green, live checks: nordisk page has no
  retired codes; omsorgsradar page shows «31,1 %» (comma); explore 200; no `/Users/` or token.
- [ ] **D6 ·** status.md close-out + review-md findings table annotated with fix status.

## Review panel (after D5, before final close-out)

3 reviewers, targeted at the panel's BLOCK verdicts:
- **domain/content re-review (opus, blind-ish):** fetch the LIVE site fresh; verify N2-N5,
  N8-N10 actually flip the kommunehelsesjef/statistiker verdict; nb-formatting everywhere.
- **correctness (opus):** N1 republished numbers vs DuckDB/KLASS; mandatory-source +
  zero-data gates actually gate (run the planted scenarios); figure guards.
- **security (opus):** C1-C4 — redirect hop validation, ordering gate bypass attempts,
  FAIL-CSV + hook pattern, run_ingest direct call.
Any BLOCK → fix → re-review (cap 3). Budget: 3 implementers + 3 reviewers + ≤2 fix rounds ≤ 9.

## Quality gates
`uv run pytest` green (382 + new) · fresh-clone `uv sync && uv run pytest` green ·
`--validate-only` × 3 analyses · site build = 3 analyses + explore · live-site checks (D5) ·
new ci.yml green on push.

## Out of scope (explicitly)
Dependency CVE audit (owner call, P5 note stands) · interactive map · absolute-headcount
column in top-20 (good idea from the domain reviewer — separate decision, changes the
analysis surface) · marimo notebook content changes.
