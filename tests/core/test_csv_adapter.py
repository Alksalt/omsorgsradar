"""Local-file CSV adapter."""

from pathlib import Path

import pytest

from omsorgsradar.core.adapters.csvfile import CsvAdapter


def write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestFetch:
    def test_reads_renames_and_types(self, tmp_path: Path) -> None:
        write_csv(tmp_path / "d.csv", "Kommun;År;Värde\n0180;2023;12,5\n1480;2023;9,0\n")
        source = {"adapter": "csv", "id": "se_csv", "path": "d.csv",
                  "sep": ";", "decimal": ",",
                  "rename": {"Kommun": "geo_code", "År": "aar", "Värde": "value"},
                  "provenance": {"institution": "Socialstyrelsen", "url": "https://x"}}
        df = CsvAdapter(base_dir=tmp_path).fetch(source)
        assert list(df.columns) == ["geo_code", "aar", "value"]
        assert df["value"].tolist() == [12.5, 9.0]

    def test_absolute_path_wins(self, tmp_path: Path) -> None:
        p = write_csv(tmp_path / "abs.csv", "a,b\n1,2\n")
        df = CsvAdapter(base_dir=tmp_path / "elsewhere").fetch(
            {"adapter": "csv", "id": "x", "path": str(p),
             "provenance": {"institution": "T", "url": "https://x"}})
        assert df["a"].tolist() == [1]

    def test_missing_file_raises_with_path(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="nope.csv"):
            CsvAdapter(base_dir=tmp_path).fetch(
                {"adapter": "csv", "id": "x", "path": "nope.csv",
                 "provenance": {"institution": "T", "url": "https://x"}})

    def test_keeps_leading_zeros_in_code_columns(self, tmp_path: Path) -> None:
        write_csv(tmp_path / "z.csv", "geo_code,value\n0180,1\n")
        df = CsvAdapter(base_dir=tmp_path).fetch(
            {"adapter": "csv", "id": "x", "path": "z.csv",
             "dtype": {"geo_code": "str"},
             "provenance": {"institution": "T", "url": "https://x"}})
        assert df["geo_code"].tolist() == ["0180"]
