"""Tests for src/omsorgsradar/fmt.py — nb-NO number formatting.

TDD: these tests were written before the implementation and define the contract.
All tests are offline (no I/O, no network, no matplotlib).
"""

from __future__ import annotations

import math
import pytest

from omsorgsradar.fmt import nb, nb_pct, nb_index


class TestNb:
    """nb(value, decimals) → Norwegian decimal / thousands format."""

    def test_simple_decimal(self):
        assert nb(31.1) == "31,1"

    def test_large_number_thousands_space(self):
        # 288 360 — space as thousands separator, zero decimal places
        result = nb(288360.0, decimals=0)
        assert result == "288 360"

    def test_thousands_separator_present(self):
        result = nb(1234.5, decimals=1)
        assert " " in result  # space thousands separator
        assert "," in result  # comma decimal separator

    def test_two_decimal_places(self):
        assert nb(1234.5, decimals=2) == "1 234,50"

    def test_zero_decimal(self):
        assert nb(1000.0, decimals=0) == "1 000"

    def test_nan_returns_dash(self):
        assert nb(float("nan")) == "—"

    def test_inf_returns_dash(self):
        assert nb(float("inf")) == "—"

    def test_negative_inf_returns_dash(self):
        assert nb(float("-inf")) == "—"

    def test_small_number_no_separator(self):
        # Numbers < 1000 should not have a thousands separator
        result = nb(31.1, decimals=1)
        assert result == "31,1"

    def test_zero(self):
        assert nb(0.0, decimals=1) == "0,0"

    def test_integer_like(self):
        # 357 with no decimals → no separator needed
        assert nb(357.0, decimals=0) == "357"

    def test_no_dot_decimal_separator(self):
        # Must never use '.' as decimal separator
        result = nb(31.1, decimals=1)
        assert "." not in result

    def test_no_comma_thousands_separator(self):
        # Must never use ',' as thousands separator (that's the English format)
        result = nb(288360.0, decimals=0)
        # The only comma present would be the decimal sep; at 0 decimals, none at all
        assert "," not in result


class TestNbPct:
    """nb_pct(value) → «xx,x %»."""

    def test_typical(self):
        assert nb_pct(31.1) == "31,1 %"

    def test_integer_like(self):
        assert nb_pct(46.0) == "46,0 %"

    def test_space_before_percent(self):
        result = nb_pct(10.0)
        assert result.endswith(" %")

    def test_nan(self):
        assert nb_pct(float("nan")) == "—"

    def test_large(self):
        # e.g. growth of 116.8%
        assert nb_pct(116.8) == "116,8 %"

    def test_zero(self):
        assert nb_pct(0.0) == "0,0 %"


class TestNbIndex:
    """nb_index(value) → two-decimal Norwegian string — never «1.000» (= one thousand)."""

    def test_one(self):
        # 1.0 press index must render «1,00», not «1.000»
        assert nb_index(1.0) == "1,00"

    def test_zero_nine_three_five(self):
        # Rounding: 0.935 → «0,94» (rounds up at 2 dp)
        assert nb_index(0.935) == "0,94"

    def test_zero(self):
        assert nb_index(0.0) == "0,00"

    def test_no_dot_decimal(self):
        result = nb_index(0.75)
        assert "." not in result
        assert "," in result

    def test_two_decimal_places(self):
        result = nb_index(0.1234)
        # Should have exactly 2 decimal places after comma
        parts = result.split(",")
        assert len(parts) == 2
        assert len(parts[1]) == 2
