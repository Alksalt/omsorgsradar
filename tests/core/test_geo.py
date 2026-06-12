"""Country-prefixed municipality ids: NO-1505, SE-0180, FI-091."""

import pytest

from omsorgsradar.core.geo import GeoError, make_geo_id, normalize_code, split_geo_id


class TestNormalizeCode:
    @pytest.mark.parametrize(
        ("country", "raw", "expected"),
        [
            ("NO", "1505", "1505"),   # Kristiansund
            ("NO", "301", "0301"),    # Oslo, zero-padded
            ("SE", "0180", "0180"),   # Stockholm
            ("SE", 180, "0180"),      # int from JSON survives
            ("FI", "091", "091"),     # Helsinki
            ("FI", "91", "091"),
            ("fi", "91", "091"),      # case-insensitive country
        ],
    )
    def test_known_values(self, country: str, raw, expected: str) -> None:
        assert normalize_code(country, raw) == expected

    @pytest.mark.parametrize(
        ("country", "raw"),
        [("NO", "12345"), ("NO", "12x5"), ("FI", "1234"), ("DK", "0101"), ("SE", "")],
    )
    def test_invalid_rejected(self, country: str, raw) -> None:
        with pytest.raises(GeoError):
            normalize_code(country, raw)


class TestGeoId:
    def test_make_and_split_round_trip(self) -> None:
        gid = make_geo_id("NO", "1505")
        assert gid == "NO-1505"
        assert split_geo_id(gid) == ("NO", "1505")
        assert make_geo_id("FI", "91") == "FI-091"
        assert make_geo_id("SE", 180) == "SE-0180"

    def test_split_rejects_garbage(self) -> None:
        for bad in ("NO1505", "XX-1505", "NO-15"):
            with pytest.raises(GeoError):
                split_geo_id(bad)
