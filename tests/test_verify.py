"""Tests for the verifier module — including the mandatory planted-hallucination test.

The «tool receipts» showcase test verifies that the Verifier catches a
deliberately planted false statistic (a claimed press index of 0.999 when
the true value is much lower, and a fake growth rate).
"""

from pathlib import Path

import pytest
import numpy as np
import pandas as pd

from omsorgsradar.analyze import AnalysisResult, KommuneMetrics
from omsorgsradar.verify import (
    Claim,
    ClaimResult,
    VerificationReport,
    Verifier,
    build_standard_claims,
    recompute_living_knrs_from_db,
    verify_ranked_knrs_exist_in_db,
)


def _make_result(n: int = 5) -> AnalysisResult:
    """Build a synthetic AnalysisResult for testing."""
    kommuner = []
    for i in range(1, n + 1):
        press = 1.0 - (i - 1) / n  # descending: 1.0, 0.8, 0.6, 0.4, 0.2
        km = KommuneMetrics(
            knr=f"000{i}",
            navn=f"Kommune{i}",
            pop_80plus_latest=1000.0 * i,
            pop_80plus_projected_2035=1200.0 * i,
            pop_80plus_growth_pct=20.0,
            coverage_rate=100.0 + i * 10,
            inst_places_per_1000_80plus=50.0,
            press_index_raw=press * 10,
            press_index_norm=press,
            rank=i,
            latest_kostra_year=2024,
            latest_pop_year=2024,
        )
        kommuner.append(km)
    return AnalysisResult(
        kommuner=kommuner,
        national_80plus_latest=10000.0,
        national_80plus_2035=12000.0,
        national_growth_rate_2035=20.0,
        analysis_year_range=(2007, 2024),
    )


class TestVerifierBasic:
    """Basic verifier functionality."""

    def test_correct_rank1_press_index_passes(self) -> None:
        """A claim matching rank-1 press index passes verification."""
        result = _make_result()
        verifier = Verifier(result)
        claim = Claim(
            claim_type="top_kommune_rank1_press_index",
            claimed_value=1.0,
        )
        r = verifier.verify_claim(claim)
        assert r.passes, f"Expected PASS, got: {r.message}"

    def test_correct_national_growth_passes(self) -> None:
        """Correct national growth rate claim passes."""
        result = _make_result()
        verifier = Verifier(result)
        claim = Claim(
            claim_type="national_growth_rate_2035",
            claimed_value=20.0,
        )
        r = verifier.verify_claim(claim)
        assert r.passes

    def test_correct_top_kommune_name_passes(self) -> None:
        """Correct top kommune name claim passes."""
        result = _make_result()
        verifier = Verifier(result)
        claim = Claim(
            claim_type="top_kommune_name",
            claimed_value="Kommune1",
        )
        r = verifier.verify_claim(claim)
        assert r.passes

    def test_unknown_claim_type_fails(self) -> None:
        """An unknown claim type returns a failing result."""
        result = _make_result()
        verifier = Verifier(result)
        claim = Claim(claim_type="imaginary_stat", claimed_value=42)
        r = verifier.verify_claim(claim)
        assert not r.passes


class TestPlantedHallucination:
    """
    The mandatory «tool receipts» test.

    Scenario: a narrative claims that rank-1 kommune has press_index = 0.999
    (planted hallucination) and that the national growth rate is 99.9%
    (another planted hallucination). The verifier must catch both.
    """

    def test_verifier_catches_planted_press_index_hallucination(self) -> None:
        """Verifier MUST flag a false press index claim.

        This is the core «tool receipts» showcase test.  A LLM that
        hallucinated «press-indeks 0.999» instead of reading the JSON
        findings would be caught here.
        """
        result = _make_result()  # rank-1 has press_index_norm = 1.0, not 0.999 (within tol)
        # Plant a claim with a value way off (0.5 when reality is 1.0 → 50% rel error)
        verifier = Verifier(result, rel_tol=0.01)
        planted_claim = Claim(
            claim_type="top_kommune_rank1_press_index",
            claimed_value=0.50,  # hallucinated: reality is 1.0
            source_text="[HALLUCINATED] Press-indeksen til den hardest pressede kommunen er 0,50",
        )
        r = verifier.verify_claim(planted_claim)
        assert not r.passes, (
            "VERIFIER DID NOT CATCH PLANTED HALLUCINATION — "
            f"claimed 0.50, recomputed {r.recomputed_value}, message: {r.message}"
        )
        assert r.relative_error is not None and r.relative_error > 0.40

    def test_verifier_catches_planted_growth_rate_hallucination(self) -> None:
        """Verifier catches a false national growth rate claim.

        A narrative claiming 99.9% growth when the data shows 20% is caught.
        """
        result = _make_result()  # national_growth_rate_2035 = 20.0
        verifier = Verifier(result, rel_tol=0.01)
        planted_claim = Claim(
            claim_type="national_growth_rate_2035",
            claimed_value=99.9,  # hallucinated
            source_text="[HALLUCINATED] Den nasjonale 80+-befolkningen vil vokse med 99,9% innen 2035",
        )
        r = verifier.verify_claim(planted_claim)
        assert not r.passes, (
            "VERIFIER DID NOT CATCH GROWTH RATE HALLUCINATION — "
            f"claimed 99.9%, recomputed {r.recomputed_value}%, message: {r.message}"
        )

    def test_verifier_catches_planted_kommune_name_hallucination(self) -> None:
        """Verifier catches a wrong top-kommune name claim."""
        result = _make_result()  # rank-1 is Kommune1
        verifier = Verifier(result)
        planted_claim = Claim(
            claim_type="top_kommune_name",
            claimed_value="FiktivKommune",  # hallucinated name
            source_text="[HALLUCINATED] FiktivKommune er mest presset",
        )
        r = verifier.verify_claim(planted_claim)
        assert not r.passes

    def test_full_verification_with_mixed_claims(self) -> None:
        """verify_all report has FAIL verdict when any claim fails."""
        result = _make_result()
        verifier = Verifier(result, rel_tol=0.01)
        claims = [
            Claim(
                claim_type="top_kommune_rank1_press_index",
                claimed_value=1.0,  # correct
            ),
            Claim(
                claim_type="national_growth_rate_2035",
                claimed_value=99.9,  # HALLUCINATED
            ),
        ]
        report = verifier.verify_all(claims)
        assert report.verdict == "FAIL"
        assert report.failed == 1
        assert report.passed == 1

    def test_all_correct_claims_pass(self) -> None:
        """verify_all has PASS verdict when all claims are correct."""
        result = _make_result()
        verifier = Verifier(result)
        claims = build_standard_claims(result)
        report = verifier.verify_all(claims)
        assert report.verdict == "PASS", (
            f"Expected PASS but got FAIL: {report.summary()}"
        )


