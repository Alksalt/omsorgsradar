# G7 — Deferred fixes + choropleth + TabPFN Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Sonnet implementers,
> opus review panel. Agent budget ≤10 total (see memory: agent-budget-frugality).

**Goal:** Close every outstanding error the review panels found but G2–G6 deferred, add the
choropleth map (the one visualization with real legibility ROI for Norwegian e-helse readers),
and make TabPFN-2.5 actually runnable — then ONE live re-run regenerates all published v1
artifacts with every fix at once.

**Architecture:** Three independent code tasks (A: per-kommune projections, B: choropleth,
C: TabPFN parity) touching disjoint files, then one serial re-run + docs task (D), plus a
timeboxed FHI probe (E). Single review panel after all code lands. The re-run is LAST so the
site publishes once, with corrected mergers + real per-kommune growth + map + honest ML framing
together.

**Tech stack:** existing engine (pxweb adapter, verify gate), matplotlib `PolyCollection` for
the map (**no geopandas — zero new heavy deps**), tabpfn (already pinned `>=8.0.8`).

---

## Outstanding agent-found issues this phase closes

| # | Finding | Found by | Status today |
|---|---------|----------|--------------|
| 1 | v1 published numbers computed with buggy hand-written merger table (1504→1506 Ålesund→Molde, NO-growth blown to 246%) | G2 correctness panel | Table regenerated from KLASS; **v1 artifacts + README "Key findings" + live site still show pre-fix numbers** (LIMITATIONS.md:87-94 admits this) |
| 2 | Identical 36.3% growth column — every kommune gets the same national rate | G6 content reviewer (cosmetic fix only) | Root cause untouched: `analyze.py:183-189` applies one `national_growth_rate` to all kommuner; SSB 13873 (kommune projections) 400-error never re-investigated |
| 3 | Raw TabPFN error string in report; TabPFN never ran | G6 content reviewer (cosmetic fix only) | `ml.py:368-417` exists but single-holdout (not fold-parallel with XGB) and license path undocumented |
| 4 | FHI NOKKEL 404, dangling "Planlagt: integrering … når tilgjengelig" promise | P0, documented in api_drift.md | Never re-probed |
| 5 | README line 3 still says "(goes live once GitHub Pages is enabled…)" | — | Site IS live; stale |
| 6 | LIMITATIONS "2024-bølgen ikke dekket" text predates the KLASS regen (which covers changes through 2024 but excludes splits by design) | — | Stale/imprecise |

---

## Task A — Per-kommune 80+ projections (kills the uniform-growth assumption)

**Files:**
- Modify: `src/omsorgsradar/ingest.py` (new optional source fetch)
- Modify: `analyses/omsorgsradar/analysis.toml` (new `[[sources]]` block)
- Modify: `src/omsorgsradar/analyze.py:140-193` (projection function)
- Modify: `src/omsorgsradar/verify.py` (recompute growth claims from the new path)
- Modify: `docs/api_drift.md` (document the discovery outcome either way)
- Test: `tests/test_analyze.py`, `tests/test_ingest.py` (offline fixtures)

**Steps:**

- [ ] **A1 — API discovery (live, one session).** The original 13873 400-error was likely
  query-shape, not access (precedent: KOSTRA region variable turned out to be
  `KOKkommuneregion0000`, discovered the same way). Probe via PxWebAPI v2 metadata:
  `GET https://data.ssb.no/api/pxwebapi/v2/tables/13873/metadata` → extract the real region
  variable code, age codes covering 80+, and the projection-alternative code (main alternative,
  typically `MMMM`). Query 80+ ages × all kommuner × years {baseline, 2035} × main alternative.
  If the cell count trips a limit, chunk by fylke prefix. If 13873 is genuinely unusable, search
  table metadata (`/tables?query=framskriv`) for a kommune-level alternative. **Document every
  probe + outcome in `docs/api_drift.md`. If nothing works, STOP Task A after A1, keep the
  fallback chain, and update LIMITATIONS honestly — that is a valid outcome.**

- [ ] **A2 — Fixture + ingest.** Capture one real (small) API response as an offline fixture
  (3 kommuner × 2 years), add the `[[sources]]` block (pxweb adapter, no new hosts needed —
  data.ssb.no already allowlisted), write the known-value ingest test against the fixture, then
  implement the fetch. Run: `uv run pytest tests/test_ingest.py -x` → green.

