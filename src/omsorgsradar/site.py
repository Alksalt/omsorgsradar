"""Static site builder — publishes committed report artifacts to GitHub Pages.

SECURITY INVARIANT: only `*_rapport.md` report files and their sibling
`figures/*.png` images are read or copied into the site. Raw data is never
touched — `data/cache`, `*/microdata`, `*.duckdb`, and loose CSVs are not
discoverable by this builder (it walks for report markdown, not for data).
CI builds the site from committed artifacts only; it never runs the pipeline.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import markdown as md
import nh3
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).parent / "templates"
_REPORT_GLOB = "*_rapport.md"
SITE_TITLE = "Kommunal Omsorgsradar"
SITE_INTRO = (
    "Agentisk dataanalyse over åpne nordiske helsedata. Hver rapport er generert "
    "av en deterministisk pipeline og kontrollregnet av en uavhengig verifiseringsmodul "
    "(«tool receipts») før publisering. "
    "De to norske analysene bruker ulike tidsvinduer og metoder, og rangerer derfor "
    "kommuner ulikt — med vilje."
)

# Allowed HTML tags and attributes for the nh3 sanitizer
_ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "p", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "blockquote", "code", "pre", "em", "strong", "a", "img",
    "hr", "br",
}
_ALLOWED_ATTRS = {"a": {"href"}, "img": {"src", "alt"}}
_ALLOWED_URL_SCHEMES = {"https", "http"}

# Card order for the index page: lower number = earlier in the list.
# Unknown slugs sort last (fallback = 99), then alphabetically.
_SLUG_PRIORITY: dict[str, int] = {
    "omsorgsradar": 0,
    "nordisk-omsorg": 1,
    "brfss-demo": 2,
}

# One-line method/window descriptor per analysis, shown on the landing card.
# Bokmål. Drives the landing-page reconciliation sentence (N4).
_SLUG_DESCRIPTOR: dict[str, str] = {
    "omsorgsradar": "Trendframskriving 2017→2035 · press-indeks",
    "nordisk-omsorg": "Historisk 2019–2023 · z-skår innen land — sammenlignbar på tvers av Norden",
    "brfss-demo": "Anonymiseringsdemo · syntetiske mikrodata",
}

_MD_HEADING_RE = re.compile(r"^#{1,6}\s+")
_MD_IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_BOLD_RE = re.compile(r"\*{1,2}([^*]*)\*{1,2}")


def _first_paragraph(text: str, max_len: int = 160) -> str:
    """Return the first non-empty, non-heading paragraph, stripped of markdown,
    truncated to max_len characters."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _MD_HEADING_RE.match(stripped):
            continue
        # Strip images, links, bold/italic markers
        stripped = _MD_IMAGE_RE.sub("", stripped)
        stripped = _MD_LINK_RE.sub(r"\1", stripped)
        stripped = _MD_BOLD_RE.sub(r"\1", stripped)
        stripped = stripped.strip("*_ `").strip()
        if not stripped:
            continue
        if len(stripped) > max_len:
            stripped = stripped[:max_len].rsplit(" ", 1)[0] + "…"
        return stripped
    return ""


@dataclass(frozen=True)
class ReportDoc:
    slug: str
    title: str
    summary: str
    md_path: Path
    figures_dir: Path | None


