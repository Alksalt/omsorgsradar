# docs/site.md — Kommunal Omsorgsradar report site

**Live URL:** https://alksalt.github.io/omsorgsradar/

## What the site is

The site is built by `omsorgsradar.site` (module `src/omsorgsradar/site.py`) from **committed
report artifacts only**. The builder walks `reports/` for `*_rapport.md` files and their sibling
`figures/*.png` images — nothing else is read or copied. Raw data (`data/cache/`, `*.duckdb`,
loose CSVs, microdata) is never touched by the builder.

CI never runs the pipeline. The site is purely a transform of committed markdown + figures into
HTML. This means the build is reproducible, has zero dependency on SSB/FHI APIs, and costs
no LLM calls.

## Interactive marimo notebook

The `notebooks/explore_nordisk.py` marimo notebook is exported to a **self-contained WASM
bundle** (`site/explore/index.html`) via `marimo export html-wasm`. It runs entirely in the
browser — no server, no backend. Aggregate data is inlined into the bundle; no row-level or
individual data is present.

## Publishing a new or updated analysis

1. Run the analysis pipeline locally:
   ```bash
   uv run python -m omsorgsradar.pipeline analyses/<name> \
       --data-dir data/<name> --reports-dir reports/<name>
   ```
2. Commit the output artifacts:
   ```bash
   git add reports/<name>/
   git commit -m "chore: publish <name> report vX"
   git push
   ```
3. GitHub Actions rebuilds and redeploys the site automatically. No manual site build step.

## What is NOT on the site

- Raw data files (`data/`, `data/cache/`, `*.duckdb`)
- Microdata or any row-level records
- Pipeline logs or run journals (`runs/`)
- Findings JSON or quality profile JSON (these are pipeline intermediates, not site artifacts)

## CI workflow summary

File: `.github/workflows/pages.yml`

| Job | Runs on | Steps |
|-----|---------|-------|
| `build` | ubuntu-latest | checkout → `uv sync --frozen` → `python -m omsorgsradar.site` → upload Pages artifact |
| `deploy` | ubuntu-latest | deploy artifact to GitHub Pages |

Permissions are least-privilege: `contents: read`, `pages: write`, `id-token: write`. No
secrets are used. The build fails loudly if the marimo export fails (dead "Utforsk" links are
never silently shipped).
