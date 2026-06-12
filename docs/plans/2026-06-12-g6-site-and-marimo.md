# G6 — Report Site + marimo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Sonnet implementers; **scaled independent review panel (6 agents, parallel) at phase close** (owner request: 3–8 agents).

**Goal:** Produce the single employer-clickable artifact: a static GitHub Pages site that publishes every analysis's bokmål report + figures + tool-receipt metadata, plus one interactive **marimo** (WASM, in-browser) exploration — built deterministically from committed report artifacts, deployed by GitHub Actions on push, and provably carrying **no row-level data, no PII, no secrets**.

**Architecture:** A standalone `omsorgsradar.site` builder transforms *committed* report markdown + figures into static HTML (Jinja2 + plain CSS, no JS framework) via an explicit **allowlist** — it never walks `data/cache`, `*/microdata`, `*.duckdb`, or raw CSVs. CI does **not** run the pipeline (no live SSB/Sotkanet fetch, fully reproducible); it builds the site from what's in the repo and deploys. One marimo notebook is exported to self-contained WASM (no runtime network, reads only a bundled aggregate) and embedded. This decouples publishing from running: you run a pipeline locally, commit its report, push, CI publishes.

**Tech Stack:** Python via `uv`; `jinja2` (present) + `markdown` (new, md→HTML) + `marimo` (new, WASM export); GitHub Actions Pages deploy. No JS framework.

---

## Context (what exists)

- Committed reports: `reports/omsorgsradar_rapport.md` (+ `reports/figures/*.png`), `reports/nordisk-omsorg/nordisk-omsorg_rapport.md` (+ `reports/nordisk-omsorg/figures/*.png`). The `brfss-demo` report is NOT yet committed (Task 2 commits it — it is offline-runnable).
- The report markdown already embeds the tool receipts in prose (verification verdict, quality/realness, WP216 identifiability for brfss). So md→HTML preserves the "receipts" story without separately wiring metadata JSON.
- No `.github/workflows`. `jinja2 3.1.6` installed; `marimo`/`markdown` not.
- Repo: `github.com/Alksalt/omsorgsradar` → Pages URL `https://alksalt.github.io/omsorgsradar/`.
- Hard constraint (`DECISIONS.md`): row-level data never leaves the engine; the public site must carry only aggregates/reports/figures.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | add `marimo`, `markdown` |
| `src/omsorgsradar/site.py` | site builder: discover reports (allowlist) → render HTML → copy figures → index; `build_site()` + CLI |
| `src/omsorgsradar/templates/index.html.j2` | landing page (analyses grid, intro, links) |
| `src/omsorgsradar/templates/report.html.j2` | per-analysis page (rendered md + figures + back-link) |
| `src/omsorgsradar/templates/static/site.css` | plain CSS (no framework) |
| `notebooks/explore_nordisk.py` | marimo notebook — interactive Nordic squeeze exploration, self-contained |
| `.github/workflows/pages.yml` | build site + marimo WASM, deploy to Pages on push to main |
| `reports/brfss-demo_rapport.md` (+ figures) | committed brfss-demo report so the site has all three analyses |
| `README.md` / `LIMITATIONS.md` / `COSTS.md` | site link + final v2 polish |
| `docs/site.md` | how the site is built/deployed; Pages-enable step |
| `tests/test_site.py` | builder: allowlist excludes row-level, figures copied, index links, empty-input handling |

---

### Task 1: `site.py` builder (deterministic, allowlist-only)

**Files:**
- Modify: `pyproject.toml`
- Create: `src/omsorgsradar/site.py`, `src/omsorgsradar/templates/{index.html.j2,report.html.j2,static/site.css}`
- Test: `tests/test_site.py`

- [ ] **Step 1: Add deps**

```bash
uv add marimo markdown
uv run pytest -q   # expect 294 passed, 5 deselected — no regression
```

- [ ] **Step 2: Write failing tests** (`tests/test_site.py`)

