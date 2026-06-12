"""Generate a synthetic BRFSS-shaped microdata fixture (deterministic, seeded).
Columns: state (FIPS), age (int), sex (1/2), diabetes (0/1), notes (free text).
Two rows carry a planted valid fødselsnummer to exercise the PII gate. No real
people; safe to commit. Run: uv run python analyses/brfss-demo/microdata/make_fixture.py
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from omsorgsradar.core.anonymize.pii import append_fnr_control_digits


def _valid_fnr(ddmmyy: str, start_individ: int = 100) -> str:
    """Return a checksum-valid fnr for a birth date, scanning individ numbers
    upward until the mod-11 checksum is satisfiable (never hardcode a literal)."""
    for ind in range(start_individ, 1000):
        try:
            return append_fnr_control_digits(f"{ddmmyy}{ind:03d}")
        except ValueError:
            continue
    raise RuntimeError("no valid individ found")


def build(n: int = 600) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "state": rng.choice(["06", "48", "36", "12", "17"], n),
        "age":   rng.integers(18, 95, n),
        "sex":   rng.integers(1, 3, n),
        "diabetes": rng.integers(0, 2, n),
        "notes": ["rutinekontroll"] * n,
    })
    df.loc[0, "notes"] = f"pasient {_valid_fnr('010190')} oppfølging"
    df.loc[1, "notes"] = f"tlf 91123456; fnr {_valid_fnr('150385')}"
    return df


if __name__ == "__main__":
    out = Path(__file__).parent / "brfss_sample.csv"
    build().to_csv(out, index=False)
    print(f"wrote {out} ({len(build())} rows)")
