from pathlib import Path
import pytest
from omsorgsradar.site import discover_reports, build_site

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