```python
from pathlib import Path
import pytest
from omsorgsradar.site import discover_reports, build_site


def _make_reports(tmp: Path):
    (tmp / "figures").mkdir(parents=True)
    (tmp / "figures" / "f1.png").write_bytes(b"\x89PNG\r\n")
    (tmp / "alpha_rapport.md").write_text(
        "# Alpha\n\nNoen funn. ![fig](figures/f1.png)\n", encoding="utf-8")
    sub = tmp / "beta"
    (sub / "figures").mkdir(parents=True)
    (sub / "figures" / "b1.png").write_bytes(b"\x89PNG\r\n")
    (sub / "beta_rapport.md").write_text("# Beta\n\nMer.\n", encoding="utf-8")
    # row-level decoys that MUST be excluded:
    (tmp / "microdata").mkdir()
    (tmp / "microdata" / "raw.csv").write_text("fnr,age\n1,2\n", encoding="utf-8")
    (tmp / "secret.duckdb").write_bytes(b"DUCK")


def test_discover_finds_only_report_markdown(tmp_path):
    _make_reports(tmp_path)
    reports = discover_reports(tmp_path)
    slugs = {r.slug for r in reports}
    assert slugs == {"alpha", "beta"}
    # never surfaces microdata/duckdb
    assert all("microdata" not in str(r.md_path) for r in reports)


def test_build_site_excludes_row_level(tmp_path):
    _make_reports(tmp_path)
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    assert (out / "index.html").exists()
    assert (out / "alpha" / "index.html").exists()
    assert (out / "alpha" / "figures" / "f1.png").exists()
    # the whole tree must contain NO raw csv / duckdb / fnr
    all_text = "".join(p.read_text(errors="ignore")
                       for p in out.rglob("*") if p.is_file() and p.suffix in {".html", ".css"})
    assert "fnr" not in all_text
    assert not list(out.rglob("*.duckdb"))
    assert not list(out.rglob("raw.csv"))


def test_index_links_each_analysis(tmp_path):
    _make_reports(tmp_path)
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="alpha/' in idx and 'href="beta/' in idx


def test_empty_reports_dir_produces_index_not_crash(tmp_path):
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)        # no reports
    assert (out / "index.html").exists()                 # empty-but-valid landing page
```

- [ ] **Step 3: Run to confirm failure.**

- [ ] **Step 4: Implement `site.py`** (allowlist discovery + Jinja2 render). Key invariant: only `*_rapport.md` files and their sibling `figures/*.png` are ever read or copied — nothing else.

