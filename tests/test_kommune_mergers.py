"""Tests for the kommune merger lookup table."""

import pytest
from omsorgsradar.kommune_mergers import (
    normalize_knr,
    normalize_knr_series,
    MERGER_LOOKUP,
    REVERSE_MERGER_LOOKUP,
)
import pandas as pd


class TestNormalizeKnr:
    """Tests for normalize_knr scalar function."""

    def test_passthrough_for_current_knr(self) -> None:
        """Known current municipality numbers are returned unchanged."""
        assert normalize_knr("0301") == "0301"  # Oslo

    def test_molde_merger_2020(self) -> None:
        """Old Molde communes (1502, 1504, 1563) map to new 1506."""
        assert normalize_knr("1502") == "1506"
        assert normalize_knr("1504") == "1506"
        assert normalize_knr("1563") == "1506"

    def test_alesund_merger_2020(self) -> None:
        """Old Ålesund (1501) and absorbed communes map to 1507."""
        assert normalize_knr("1501") == "1507"
        assert normalize_knr("1523") == "1507"

    def test_trondheim_renumbering(self) -> None:
        """Old 1601 → 5001 (Trondheim renumbering in 2020)."""
        assert normalize_knr("1601") == "5001"

    def test_bergen_renumbering(self) -> None:
        """Old 1201 → 4601 (Bergen renumbering in 2020)."""
        assert normalize_knr("1201") == "4601"

    def test_zero_padded_input(self) -> None:
        """Input without leading zeros is handled correctly."""
        assert normalize_knr("301") == "0301"

    def test_unknown_knr_passthrough(self) -> None:
        """An unknown 4-digit code is returned as-is."""
        assert normalize_knr("9999") == "9999"

    def test_asker_merger(self) -> None:
        """Old Asker communes merge to 3025."""
        assert normalize_knr("0220") == "3025"
        assert normalize_knr("0226") == "3025"

    def test_kristiansand_merger(self) -> None:
        """Kristiansand merger 1001+1002+1014 → 4204."""
        assert normalize_knr("1001") == "4204"
        assert normalize_knr("1002") == "4204"


class TestNormalizeKnrSeries:
    """Tests for the vectorized pandas Series normalizer."""

    def test_series_normalisation(self) -> None:
        """Series with mixed old/new codes is normalized correctly."""
        s = pd.Series(["1502", "0301", "1601", "9999"])
        result = normalize_knr_series(s)
        assert result.tolist() == ["1506", "0301", "5001", "9999"]

    def test_series_with_integers(self) -> None:
        """Integer-valued series is handled without error."""
        s = pd.Series([1502, 301, 1601])
        result = normalize_knr_series(s)
        assert result.tolist() == ["1506", "0301", "5001"]


class TestMergerLookupIntegrity:
    """Structural integrity of the merger lookup table."""

    def test_no_self_referential_entries(self) -> None:
        """No old code maps to itself (would indicate a data error)."""
        for old, new in MERGER_LOOKUP.items():
            assert old != new, f"{old} maps to itself"

    def test_all_keys_are_4_digits(self) -> None:
        """All old codes are 4-digit zero-padded strings."""
        for k in MERGER_LOOKUP:
            assert len(k) == 4 and k.isdigit(), f"Invalid key: {k}"

    def test_all_values_are_4_digits(self) -> None:
        """All new codes are 4-digit zero-padded strings."""
        for v in MERGER_LOOKUP.values():
            assert len(v) == 4 and v.isdigit(), f"Invalid value: {v}"

    def test_reverse_lookup_consistency(self) -> None:
        """Every entry in MERGER_LOOKUP is reflected in REVERSE_MERGER_LOOKUP."""
        for old, new in MERGER_LOOKUP.items():
            assert old in REVERSE_MERGER_LOOKUP.get(new, []), (
                f"{old} → {new} not found in reverse lookup"
            )