def discover_reports(reports_dir: Path) -> list[ReportDoc]:
    """Find every `*_rapport.md` under reports_dir (recursive). Each report's
    figures are the `figures/` dir SIBLING to its markdown file, if present.

    DEFENSIVE: if more than one `*_rapport.md` shares the same parent dir,
    no figures/ is attached to any of them — a shared figures/ must never
    be cross-published to a sibling report's page.
    """
    reports_dir = Path(reports_dir)
    docs: list[ReportDoc] = []

    # Collect all report paths grouped by parent dir
    by_parent: dict[Path, list[Path]] = {}
    for md_path in sorted(reports_dir.rglob(_REPORT_GLOB)):
        by_parent.setdefault(md_path.parent, []).append(md_path)

    for parent, paths in sorted(by_parent.items()):
        # If multiple reports share a parent, figures/ is ambiguous — skip it for all
        shared_parent = len(paths) > 1
        fig_candidate = parent / "figures"
        for md_path in paths:
            slug = md_path.stem.replace("_rapport", "")
            text = md_path.read_text(encoding="utf-8")
            lines = text.splitlines()
            first_line = lines[0] if lines else slug
            title = first_line.lstrip("# ").strip() or slug
            summary = _first_paragraph(text)
            if shared_parent:
                # Co-located reports: no figures to avoid cross-publishing
                figures_dir = None
            else:
                figures_dir = fig_candidate if fig_candidate.is_dir() else None
            docs.append(ReportDoc(
                slug=slug,
                title=title,
                summary=summary,
                md_path=md_path,
                figures_dir=figures_dir,
            ))
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

        # Convert markdown → HTML → sanitize before rendering into template
        raw_html = converter.reset().convert(doc.md_path.read_text(encoding="utf-8"))
        html_body = nh3.clean(
            raw_html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            url_schemes=_ALLOWED_URL_SCHEMES,
        )

        # Copy ONLY real PNG figures — skip symlinked dirs, symlinked files, non-PNG
        if doc.figures_dir and not doc.figures_dir.is_symlink():
            (page_dir / "figures").mkdir(exist_ok=True)
            for png in sorted(doc.figures_dir.glob("*.png")):
                if png.is_symlink() or not png.is_file():
                    continue
                with png.open("rb") as fh:
                    if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                        continue
                shutil.copy2(png, page_dir / "figures" / png.name)

        (page_dir / "index.html").write_text(
            env.get_template("report.html.j2").render(
                title=doc.title, body=html_body, site_title=SITE_TITLE),
            encoding="utf-8")

    css_src = _TEMPLATES / "static" / "site.css"
    (out_dir / "static").mkdir(exist_ok=True)
    shutil.copy2(css_src, out_dir / "static" / "site.css")

    # Sort analyses: known slugs first (by priority map), then alphabetical
    def _sort_key(d: ReportDoc) -> tuple[int, str]:
        return (_SLUG_PRIORITY.get(d.slug, 99), d.slug)

    analyses = [
        {
            "slug": d.slug,
            "title": d.title,
            "summary": d.summary,
            "descriptor": _SLUG_DESCRIPTOR.get(d.slug, ""),
        }
        for d in sorted(docs, key=_sort_key)
    ]

    (out_dir / "index.html").write_text(
        env.get_template("index.html.j2").render(
            site_title=SITE_TITLE, intro=SITE_INTRO,
            analyses=analyses,
            marimo_embedded=marimo_embedded),
        encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    return out_dir


def export_marimo(notebook: Path | str, out_dir: Path | str) -> Path:
    """Export a marimo notebook to WASM HTML under out_dir/explore/.

    Runs from a clean temp dir containing ONLY a copy of the notebook so no
    stray repo files (CLAUDE.md, etc.) are bundled into the export.

    Raises RuntimeError loudly if the export fails — a dead 'Utforsk' link
    must never be silently shipped.
    """
    import subprocess
    import tempfile
    import shutil as _sh

    # Resolve to ABSOLUTE paths: the subprocess runs with cwd=td, so a relative
    # -o target (e.g. "site/explore") would be written INSIDE the temp dir and
    # vanish. (This was the CI failure: passed locally with an absolute --out,
    # failed with the workflow's relative `--out site`.)
    notebook = Path(notebook).resolve()
    target = (Path(out_dir) / "explore").resolve()
    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        nb_copy = Path(td) / notebook.name
        _sh.copy2(notebook, nb_copy)
        res = subprocess.run(
            ["marimo", "export", "html-wasm", str(nb_copy), "-o", str(target), "--mode", "run"],
            capture_output=True, text=True, cwd=td)

    # Belt: drop any stray non-asset markdown the exporter may still bundle
    for stray in ("CLAUDE.md", "AGENTS.md", "GEMINI.md"):
        (target / stray).unlink(missing_ok=True)

    index = target / "index.html"
    if res.returncode != 0 or not index.exists():
        raise RuntimeError(f"marimo wasm export failed: {res.stderr or res.stdout}")

    # Fix language attribute for Norwegian audience
    html = index.read_text(encoding="utf-8")
    html = html.replace('<html lang="en"', '<html lang="nb"', 1)
    index.write_text(html, encoding="utf-8")

    return target


def main() -> None:
    """Build the static site from committed report artifacts.

    Marimo export (--marimo flag): if the WASM export fails, the static site is
    NOT deleted — a placeholder explore/index.html is written instead, a loud
    stderr warning is printed, and the process exits 0 (static success).

    Design choice: publishing the static reports is the primary goal; losing the
    interactive explore page is a degraded experience, not a site failure. CI
    uploads whatever is in `site/`, so a failed marimo build should not block
    the reports from being deployed.
    """
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Build the static report site.")
    p.add_argument("--reports-dir", default="reports")
    p.add_argument("--out", default="site")
    p.add_argument("--marimo", default=None, metavar="NOTEBOOK",
                   help="Path to a marimo notebook to export as WASM into out/explore/")
    args = p.parse_args()
    out = build_site(args.reports_dir, args.out,
                     marimo_embedded=bool(args.marimo))
    if args.marimo:
        try:
            export_marimo(args.marimo, args.out)
        except Exception as exc:
            # N20: never rmtree the built site on marimo failure.
            # Write a placeholder so the explore/ link returns 200, not 404.
            explore_dir = out / "explore"
            explore_dir.mkdir(parents=True, exist_ok=True)
            (explore_dir / "index.html").write_text(
                "<!DOCTYPE html><html lang='nb'><head><meta charset='utf-8'>"
                "<title>Interaktiv utforsking</title></head><body>"
                "<p>Interaktiv utforsking er midlertidig utilgjengelig.</p>"
                "</body></html>",
                encoding="utf-8",
            )
            print(
                f"\nWARNING: marimo WASM export failed — static site is intact but "
                f"explore/ shows a placeholder.\nError: {exc}\n",
                file=sys.stderr,
            )
    print(f"site built: {out} ({len(discover_reports(Path(args.reports_dir)))} analyses)")


if __name__ == "__main__":
    main()
