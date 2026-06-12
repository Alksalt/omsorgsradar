"""Pointer classification for /magic-analyze — pure, no network."""

from pathlib import Path

from omsorgsradar.core.discovery import HOST_ADAPTERS, Pointer, classify_pointer


class TestClassifyPointer:
    def test_known_api_urls_map_to_adapters(self) -> None:
        cases = {
            "https://data.ssb.no/api/v0/no/table/12209": "pxweb",
            "https://api.scb.se/OV0104/v1/doris/sv/ssd/START/BE": "pxweb",
            "https://sotkanet.fi/rest/1.1/json?indicator=127": "sotkanet",
            "https://api.kolada.se/v3/data/kpi/N21704/year/2023": "kolada",
            "https://sdb.socialstyrelsen.se/api/v1/sv/amning": "socialstyrelsen",
            "https://opne-data-api.helserefusjon.no/v1/fagomraader": "kuhr",
        }
        for url, adapter in cases.items():
            p = classify_pointer(url)
            assert p == Pointer("url", adapter, p.host), url

    def test_unknown_api_url(self) -> None:
        p = classify_pointer("https://opendata.nhsbsa.net/api/3/action/datastore_search")
        assert p.kind == "url" and p.adapter is None
        assert p.host == "opendata.nhsbsa.net"

    def test_csv_extension_is_file(self) -> None:
        assert classify_pointer("nedlastet/data.csv") == Pointer("file", "csv", None)

    def test_existing_file_is_file(self, tmp_path: Path) -> None:
        f = tmp_path / "dump.txt"
        f.write_text("x")
        assert classify_pointer(str(f)) == Pointer("file", "csv", None)

    def test_relative_existing_file_with_base_dir(self, tmp_path: Path) -> None:
        (tmp_path / "d.parquet").write_text("x")
        p = classify_pointer("d.parquet", base_dir=tmp_path)
        assert p.kind == "file"

    def test_free_text_is_question(self) -> None:
        p = classify_pointer("hvilke kommuner har flest fastlegebytter?")
        assert p == Pointer("question", None, None)

    def test_host_adapters_consistent_with_allowlist(self) -> None:
        from omsorgsradar.core.adapters import ALLOWED_BASE_URL_HOSTS
        assert set(HOST_ADAPTERS) <= set(ALLOWED_BASE_URL_HOSTS)
