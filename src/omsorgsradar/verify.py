"""Verifier module — «tool receipts» layer.

Every numeric claim in the narrative is recomputed from the structured
findings JSON and flagged if the deviation exceeds a tolerance.

Design:
- :class:`Verifier` takes an :class:`AnalysisResult` and a list of
  :class:`Claim` objects (extracted from the narrative).
- It recomputes each claimed value from the dataframe and produces a
  :class:`VerificationReport`.
- The test suite includes a test where a deliberately planted false
  statistic is caught (the «tool receipts» showcase test).

Claim types supported:
  - ``top_kommune_rank1_press_index``: press_index_norm of rank-1 kommune
  - ``national_growth_rate_2035``: national 80+ growth rate to 2035
  - ``kommuner_above_threshold``: count of kommuner with press_index_norm ≥ threshold
  - ``coverage_rate_mean``: mean coverage_rate across all kommuner
  - ``top_kommune_name``: name of rank-1 kommune (string equality)
  - ``top_n_press_index``: press_index_norm of rank-n kommune
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .analyze import AnalysisResult, KommuneMetrics

logger = logging.getLogger(__name__)

# Default tolerance for numeric comparisons (relative)
DEFAULT_REL_TOL = 0.01   # 1%
DEFAULT_ABS_TOL = 0.001  # absolute floor


# ──────────────────────────────────────────────────────────────────────────────
# Claim data structure
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Claim:
    """A single verifiable claim extracted from a narrative.

    Attributes:
        claim_type: One of the supported claim types (see module docstring).
        claimed_value: The value asserted in the narrative.
        parameters: Optional dict of parameters for the claim (e.g. threshold, rank).
        source_text: Original text snippet for debugging.
    """

    claim_type: str
    claimed_value: Any
    parameters: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""


@dataclass
class ClaimResult:
    """Result of verifying a single claim.

    Attributes:
        claim: The original claim.
        recomputed_value: Value computed from the findings.
        passes: True if within tolerance.
        relative_error: Relative error (None for string comparisons).
        message: Human-readable verdict.
    """

    claim: Claim
    recomputed_value: Any
    passes: bool
    relative_error: float | None = None
    message: str = ""


@dataclass
class VerificationReport:
    """Aggregate verification report for all claims in a narrative.

    Attributes:
        total_claims: Number of claims checked.
        passed: Number of claims that passed.
        failed: Number of claims that failed.
        results: Per-claim results.
        verdict: ``"PASS"`` if all pass, else ``"FAIL"``.
    """

    total_claims: int = 0
    passed: int = 0
    failed: int = 0
    results: list[ClaimResult] = field(default_factory=list)
    verdict: str = "PASS"

    def summary(self) -> str:
        """Return a one-line summary string."""
        return (
            f"{self.verdict}: {self.passed}/{self.total_claims} claims verified. "
            + (
                "All OK."
                if self.verdict == "PASS"
                else f"{self.failed} FAILED: "
                + "; ".join(r.message for r in self.results if not r.passes)
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# Verifier
# ──────────────────────────────────────────────────────────────────────────────


class Verifier:
    """Recomputes claimed statistics from structured findings.

    Args:
        result: The :class:`AnalysisResult` used as ground truth.
        rel_tol: Relative tolerance for numeric comparisons.
        abs_tol: Absolute tolerance floor.
    """

    def __init__(
        self,
        result: AnalysisResult,
        rel_tol: float = DEFAULT_REL_TOL,
        abs_tol: float = DEFAULT_ABS_TOL,
    ) -> None:
        self._result = result
        self._rel_tol = rel_tol
        self._abs_tol = abs_tol
        # Index kommuner by rank for fast access
        self._by_rank: dict[int, KommuneMetrics] = {
            km.rank: km for km in result.kommuner
        }

    def _numeric_close(self, claimed: float, recomputed: float) -> tuple[bool, float]:
        """Check if two numeric values are within tolerance.

        Returns:
            ``(passes, relative_error)``
        """
        if recomputed == 0 and claimed == 0:
            return True, 0.0
        if recomputed == 0:
            return False, float("inf")
        rel_err = abs(claimed - recomputed) / abs(recomputed)
        passes = rel_err <= self._rel_tol or abs(claimed - recomputed) <= self._abs_tol
        return passes, rel_err

    def verify_claim(self, claim: Claim) -> ClaimResult:
        """Verify a single claim.

        Args:
            claim: The :class:`Claim` to verify.

        Returns:
            :class:`ClaimResult` with verdict and recomputed value.
        """
        ct = claim.claim_type

        if ct == "top_kommune_rank1_press_index":
            km = self._by_rank.get(1)
            if km is None:
                return ClaimResult(
                    claim=claim,
                    recomputed_value=None,
                    passes=False,
                    message="No rank-1 kommune found in findings",
                )
            recomputed = km.press_index_norm
            passes, rel_err = self._numeric_close(float(claim.claimed_value), recomputed)
            return ClaimResult(
                claim=claim,
                recomputed_value=round(recomputed, 4),
                passes=passes,
                relative_error=rel_err,
                message=(
                    "OK"
                    if passes
                    else f"FAIL: claimed {claim.claimed_value:.4f}, recomputed {recomputed:.4f} "
                         f"(rel err {rel_err:.1%})"
                ),
            )

        elif ct == "top_n_press_index":
            rank = int(claim.parameters.get("rank", 1))
            km = self._by_rank.get(rank)
            if km is None:
                return ClaimResult(
                    claim=claim,
                    recomputed_value=None,
                    passes=False,
                    message=f"No rank-{rank} kommune found",
                )
            recomputed = km.press_index_norm
            passes, rel_err = self._numeric_close(float(claim.claimed_value), recomputed)
            return ClaimResult(
                claim=claim,
                recomputed_value=round(recomputed, 4),
                passes=passes,
                relative_error=rel_err,
                message=(
                    "OK"
                    if passes
                    else f"FAIL rank {rank}: claimed {claim.claimed_value:.4f}, "
                         f"recomputed {recomputed:.4f} (rel err {rel_err:.1%})"
                ),
            )

        elif ct == "national_growth_rate_2035":
            recomputed = self._result.national_growth_rate_2035
            if np.isnan(recomputed):
                return ClaimResult(
                    claim=claim, recomputed_value=None, passes=False,
                    message="national_growth_rate_2035 is NaN in findings",
                )
            passes, rel_err = self._numeric_close(float(claim.claimed_value), recomputed)
            return ClaimResult(
                claim=claim,
                recomputed_value=round(recomputed, 2),
                passes=passes,
                relative_error=rel_err,
                message=(
                    "OK"
                    if passes
                    else f"FAIL: claimed {claim.claimed_value:.2f}%, recomputed {recomputed:.2f}% "
                         f"(rel err {rel_err:.1%})"
                ),
            )

        elif ct == "kommuner_above_threshold":
            threshold = float(claim.parameters.get("threshold", 0.5))
            recomputed = sum(
                1 for km in self._result.kommuner
                if not np.isnan(km.press_index_norm) and km.press_index_norm >= threshold
            )
            passes = recomputed == int(claim.claimed_value)
            rel_err = (
                abs(int(claim.claimed_value) - recomputed) / max(recomputed, 1)
            )
            return ClaimResult(
                claim=claim,
                recomputed_value=recomputed,
                passes=passes,
                relative_error=rel_err,
                message=(
                    "OK"
                    if passes
                    else f"FAIL: claimed {claim.claimed_value}, recomputed {recomputed} "
                         f"kommuner with press_index ≥ {threshold}"
                ),
            )

        elif ct == "coverage_rate_mean":
            rates = [km.coverage_rate for km in self._result.kommuner
                     if not np.isnan(km.coverage_rate)]
            if not rates:
                return ClaimResult(
                    claim=claim, recomputed_value=None, passes=False,
                    message="No coverage_rate values available",
                )
            recomputed = np.mean(rates)
            passes, rel_err = self._numeric_close(float(claim.claimed_value), recomputed)
            return ClaimResult(
                claim=claim,
                recomputed_value=round(recomputed, 1),
                passes=passes,
                relative_error=rel_err,
                message=(
                    "OK"
                    if passes
                    else f"FAIL: claimed {claim.claimed_value:.1f}, recomputed {recomputed:.1f} "
                         f"(rel err {rel_err:.1%})"
                ),
            )

        elif ct == "top_kommune_name":
            km = self._by_rank.get(1)
            if km is None:
                return ClaimResult(
                    claim=claim, recomputed_value=None, passes=False,
                    message="No rank-1 kommune found",
                )
            recomputed = km.navn
            passes = str(claim.claimed_value).strip().lower() == recomputed.strip().lower()
            return ClaimResult(
                claim=claim,
                recomputed_value=recomputed,
                passes=passes,
                relative_error=None,
                message=(
                    "OK"
                    if passes
                    else f"FAIL: claimed '{claim.claimed_value}', recomputed '{recomputed}'"
                ),
            )

        else:
            return ClaimResult(
                claim=claim,
                recomputed_value=None,
                passes=False,
                message=f"Unknown claim type: '{ct}'",
            )

    def verify_all(self, claims: list[Claim]) -> VerificationReport:
        """Verify a list of claims and return aggregate report.

        Args:
            claims: List of :class:`Claim` objects.

        Returns:
            :class:`VerificationReport` with all results.
        """
        results: list[ClaimResult] = []
        for claim in claims:
            r = self.verify_claim(claim)
            results.append(r)
            if not r.passes:
                logger.warning("CLAIM FAILED: %s", r.message)
            else:
                logger.debug("Claim OK: %s = %s", claim.claim_type, r.recomputed_value)

        passed = sum(1 for r in results if r.passes)
        failed = len(results) - passed
        report = VerificationReport(
            total_claims=len(results),
            passed=passed,
            failed=failed,
            results=results,
            verdict="PASS" if failed == 0 else "FAIL",
        )
        logger.info("Verification: %s", report.summary())
        return report


# ──────────────────────────────────────────────────────────────────────────────
# Claim extraction helpers (for narrative → claims pipeline)
# ──────────────────────────────────────────────────────────────────────────────


def build_standard_claims(result: AnalysisResult) -> list[Claim]:
    """Build the standard set of claims from analysis findings.

    These claims are directly derivable from the findings and serve as
    the canonical set to be embedded in the narrative and then re-verified.

    Args:
        result: :class:`AnalysisResult` to build claims for.

    Returns:
        List of :class:`Claim` objects.
    """
    claims: list[Claim] = []

    if result.kommuner:
        rank1 = result.kommuner[0]
        claims.append(Claim(
            claim_type="top_kommune_rank1_press_index",
            claimed_value=round(rank1.press_index_norm, 4),
            source_text=f"Rank-1 kommune {rank1.navn} has press index {rank1.press_index_norm:.4f}",
        ))
        if rank1.navn:
            claims.append(Claim(
                claim_type="top_kommune_name",
                claimed_value=rank1.navn,
                source_text=f"Top kommune by press index is {rank1.navn}",
            ))

    if not np.isnan(result.national_growth_rate_2035):
        claims.append(Claim(
            claim_type="national_growth_rate_2035",
            claimed_value=round(result.national_growth_rate_2035, 2),
            source_text=f"National 80+ population grows {result.national_growth_rate_2035:.1f}% to 2035",
        ))

    # Count kommuner in top half of press index
    n_high = sum(
        1 for km in result.kommuner
        if not np.isnan(km.press_index_norm) and km.press_index_norm >= 0.5
    )
    claims.append(Claim(
        claim_type="kommuner_above_threshold",
        claimed_value=n_high,
        parameters={"threshold": 0.5},
        source_text=f"{n_high} kommuner with press_index ≥ 0.5",
    ))

    rates = [km.coverage_rate for km in result.kommuner if not np.isnan(km.coverage_rate)]
    if rates:
        mean_rate = np.mean(rates)
        claims.append(Claim(
            claim_type="coverage_rate_mean",
            claimed_value=round(mean_rate, 1),
            source_text=f"Mean coverage rate: {mean_rate:.1f} brukere per 1000 80+",
        ))

    return claims