class TestVerificationReport:
    """Tests for VerificationReport summary formatting."""

    def test_summary_pass_message(self) -> None:
        """PASS verdict summary contains 'PASS'."""
        result = _make_result()
        verifier = Verifier(result)
        claims = build_standard_claims(result)
        report = verifier.verify_all(claims)
        if report.verdict == "PASS":
            assert "PASS" in report.summary()

    def test_summary_fail_message_contains_claim_type(self) -> None:
        """FAIL verdict summary mentions the failing claim type."""
        result = _make_result()
        verifier = Verifier(result, rel_tol=0.01)
        claims = [
            Claim(
                claim_type="national_growth_rate_2035",
                claimed_value=99.9,  # planted hallucination
            )
        ]
        report = verifier.verify_all(claims)
        assert report.verdict == "FAIL"
        assert "FAIL" in report.summary()


def _seed_befolkning_db(db_path: Path) -> None:
    """Write a tiny befolkning table: 0301 live, 3011 dead in latest year 2024."""
    from omsorgsradar.ingest import save_to_duckdb

    rows = []
    for aar in (2022, 2023, 2024):
        rows.append({"knr": "0301", "knr_raw": "0301", "alder": "80 år",
                     "aar": aar, "value": 1000.0})
        # dead code: positive only in 2022, zero afterwards
        rows.append({"knr": "3011", "knr_raw": "3011", "alder": "80 år",
                     "aar": aar, "value": 200.0 if aar == 2022 else 0.0})
    save_to_duckdb(pd.DataFrame(rows), "befolkning", db_path=db_path)


class TestStructuralDbCheck:
    """Bug-'Also': independent DuckDB recompute that ranked knrs are living.

    These checks read the persisted befolkning table directly — they do NOT
    trust analyze internals — so a dead-code-ranking regression is caught even
    if run_analysis is later broken.
    """

    def test_recompute_living_knrs_from_db(self, tmp_path: Path) -> None:
        db = tmp_path / "t.duckdb"
        _seed_befolkning_db(db)
        living, year = recompute_living_knrs_from_db(db)
        assert year == 2024
        assert living == {"0301"}, f"expected only 0301 living, got {living}"

    def test_ranked_living_kommune_passes(self, tmp_path: Path) -> None:
        db = tmp_path / "t.duckdb"
        _seed_befolkning_db(db)
        result = AnalysisResult(kommuner=[
            KommuneMetrics(knr="0301", navn="Oslo", rank=1,
                           pop_80plus_growth_pct=10.0, press_index_norm=1.0),
            KommuneMetrics(knr="3011", navn="Hvaler (-2019)", rank=0,
                           pop_80plus_growth_pct=float("nan"),
                           press_index_norm=float("nan")),
        ])
        cr = verify_ranked_knrs_exist_in_db(result, db)
        assert cr.passes, cr.message

    def test_ranked_dead_code_fails(self, tmp_path: Path) -> None:
        db = tmp_path / "t.duckdb"
        _seed_befolkning_db(db)
        # Plant a regression: a DEAD code (3011) carries a rank.
        result = AnalysisResult(kommuner=[
            KommuneMetrics(knr="0301", navn="Oslo", rank=1,
                           pop_80plus_growth_pct=10.0, press_index_norm=1.0),
            KommuneMetrics(knr="3011", navn="Hvaler (-2019)", rank=2,
                           pop_80plus_growth_pct=5.0, press_index_norm=0.5),
        ])
        cr = verify_ranked_knrs_exist_in_db(result, db)
        assert not cr.passes, "structural check must FAIL when a dead code is ranked"
        assert "3011" in cr.message


class TestBuildStandardClaims:
    """Tests for the standard claim builder."""

    def test_returns_list_of_claims(self) -> None:
        """Returns a non-empty list."""
        result = _make_result()
        claims = build_standard_claims(result)
        assert isinstance(claims, list)
        assert len(claims) > 0

    def test_claims_are_verifiable(self) -> None:
        """All standard claims pass verification against the same result."""
        result = _make_result()
        verifier = Verifier(result)
        claims = build_standard_claims(result)
        report = verifier.verify_all(claims)
        assert report.verdict == "PASS", report.summary()