```python
"""Static site builder — publishes committed report artifacts to GitHub Pages.

SECURITY INVARIANT: only `*_rapport.md` report files and their sibling
`figures/*.png` images are read or copied into the site. Raw data is never
touched — `data/cache`, `*/microdata`, `*.duckdb`, and loose CSVs are not
discoverable by this builder (it walks for report markdown, not for data).
CI builds the site from committed artifacts only; it never runs the pipeline.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).parent / "templates"
_REPORT_GLOB = "*_rapport.md"
SITE_TITLE = "Kommunal Omsorgsradar"
SITE_INTRO = (
    "Agentisk dataanalyse over åpne nordiske helsedata. Hver rapport er generert "
    "av en deterministisk pipeline og kontrollregnet av en uavhengig verifiseringsmodul "
    "(«tool receipts») før publisering."
)


@dataclass(frozen=True)
class ReportDoc:
    slug: str
    title: str
    md_path: Path
    figures_dir: Path | None


def discover_reports(reports_dir: Path) -> list[ReportDoc]:
    """Find every `*_rapport.md` under reports_dir (recursive). Each report's
    figures are the `figures/` dir SIBLING to its markdown file, if present."""
    reports_dir = Path(reports_dir)
    docs: list[ReportDoc] = []
    for md_path in sorted(reports_dir.rglob(_REPORT_GLOB)):
        slug = md_path.stem.replace("_rapport", "")
        first_line = md_path.read_text(encoding="utf-8").splitlines()[0]
        title = first_line.lstrip("# ").strip() or slug
        fig = md_path.parent / "figures"
        docs.append(ReportDoc(slug=slug, title=title, md_path=md_path,
                              figures_dir=fig if fig.is_dir() else None))
    return docs


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                       autoescape=select_autoescape(["html"]))


def build_site(reports_dir: Path | str, out_dir: Path | str,
               *, marimo_embedded: bool = False) -> Path:
    """Render all discovered reports + an index into out_dir. Returns out_dir."""
    reports_dir, out_dir = Path(reports_dir), Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    env = _env()
    docs = discover_reports(reports_dir)

    converter = md.Markdown(extensions=["tables", "fenced_code", "toc"])
    for doc in docs:
        page_dir = out_dir / doc.slug
        page_dir.mkdir(parents=True, exist_ok=True)
        html_body = converter.reset().convert(doc.md_path.read_text(encoding="utf-8"))
        if doc.figures_dir:                       # copy ONLY png figures, nothing else
            (page_dir / "figures").mkdir(exist_ok=True)
            for png in sorted(doc.figures_dir.glob("*.png")):
                shutil.copy2(png, page_dir / "figures" / png.name)
        (page_dir / "index.html").write_text(
            env.get_template("report.html.j2").render(
                title=doc.title, body=html_body, site_title=SITE_TITLE),
            encoding="utf-8")

    # static assets
    css_src = _TEMPLATES / "static" / "site.css"
    (out_dir / "static").mkdir(exist_ok=True)
    shutil.copy2(css_src, out_dir / "static" / "site.css")

    (out_dir / "index.html").write_text(
        env.get_template("index.html.j2").render(
            site_title=SITE_TITLE, intro=SITE_INTRO,
            analyses=[{"slug": d.slug, "title": d.title} for d in docs],
            marimo_embedded=marimo_embedded),
        encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")  # serve _-prefixed paths
    return out_dir


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Build the static report site.")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--out", default="site")
    args = p.parse_args()
    out = build_site(args.reports_dir, args.out)
    print(f"site built: {out} ({len(discover_reports(Path(args.reports_dir)))} analyses)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Templates** — `index.html.j2` (header + intro + a grid of analysis cards linking `<slug>/`, + an "Utforsk interaktivt" link to `explore/` when `marimo_embedded`), `report.html.j2` (header, `{{ body|safe }}`, back-link to `../`), `static/site.css` (clean, readable, mobile-friendly, no framework). All link CSS as `../static/site.css` (report pages) / `static/site.css` (index). Keep bokmål UI text.

- [ ] **Step 6: Run** `uv run pytest tests/test_site.py -v` → PASS. Then full suite.

- [ ] **Step 7: Commit** — `git add -A && git commit -m "G6: static site builder (allowlist-only, row-level data excluded)"`

---

### Task 2: marimo notebook + WASM export + brfss report

**Files:**
- Create: `notebooks/explore_nordisk.py`
- Modify: `src/omsorgsradar/site.py` (add `export_marimo()`)
- Create: `reports/brfss-demo_rapport.md` (+ `reports/brfss-demo/figures/` if any) — committed offline run
- Test: extend `tests/test_site.py`

- [ ] **Step 1: Commit the brfss-demo report** so the site publishes all three analyses:

```bash
uv run python -m omsorgsradar.pipeline analyses/brfss-demo --data-dir /tmp/brfsspub --reports-dir reports
# moves reports/brfss-demo_rapport.md into the repo. Confirm NO microdata/csv landed in reports/.
git add reports/brfss-demo_rapport.md
```
Verify (security): `reports/` contains only `*.md` + `figures/*.png` — no csv/duckdb.

- [ ] **Step 2: Write the marimo notebook** `notebooks/explore_nordisk.py`. It must be **self-contained for WASM** — embed the aggregate data inline (a small CSV string built from `data/nordisk-omsorg/nordic_table.csv`, columns `country,geo_id,geo_name,coverage,growth_pct,squeeze,rank`) so the exported WASM does **no runtime network fetch and reads no local file**. Interactive: a country dropdown (`mo.ui.dropdown`) → filtered, sorted table (`mo.ui.table`) + a coverage-vs-growth scatter (matplotlib). Pure aggregate, no row-level data.

```python
import marimo
app = marimo.App(width="medium")

@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import io
    # Inline aggregate (Nordic squeeze table) — self-contained, no network in WASM.
    DATA = """country,geo_name,coverage,growth_pct,squeeze,rank
NO,<filled by build from nordic_table.csv>,...
"""
    df = pd.read_csv(io.StringIO(DATA))
    return mo, pd, df

@app.cell
def _(mo, df):
    land = mo.ui.dropdown(options=sorted(df["country"].unique()), value="NO", label="Land")
    land
    return (land,)

@app.cell
def _(mo, df, land):
    sub = df[df["country"] == land.value].sort_values("squeeze", ascending=False)
    mo.ui.table(sub, selection=None)
    return (sub,)

@app.cell
def _(sub):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(sub["coverage"], sub["growth_pct"], s=14, alpha=0.6)
    ax.set_xlabel("Dekning hjemmetjeneste (%)"); ax.set_ylabel("Vekst eldre (%)")
    ax.set_title(f"Skvis — {sub['country'].iloc[0] if len(sub) else ''}")
    fig
    return

if __name__ == "__main__":
    app.run()
```
The implementer fills `DATA` by reading `data/nordisk-omsorg/nordic_table.csv`, taking the needed columns, rounding, and embedding (cap to a sane row count if huge). If that CSV is absent, generate a tiny representative inline sample and document it — the notebook is a UI demo, not the source of truth (the reports are).

- [ ] **Step 3: Add `export_marimo()` to `site.py`** — runs `marimo export html-wasm notebooks/explore_nordisk.py -o <out>/explore --mode run` via `subprocess`, and sets `marimo_embedded=True`. It must **fail loudly** (raise) if the export errors or produces no `index.html` — never silently ship a site with a dead "Utforsk" link.

```python
def export_marimo(notebook: Path, out_dir: Path) -> Path:
    import subprocess
    target = Path(out_dir) / "explore"
    target.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["marimo", "export", "html-wasm", str(notebook), "-o", str(target), "--mode", "run"],
        capture_output=True, text=True)
    index = target / "index.html"
    if res.returncode != 0 or not index.exists():
        raise RuntimeError(f"marimo wasm export failed: {res.stderr or res.stdout}")
    return target
```
Wire an optional `--marimo notebooks/explore_nordisk.py` flag into `main()` that calls `export_marimo` then `build_site(..., marimo_embedded=True)`.

- [ ] **Step 4: Smoke test the export locally** (NOT in the core pytest suite — it is heavy):

```bash
uv run marimo export html-wasm notebooks/explore_nordisk.py -o /tmp/exp --mode run && ls /tmp/exp/index.html
```
Expected: exits 0, `index.html` exists. If `--mode run` is unsupported by the installed marimo, use the version's correct flag (check `uv run marimo export html-wasm --help`) and update the command + `export_marimo`.

- [ ] **Step 5: Add a light test** to `tests/test_site.py` that `notebooks/explore_nordisk.py` is importable as a marimo app (`import marimo; app = ...`) without executing cells — keeps the core suite fast, leaves the heavy WASM export to the build/CI.

- [ ] **Step 6: Run** full suite → green. **Commit** — `git add -A && git commit -m "G6: marimo WASM exploration + brfss-demo report published to site"`

---

### Task 3: GitHub Pages workflow + README/docs polish

**Files:**
- Create: `.github/workflows/pages.yml`, `docs/site.md`
- Modify: `README.md`, `LIMITATIONS.md`, `COSTS.md`

- [ ] **Step 1: `.github/workflows/pages.yml`** — least-privilege, builds from committed artifacts (no pipeline run, no secrets):

```yaml
name: Deploy report site to Pages
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - name: Build site (+ marimo WASM)
        run: uv run python -m omsorgsradar.site --reports-dir reports --out site --marimo notebooks/explore_nordisk.py
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```
(Confirm `--marimo` is the flag implemented in Task 2 `main()`. If `uv sync --frozen` needs the lockfile current, ensure `uv.lock` is committed.)

- [ ] **Step 2: `docs/site.md`** — how the site builds (allowlist, committed-artifacts-only, no pipeline in CI), the marimo WASM piece, and the **one owner step**: enable Pages in repo Settings → Pages → Source = "GitHub Actions". Note the URL `https://alksalt.github.io/omsorgsradar/`.

- [ ] **Step 3: README polish** — add the live-site link near the top, a short "Live report site" section, and confirm the v2 story (deterministic engine + agentic shell; G0–G6; tool receipts; anonymize; execution modes) reads coherently for a non-technical Norwegian e-helse employer. `LIMITATIONS.md` — note the site shows only aggregates/reports (no row-level data) and is rebuilt on push. `COSTS.md` — Pages + CI build is free (GitHub-hosted, no LLM in CI).

- [ ] **Step 4: Run** the full suite + `uv run python -m omsorgsradar.site --reports-dir reports --out /tmp/site_smoke` and confirm `index.html` + all three analysis pages exist. **Commit** — `git add -A && git commit -m "G6: Pages workflow + site docs + README/LIMITATIONS/COSTS polish"`

---

## Closing review panel — 6 independent agents, parallel (owner request: 3–8)

Run after Task 3. All read-only, dispatched in one batch:

1. **blast-radius-mapper (opus)** — what the new deps (marimo/markdown) + builder + workflow touch; any caller/import affected.
2. **security-reviewer (opus)** — **the published site carries no row-level data, no PII, no secrets**: builder allowlist can't be tricked into copying `microdata`/`*.duckdb`/raw CSV; the committed `brfss-demo` report + marimo inline data are aggregate-only (no fnr, no microdata rows); workflow permissions are least-privilege (`pages: write`, `id-token: write`, `contents: read`) with no secrets; marimo is exported to **static WASM** (no live marimo edit-server on Pages — cf. the marimo-server compromise advisory); `.nojekyll`/path handling introduces no traversal.
3. **correctness-reviewer (opus)** — md→HTML renders each report faithfully (tables, figures, links resolve); numbers on the site match the source report artifacts (builder transforms, never re-derives); index links every analysis; marimo notebook computes correctly from the aggregate.
4. **integration-reviewer (sonnet)** — deps declared + lockfile current for `uv sync --frozen`; workflow YAML valid + action versions exist; builder CLI flags match the workflow invocation; `--mode run`/export flag correct for the installed marimo; tests green; no broken imports.
5. **silent-failure-hunter (sonnet)** — missing figures, an empty report, or a failed marimo export must NOT silently yield a broken/empty/partial site; `export_marimo` raises on failure; the builder handles a report with no `figures/` dir; CI fails (not green-with-broken-site) if the build errors.
6. **Content/UX reviewer (general-purpose, sonnet)** — read the built site **as a non-technical Norwegian kommunehelsesjef / e-helse employer**: is the landing page legible, is the elder-care question obvious, do the bokmål reports read professionally, is the "verified numbers / målt restrisiko" trust story visible, are there embarrassing rough edges? Returns concrete copy/layout fixes only.

Any BLOCK → fix + re-review the blocking dimension (cap 3). Then push to `main` (triggers the Pages deploy). After deploy, verify the live URL renders and send the owner the link + a screenshot.

## Self-review (writing-plans checklist)

- **Spec coverage:** GitHub Pages static site (Jinja2, no JS framework) ✓ (Task 1) · figures + bokmål reports + receipts ✓ (md already embeds receipts) · GitHub Action deploy on push ✓ (Task 3) · "one link for employers" ✓ (index) · marimo artifacts ✓ (Task 2, WASM) · README/LIMITATIONS/COSTS ✓ (Task 3) · row-level-never-published ✓ (allowlist builder + security panel).
- **Placeholder scan:** the notebook's `DATA` block is an explicit `<filled by build…>` directive with a concrete fallback rule, not a silent TODO — the implementer fills it from `nordic_table.csv`. No other placeholders.
- **Type consistency:** `discover_reports → list[ReportDoc]`, `build_site(reports_dir, out_dir, marimo_embedded)`, `export_marimo(notebook, out_dir)` used identically across Tasks 1–3, the tests, and the workflow `--marimo` flag.
- **Deviation noted:** the spec says "report stage renders site/"; this plan instead builds the site as a standalone aggregator of committed artifacts (cleaner: publishes multiple analyses, keeps CI pipeline-free and reproducible). Recorded in `docs/site.md` + DECISIONS on execution.
