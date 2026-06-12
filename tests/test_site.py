from pathlib import Path
import pytest
from omsorgsradar.site import discover_reports, build_site


def _make_reports(tmp: Path):
    (tmp / "figures").mkdir(parents=True)
    (tmp / "figures" / "f1.png").write_bytes(b"\x89PNG\r\n")
    (tmp / "alpha_rapport.md").write_text(
        "# Alpha\n\nNoen funn. ![fig](figures/f1.png)\n", encoding="utf-8")
    sub = tmp / "beta"
    sub.mkdir(parents=True)
    (sub / "figures").mkdir(parents=True)
    (sub / "figures" / "b1.png").write_bytes(b"\x89PNG\r\n")
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
