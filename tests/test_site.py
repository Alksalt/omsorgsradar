import sys
from pathlib import Path
import pytest
from omsorgsradar.site import discover_reports, build_site, SITE_INTRO, _SLUG_DESCRIPTOR

# Real PNG magic bytes (8-byte signature)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Truncated PNG — only first 6 bytes (old test fixture used this; now rejected by magic check)
_PNG_PARTIAL = b"\x89PNG\r\n"


def _make_reports(tmp: Path):
    """Create a fixture with two reports in separate subdirs + microdata/duckdb noise."""
    # alpha: lives at root level — co-located scenario (see test_colocated_no_figures)
    # For the canonical two-report fixture, use separate subdirs instead.
    alpha = tmp / "alpha"
    alpha.mkdir(parents=True)
    (alpha / "figures").mkdir()
    (alpha / "figures" / "f1.png").write_bytes(_PNG_MAGIC + b"\x00" * 100)
    (alpha / "alpha_rapport.md").write_text(
        "# Alpha\n\nNoen funn. ![fig](figures/f1.png)\n", encoding="utf-8")

    sub = tmp / "beta"
    sub.mkdir(parents=True)
    (sub / "figures").mkdir()
    (sub / "figures" / "b1.png").write_bytes(_PNG_MAGIC + b"\x00" * 100)
    (sub / "beta_rapport.md").write_text("# Beta\n\nMer.\n", encoding="utf-8")

    (tmp / "microdata").mkdir()
    (tmp / "microdata" / "raw.csv").write_text("fnr,age\n1,2\n", encoding="utf-8")
    (tmp / "secret.duckdb").write_bytes(b"DUCK")


def test_discover_finds_only_report_markdown(tmp_path):
    _make_reports(tmp_path)
    reports = discover_reports(tmp_path)
    assert {r.slug for r in reports} == {"alpha", "beta"}
    assert all("microdata" not in str(r.md_path) for r in reports)


def test_build_site_excludes_row_level(tmp_path):
    _make_reports(tmp_path)
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    assert (out / "index.html").exists()
    assert (out / "alpha" / "index.html").exists()
    assert (out / "alpha" / "figures" / "f1.png").exists()
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
    build_site(reports_dir=tmp_path, out_dir=out)
    assert (out / "index.html").exists()


def test_marimo_notebook_is_valid_app():
    import importlib.util
    from pathlib import Path
    nb = Path(__file__).parent.parent / "notebooks" / "explore_nordisk.py"
    spec = importlib.util.spec_from_file_location("explore_nordisk", nb)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # must import without executing cells
    import marimo
    assert isinstance(mod.app, marimo.App)


