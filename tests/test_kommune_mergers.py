"""Tests for the kommune merger lookup table."""

import pytest
from omsorgsradar.kommune_mergers import (
    normalize_knr,
    normalize_knr_series,
    MERGER_LOOKUP,
    REVERSE_MERGER_LOOKUP,
    SPLIT_CODES_EXCLUDED,
)
import pandas as pd


class TestNormalizeKnr:
    """Tests for normalize_knr scalar function."""

    def test_passthrough_for_current_knr(self) -> None:
        """Known current municipality numbers are returned unchanged."""
        assert normalize_knr("0301") == "0301"  # Oslo

    def test_molde_predecessors_2020(self) -> None:
        """Old Molde predecessors map to new 1506 per KLASS.

        KLASS classification 131 records:
          1502 (old Molde) -> 1506
          1543 (Nesset)    -> 1506
          1545 (Midsund)   -> 1506
        Note: the former hand-written entry '1504 -> 1506' was WRONG;
        KLASS records 1504 (old Ålesund) -> 1507.
        """
        assert normalize_knr("1502") == "1506"
        assert normalize_knr("1543") == "1506"
        assert normalize_knr("1545") == "1506"

    def test_alesund_chain_into_2024_split_is_dropped(self) -> None:
        """Old Ålesund (1504) merged to 1507 in 2020, but 1507 SPLIT in 2024
        (1507 → 1508 Ålesund + 1580 Haram). A chain running into a split has no
        single terminal successor, so 1504 et al. are dropped (pass through)."""
        assert normalize_knr("1504") == "1504"  # chain into 1507 split → dropped
        assert normalize_knr("1523") == "1523"  # Ørskog
        assert normalize_knr("1529") == "1529"  # Skodje
        assert normalize_knr("1534") == "1534"  # Haram
        assert normalize_knr("1546") == "1546"  # Sandøy
        assert "1507" in SPLIT_CODES_EXCLUDED

    def test_halden_renumbering_terminal_2024(self) -> None:
        """0101 (Halden): renumbered 0101→3001 in 2020, then 3001→3101 in the
        2024 Viken dissolution. Closure resolves to the terminal code 3101."""
        assert normalize_knr("0101") == "3101"

    def test_trondheim_renumbering(self) -> None:
        """Old 1601 -> 5001 (Trondheim renumbering in 2018)."""
        assert normalize_knr("1601") == "5001"

    def test_bergen_renumbering(self) -> None:
        """Old 1201 -> 4601 (Bergen renumbering in 2020)."""
        assert normalize_knr("1201") == "4601"

    def test_zero_padded_input(self) -> None:
        """Input without leading zeros is handled correctly."""
        assert normalize_knr("301") == "0301"

    def test_unknown_knr_passthrough(self) -> None:
        """An unknown 4-digit code is returned as-is."""
        assert normalize_knr("9999") == "9999"

    def test_asker_predecessors(self) -> None:
        """Old Asker-area communes merge to Asker, terminal code 3203 (2024).

        KLASS: 0220/0627/0628 -> 3025 (2020 Viken), then 3025 -> 3203 (2024
        Viken dissolution). Closure resolves to the terminal 3203.
        Note: 0226 (Sørum) -> 3205 (Lillestrøm), not Asker.
        """
        assert normalize_knr("0220") == "3203"
        assert normalize_knr("0627") == "3203"
        assert normalize_knr("0628") == "3203"

    def test_soerrum_to_lillestroen(self) -> None:
        """0226 (Sørum) -> Lillestrøm, terminal code 3205 (3030 in 2020 → 3205
        in 2024) per KLASS (not Asker)."""
        assert normalize_knr("0226") == "3205"

    def test_kristiansand_merger(self) -> None:
        """Kristiansand merger per KLASS.

        1001 (Kristiansand) + 1017 (Songdalen) + 1018 (Søgne) -> 4204.
        Note: 1002 (Mandal) was WRONG in old table — KLASS records 1002 -> 4205 (Lindesnes).
        """
        assert normalize_knr("1001") == "4204"
        assert normalize_knr("1017") == "4204"
        assert normalize_knr("1018") == "4204"

    def test_mandal_to_lindesnes(self) -> None:
        """1002 (Mandal) -> 4205 (Lindesnes) per KLASS (not Kristiansand)."""
        assert normalize_knr("1002") == "4205"

    def test_split_codes_pass_through(self) -> None:
        """Split codes (no single successor) are returned unchanged."""
        assert normalize_knr("5012") == "5012"  # Snillfjord split
        assert normalize_knr("1850") == "1850"  # Tysfjord split

    def test_hvaler_chain_resolves_to_terminal_2024(self) -> None:
        """Bug-1 regression: 0111 (Hvaler) was renumbered 0111→3011 in 2020,
        then 3011→3110 in the 2024 Viken dissolution. The closure must resolve
        0111 DIRECTLY to the terminal 3110 (not the intermediate 3011), so the
        population series under 0111/3011/3110 collapses into one knr."""
        assert normalize_knr("0111") == "3110"
        # The intermediate code also resolves to the terminal.
        assert normalize_knr("3011") == "3110"


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

    def test_split_codes_unchanged_in_series(self) -> None:
        """Split codes in a series pass through unchanged; chained codes resolve
        to their terminal (0101 → 3101 after the 2024 wave)."""
        s = pd.Series(["5012", "1850", "0101"])
        result = normalize_knr_series(s)
        assert result.tolist() == ["5012", "1850", "3101"]

    def test_klass_verified_terminal_codes(self) -> None:
        """Key KLASS-verified mappings resolve to terminal codes in series form.
        1504 chains into the 2024 Ålesund split → dropped; 1502→1506 (Molde,
        unchanged 2024); 0101→3101 (Halden, renumbered twice)."""
        s = pd.Series(["1504", "1502", "0101"])
        result = normalize_knr_series(s)
        assert result.tolist() == ["1504", "1506", "3101"]


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
                f"{old} -> {new} not found in reverse lookup"
            )

    def test_split_codes_not_in_merger_lookup(self) -> None:
        """Split codes are excluded from MERGER_LOOKUP (no attribution possible)."""
        for code in SPLIT_CODES_EXCLUDED:
            assert code not in MERGER_LOOKUP, (
                f"Split code {code} should not appear in MERGER_LOOKUP"
            )

    def test_table_size_matches_klass(self) -> None:
        """Merger lookup has the expected number of entries from KLASS across the
        2018+2020+2024 waves (468 one-to-one after transitive closure; 6 codes
        dropped because their chain runs into the 2024 Ålesund/Snillfjord split)."""
        assert len(MERGER_LOOKUP) == 468, (
            f"Expected 468 KLASS-sourced entries, got {len(MERGER_LOOKUP)}"
        )

    def test_table_fully_resolved_no_value_is_a_key(self) -> None:
        """Bug-1 invariant: the table is resolved to terminal codes — no mapping
        VALUE is itself a mapping KEY. Otherwise normalize_knr would leave a code
        one hop short of its current number (the original 0111→3011 bug)."""
        keys = set(MERGER_LOOKUP.keys())
        values = set(MERGER_LOOKUP.values())
        leaked = values & keys
        assert not leaked, (
            f"table not fully resolved — these codes are both a value and a key: "
            f"{sorted(leaked)}"
        )

    def test_no_value_is_a_split_code(self) -> None:
        """No terminal code is itself an excluded split source (a chain into a
        split must be dropped, never point at the split code)."""
        values = set(MERGER_LOOKUP.values())
        assert not (values & SPLIT_CODES_EXCLUDED), (
            f"split code leaked as a terminal: {sorted(values & SPLIT_CODES_EXCLUDED)}"
        )