- [ ] **A3 — Per-kommune growth in analyze.** Failing test first: 3-kommune frame with distinct
  projected growth → `pop_80plus_growth_pct` must differ per kommune; second test: no projection
  rows for a kommune → falls back to national rate (existing chain national-derived → 3.5%).
  Implement in the `analyze.py:140-193` projection function: join per-kommune projection,
  compute `(proj_2035 / proj_baseline) ** (1/years) - 1` per kommune, fallback chain
  kommune → national → 3.5% constant. Add `growth_source` ("kommune" | "national" | "default")
  per row AND a top-level findings field `growth_method` — honesty surfaced in report.

- [ ] **A4 — Verify gate.** Verifier must independently recompute at least one per-kommune growth
  claim from raw projection data (not from analyze's intermediate). Extend the planted-fault
  test: corrupt one kommune's growth in findings → verify FAILS.

- [ ] **A5 — Commit** `git commit -m "G7-A: per-kommune 80+ projections, growth varies by kommune"`

## Task B — Choropleth (press-index map)

**Files:**
- Create: `src/omsorgsradar/maps.py`
- Create: `assets/geo/kommuner_simplified.geojson` (committed, one-time download)
- Create: `assets/geo/PROVENANCE.md` (source URL, date, license, simplification applied)
- Modify: `src/omsorgsradar/report.py` (one call: figure 4)
- Test: `tests/test_maps.py` (synthetic 3-polygon fixture)

**Constraints (lock these):**
- Boundary source: official Geonorge/Kartverket administrative kommune boundaries (CC BY 4.0 /
  NLOD — record exact license in PROVENANCE.md, cite in report figure caption). Use the
  *simplified/illustration* variant or simplify to **< 5 MB** before committing.
- **No geopandas/fiona/pyogrio.** Render with stdlib `json` + matplotlib `PolyCollection`
  (handle Polygon AND MultiPolygon). Pure-matplotlib is the point — pandas/matplotlib evidence,
  zero dep weight.
- Join on 4-digit kommune code (current codes, post-KLASS normalization). Kommuner missing from
  findings → grey + counted in caption ("N kommuner uten data").
- The GeoJSON is a committed asset: **no runtime fetch, no new allowlist hosts, CI-safe.**

**Steps:**

- [ ] **B1 — Failing test.** Synthetic GeoJSON fixture (3 fake kommune polygons, one MultiPolygon)
  + values for 2 of them → `render_choropleth(geojson_path, values: dict[str, float], out_png)`
  produces a PNG (magic-bytes check), greys the third, returns counts `{plotted: 2, missing: 1}`.
- [ ] **B2 — Implement `maps.py`.** PolyCollection, viridis-like colormap, colorbar labeled
  «Press-indeks», no axes ticks, figure caption text returned for report embedding.
- [ ] **B3 — Real boundary asset.** Download once from Geonorge, simplify if needed, commit +
  PROVENANCE.md. Spot-check: codes for Oslo (0301), Trondheim (5001), Hasvik (5616 — top press)
  present.
- [ ] **B4 — Wire into report.** `report.py` figure 4: choropleth of press_index. Skip gracefully
  with a logged warning if the asset is absent (report must still build), but the asset IS
  committed so the published report always has it.
- [ ] **B5 — Commit** `git commit -m "G7-B: press-index choropleth, pure matplotlib, committed Geonorge boundaries"`

## Task C — TabPFN actually runnable + honest ML reframe

**Files:**
- Modify: `src/omsorgsradar/ml.py` (`run_tabpfn_baseline`, `walk_forward_cv` wiring, summary md)
- Modify: `src/omsorgsradar/report.py` ML section text, `README.md` ML section, `COSTS.md`, `LIMITATIONS.md` ML section
- Test: `tests/test_ml.py` (stubbed `TabPFNRegressor`)

**Steps:**

- [ ] **C1 — Fold parity.** Failing test with monkeypatched `tabpfn.TabPFNRegressor` (deterministic
  stub): TabPFN runs the SAME 3 walk-forward folds as XGB (reuse the split logic — single-holdout
  comparison is not honest), per-fold `tabpfn_mae` lands in `CVFold` (fields exist, ml.py:61-62),
  `mean_tabpfn_mae` + `tabpfn_available=True` in `MLResults`.
- [ ] **C2 — License/status path.** When tabpfn import works but weights need the PriorLabs token:
  catch, return status `"krever TABPFN_TOKEN (priorlabs.ai) — ikke kjørt"` — NEVER the raw
  exception string into the report. Assert the token value itself can never appear in logs,
  journal, findings, or report (test greps artifacts for the env value with a planted fake token).
- [ ] **C3 — Honest reframe (text).** Report ML section + README: the finding IS that both a tuned
  GBM and (when run) a no-training tabular foundation model barely beat year-over-year
  persistence → kommunal dekning er sterkt autoregressiv; modellverdi ligger i avviks-flagging,
  ikke punktprediksjon. Update the stale "TabPFN-2.5 not run (interactive license)" wording:
  one-line owner instruction (sign up at priorlabs.ai → `export TABPFN_TOKEN=…` → re-run ml
  stage). COSTS.md TabPFN section same.
- [ ] **C4 — Commit** `git commit -m "G7-C: TabPFN fold-parallel behind TABPFN_TOKEN, honest persistence framing"`

## Task D — Single live re-run + docs truth pass (serial, after A–C merge)

- [ ] **D1 — Full live re-run** of `analyses/omsorgsradar` (corrected KLASS merger table now in
  effect for the FIRST time on v1 numbers + per-kommune growth + map). Verify gate green required.
  Expect Key-findings deltas (Hasvik/Bjerkreim/Tydal ranking may shift; national growth no longer
  one number per kommune).
- [ ] **D2 — README truth pass:** new Key findings + quality-profile counts from the re-run; delete
  the stale "(goes live once GitHub Pages is enabled…)" on line 3; ML table updated (TabPFN row =
  status or real MAE if owner has set token by then); architecture diagram unchanged.
- [ ] **D3 — LIMITATIONS truth pass:** rewrite §Kommunesammenslåinger (KLASS-regenerated, changes
  through 2024 covered, splits excluded by design — list what that means for Ålesund/Haram 2024);
  rewrite §Befolkningsframskrivinger per Task A outcome; drop §«Kartkoplinger (fremtidig
  arbeid)» — the map exists now; resolve the v1-tall §(2026-06-11) caveat — numbers are now
  regenerated, say so with date.
- [ ] **D4 — Site rebuild + push + live check:** `uv run python -m omsorgsradar.site --reports-dir
  reports --out site` locally, commit artifacts, push, Pages deploy green, spot-check live pages
  (map PNG present, no 11-digit numbers, no token).
- [ ] **D5 — Commit** per sub-step; status.md G7 close-out entry.

## Task E — FHI NOKKEL re-probe (timeboxed: ONE discovery session)

- [ ] Probe current FHI open-data API for the moved indikator endpoint. Wire in ONLY if it fits the
  existing adapter pattern with zero new code (a `[[sources]]` block); otherwise update
  `docs/api_drift.md` + LIMITATIONS §FHI NOKKEL with "re-checked 2026-06-12, still unavailable"
  and DELETE the dangling "Planlagt: integrering …" promise. Either outcome closes the item.

---

## Execution notes

- **Implementers:** 3 sonnet subagents in parallel for A, B, C (disjoint files; the only shared
  file is `report.py` — B adds figure-4 call, C edits ML-section text; different regions, B lands
  first, C rebases trivially). Then D+E serial (D is mostly running + docs — main loop can do it,
  no agent needed; E folds into the A implementer's brief or main loop).
- **Review panel (after A–C + D):** correctness (**opus**) — per-kommune growth math, verify
  independence, map join correctness, TabPFN fold parity; security (**opus**) — GeoJSON
  provenance/license, no new hosts, TABPFN_TOKEN never journaled/logged, live-site leak re-check;
  integration (**sonnet**) — deps unchanged (no geopandas!), config schema, test coverage, docs
  consistency. Any BLOCK → fix → re-review, cap 3 iterations.
- **Agent budget:** 3 implementers + 3 reviewers = 6 (≤10 ✓).
- **Quality gates:** `uv run pytest` (303 offline + new must be green), live verify gate green,
  Pages deploy green.
- **Owner action (non-blocking):** PriorLabs sign-up for `TABPFN_TOKEN` — code path ships tested
  against a stub regardless; real MAE lands whenever the token exists.