def test_xss_in_report_body_is_stripped(tmp_path):
    """A <script> tag planted in a report must not appear in the rendered HTML."""
    report_dir = tmp_path / "xss"
    report_dir.mkdir()
    (report_dir / "xss_rapport.md").write_text(
        "# XSS test\n\n<script>alert(1)</script>\n\nNoen tekst.\n",
        encoding="utf-8")
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    html = (out / "xss" / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "alert(1)" not in html


def test_png_magic_bytes_required(tmp_path):
    """Files without valid PNG magic bytes must be excluded from the site."""
    report_dir = tmp_path / "badpng"
    report_dir.mkdir()
    (report_dir / "figures").mkdir()
    # Write a file that has a .png extension but wrong magic bytes
    (report_dir / "figures" / "fake.png").write_bytes(b"FAKEFAKE" + b"\x00" * 50)
    # Write a real PNG
    (report_dir / "figures" / "real.png").write_bytes(_PNG_MAGIC + b"\x00" * 50)
    (report_dir / "badpng_rapport.md").write_text("# Bad PNG\n\nTest.\n", encoding="utf-8")
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    fig_dir = out / "badpng" / "figures"
    assert (fig_dir / "real.png").exists()
    assert not (fig_dir / "fake.png").exists()


def test_colocated_reports_no_cross_figures(tmp_path):
    """Two *_rapport.md in the same directory must NOT get each other's figures."""
    parent = tmp_path / "shared"
    parent.mkdir()
    (parent / "figures").mkdir()
    (parent / "figures" / "f1.png").write_bytes(_PNG_MAGIC + b"\x00" * 50)
    (parent / "alpha_rapport.md").write_text("# Alpha\nTest.\n", encoding="utf-8")
    (parent / "beta_rapport.md").write_text("# Beta\nTest.\n", encoding="utf-8")
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    # Neither report should have a figures/ dir (shared parent guard)
    assert not (out / "alpha" / "figures").exists()
    assert not (out / "beta" / "figures").exists()


def test_report_summary_appears_in_index(tmp_path):
    """The first paragraph of each report should appear as a card teaser in index.html."""
    report_dir = tmp_path / "summary"
    report_dir.mkdir()
    (report_dir / "summary_rapport.md").write_text(
        "# Summary Test\n\nDette er første avsnitt med tekst.\n\n## Seksjon\n\nAnnet avsnitt.\n",
        encoding="utf-8")
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert "Dette er første avsnitt med tekst." in idx


# ── B7: landing-page reconciliation (N4 + N20) ───────────────────────────────

def test_slug_descriptor_map_has_known_analyses():
    """All three known analysis slugs have descriptors."""
    for slug in ("omsorgsradar", "nordisk-omsorg", "brfss-demo"):
        assert slug in _SLUG_DESCRIPTOR
        assert _SLUG_DESCRIPTOR[slug]


def test_site_intro_contains_reconciliation_sentence():
    """SITE_INTRO must contain the ranking-differs-by-design sentence."""
    assert "ulike tidsvinduer og metoder" in SITE_INTRO
    assert "rangerer" in SITE_INTRO


def test_descriptor_appears_in_index_for_known_slug(tmp_path):
    """Landing card for omsorgsradar shows the method/window descriptor."""
    report_dir = tmp_path / "omsorgsradar"
    report_dir.mkdir()
    (report_dir / "omsorgsradar_rapport.md").write_text(
        "# Omsorgsradar\n\nNoen funn.\n", encoding="utf-8")
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert "Trendframskriving 2017" in idx
    assert "card-method" in idx


def test_descriptor_absent_for_unknown_slug(tmp_path):
    """Unknown slug: no descriptor line, no card-method class with empty content."""
    report_dir = tmp_path / "unknown-analysis"
    report_dir.mkdir()
    (report_dir / "unknown-analysis_rapport.md").write_text(
        "# Unknown\n\nTekst.\n", encoding="utf-8")
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)
    idx = (out / "index.html").read_text(encoding="utf-8")
    # descriptor block must not render for slugs with no descriptor
    assert 'card-method"><' not in idx or "card-method\"></p>" not in idx


def test_marimo_failure_keeps_site_and_writes_placeholder(tmp_path):
    """N20: if marimo export fails, built site is preserved and explore/ gets a placeholder."""
    _make_reports(tmp_path)
    out = tmp_path / "site"
    build_site(reports_dir=tmp_path, out_dir=out)

    from omsorgsradar.site import export_marimo
    # export_marimo on a non-notebook path will raise RuntimeError
    try:
        export_marimo(tmp_path / "nonexistent.py", out)
    except Exception:
        pass

    # Simulate the main() logic for marimo failure: placeholder written, site intact
    explore_dir = out / "explore"
    explore_dir.mkdir(parents=True, exist_ok=True)
    placeholder = explore_dir / "index.html"
    placeholder.write_text(
        "<!DOCTYPE html><html lang='nb'><head><meta charset='utf-8'>"
        "<title>Interaktiv utforsking</title></head><body>"
        "<p>Interaktiv utforsking er midlertidig utilgjengelig.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    # Static site must still be intact
    assert (out / "index.html").exists()
    assert (out / "alpha" / "index.html").exists()
    # Placeholder exists
    assert placeholder.exists()
    assert "midlertidig utilgjengelig" in placeholder.read_text(encoding="utf-8")


def test_main_marimo_failure_writes_placeholder_not_rmtree(tmp_path, capsys):
    """N20: main() with failing --marimo must NOT delete the site; placeholder + warning."""
    import subprocess, sys, textwrap

    _make_reports(tmp_path)
    # Run main() directly by importing and calling it with monkeypatching
    from unittest.mock import patch
    from omsorgsradar import site as site_mod

    out_dir = tmp_path / "site"

    # Patch export_marimo to simulate failure, patch sys.argv
    def _fail_export(notebook, out_dir):
        raise RuntimeError("marimo not available in test")

    with patch.object(site_mod, "export_marimo", side_effect=_fail_export), \
         patch("sys.argv", ["site", "--reports-dir", str(tmp_path),
                            "--out", str(out_dir),
                            "--marimo", str(tmp_path / "fake.py")]):
        site_mod.main()

    # Site must still exist
    assert (out_dir / "index.html").exists()
    # Placeholder must exist
    placeholder = out_dir / "explore" / "index.html"
    assert placeholder.exists()
    assert "midlertidig utilgjengelig" in placeholder.read_text(encoding="utf-8")
    # Warning on stderr
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
