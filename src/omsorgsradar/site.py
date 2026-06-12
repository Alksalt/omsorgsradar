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
        lines = md_path.read_text(encoding="utf-8").splitlines()
        first_line = lines[0] if lines else slug
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

    css_src = _TEMPLATES / "static" / "site.css"
    (out_dir / "static").mkdir(exist_ok=True)
    shutil.copy2(css_src, out_dir / "static" / "site.css")

    (out_dir / "index.html").write_text(
        env.get_template("index.html.j2").render(
            site_title=SITE_TITLE, intro=SITE_INTRO,
            analyses=[{"slug": d.slug, "title": d.title} for d in docs],
            marimo_embedded=marimo_embedded),
        encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
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
