"""Municipality-code harmonization across NO/SE/FI.

Canonical cross-country key: ``<ISO2>-<national code>`` — "NO-1505",
"SE-0180", "FI-091". National codes keep their official zero-padding
(NO/SE 4 digits, FI 3 digits). Norwegian codes must additionally pass
through :func:`omsorgsradar.kommune_mergers.normalize_knr_series` (adapter
responsibility) so pre-2020 numbers land on post-merger municipalities.
"""

from __future__ import annotations


class GeoError(ValueError):
    """A municipality code or geo id does not match its country's format."""


CODE_LENGTHS: dict[str, int] = {"NO": 4, "SE": 4, "FI": 3}


def normalize_code(country: str, code: object) -> str:
    c2 = country.upper()
    if c2 not in CODE_LENGTHS:
        raise GeoError(f"unknown country '{country}' (known: {sorted(CODE_LENGTHS)})")
    n = CODE_LENGTHS[c2]
    raw = str(code).strip()
    if raw.isdigit() and 0 < len(raw) <= n:
        return raw.zfill(n)
    raise GeoError(f"{c2}: invalid municipality code {code!r} (expected ≤{n} digits)")


def make_geo_id(country: str, code: object) -> str:
    return f"{country.upper()}-{normalize_code(country, code)}"


def split_geo_id(geo_id: str) -> tuple[str, str]:
    country, sep, code = str(geo_id).partition("-")
    if not sep:
        raise GeoError(f"invalid geo id {geo_id!r} (expected '<CC>-<code>')")
    c2 = country.upper()
    if c2 not in CODE_LENGTHS or len(code) != CODE_LENGTHS[c2] or not code.isdigit():
        raise GeoError(f"invalid geo id {geo_id!r}")
    return c2, code
