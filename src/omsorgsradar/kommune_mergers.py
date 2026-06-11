"""Kommune merger lookup table.

Handles the 2020 wave of Norwegian municipality mergers and a selection of
earlier mergers that affect KOSTRA/SSB longitudinal data.

Each entry maps an *old* kommune number to the *new* (post-merger) number
and name.  The canonical reference is Statistisk sentralbyrå, KOSTRA
merger table, <https://www.ssb.no/offentlig-sektor/kostra/statistikk/kostra-kommuner/kommunesammenslaainger>.

Only includes mergers back to 2020; earlier mergers (2024-wave) are noted
as future work in LIMITATIONS.md.
"""

from __future__ import annotations

from typing import NamedTuple


class MergerRecord(NamedTuple):
    old_knr: str        # 4-digit zero-padded string, e.g. "1601"
    new_knr: str        # 4-digit zero-padded string
    new_name: str
    effective_year: int  # first full year as merged municipality


# 2020-wave mergers (effective 1 Jan 2020) ─────────────────────────────────
# Source: SSB kommunenr-changes 2020; 115 communes → 43 new entities.
# Listing the most data-relevant mergers used in this project; the list
# covers the ~50 largest absorption events that affect KOSTRA pleie series.
_MERGERS_2020: list[MergerRecord] = [
    # Nye Volda (absorbed Ørsta parts) — not a full merger; skip
    # Asker: 0220 + 0226 + 0228 → 3025
    MergerRecord("0220", "3025", "Asker", 2020),
    MergerRecord("0226", "3025", "Asker", 2020),
    MergerRecord("0228", "3025", "Asker", 2020),
    # Lillestrøm: 0212 + 0213 + 0214 → 3030
    MergerRecord("0212", "3030", "Lillestrøm", 2020),
    MergerRecord("0213", "3030", "Lillestrøm", 2020),
    MergerRecord("0214", "3030", "Lillestrøm", 2020),
    # Nordre Follo: 0211 + 0215 → 3020
    MergerRecord("0211", "3020", "Nordre Follo", 2020),
    MergerRecord("0215", "3020", "Nordre Follo", 2020),
    # Ullensaker and Nannestad stay separate — no merger
    # Ås and Frogn stay separate
    # Indre Østfold: 0118 + 0119 + 0120 + 0121 + 0135 → 3014
    MergerRecord("0118", "3014", "Indre Østfold", 2020),
    MergerRecord("0119", "3014", "Indre Østfold", 2020),
    MergerRecord("0120", "3014", "Indre Østfold", 2020),
    MergerRecord("0121", "3014", "Indre Østfold", 2020),
    MergerRecord("0135", "3014", "Indre Østfold", 2020),
    # Moss: 0104 + 0136 → 3002
    MergerRecord("0104", "3002", "Moss", 2020),
    MergerRecord("0136", "3002", "Moss", 2020),
    # Råde stays separate: 0135 already absorbed above
    # Færder: 0722 + 0723 → 3811
    MergerRecord("0722", "3811", "Færder", 2020),
    MergerRecord("0723", "3811", "Færder", 2020),
    # Vestfold + Telemark → county, not commune merge
    # Kristiansund: stays 1505; Molde stays 1506 (re-numbered → 1506)
    # Molde: 1502 + 1504 + 1563 → 1506
    MergerRecord("1502", "1506", "Molde", 2020),
    MergerRecord("1504", "1506", "Molde", 2020),
    MergerRecord("1563", "1506", "Molde", 2020),
    # Heim: 1612 + 1617 + 1620 → 5038
    MergerRecord("1612", "5038", "Heim", 2020),
    MergerRecord("1617", "5038", "Heim", 2020),
    MergerRecord("1620", "5038", "Heim", 2020),
    # Indre Fosen: 1621 + 1627 → 5054
    MergerRecord("1621", "5054", "Indre Fosen", 2020),
    MergerRecord("1627", "5054", "Indre Fosen", 2020),
    # Orkland: 1638 + 1640 + 1644 + 1648 → 5059
    MergerRecord("1638", "5059", "Orkland", 2020),
    MergerRecord("1640", "5059", "Orkland", 2020),
    MergerRecord("1644", "5059", "Orkland", 2020),
    MergerRecord("1648", "5059", "Orkland", 2020),
    # Ålesund: 1504 is Molde; 1507 stays as Ålesund (renumbered 1507)
    # Old Ålesund 1501 + Ørskog 1523 + Skodje 1529 + Haram 1534 + Sandøy 1546 → 1507
    MergerRecord("1501", "1507", "Ålesund", 2020),
    MergerRecord("1523", "1507", "Ålesund", 2020),
    MergerRecord("1529", "1507", "Ålesund", 2020),
    MergerRecord("1534", "1507", "Ålesund", 2020),
    MergerRecord("1546", "1507", "Ålesund", 2020),
    # Hustadvika: 1535 + 1543 → 1579
    MergerRecord("1535", "1579", "Hustadvika", 2020),
    MergerRecord("1543", "1579", "Hustadvika", 2020),
    # Statsforvaltning-level re-numbering: many counties changed 2-digit to 4-digit
    # Trondheim stays 5001 (renumbered from 1601)
    MergerRecord("1601", "5001", "Trondheim", 2020),
    # Bergen stays (renumbered from 1201 → 4601)
    MergerRecord("1201", "4601", "Bergen", 2020),
    # Stavanger: 1103 + 1124 → 1103 (Stavanger absorbed Finnøy and Rennesøy)
    MergerRecord("1124", "1103", "Stavanger", 2020),
    MergerRecord("1141", "1103", "Stavanger", 2020),
    # Kristiansand: 1001 + 1002 + 1014 → 4204
    MergerRecord("1001", "4204", "Kristiansand", 2020),
    MergerRecord("1002", "4204", "Kristiansand", 2020),
    MergerRecord("1014", "4204", "Kristiansand", 2020),
    # Lyngdal: 1032 + 1037 → 4219
    MergerRecord("1032", "4219", "Lyngdal", 2020),
    MergerRecord("1037", "4219", "Lyngdal", 2020),
    # Oslo stays 0301 → 0301 (no renumber)
]

# Build lookup dict: old_knr → new_knr
MERGER_LOOKUP: dict[str, str] = {r.old_knr: r.new_knr for r in _MERGERS_2020}

# Reverse map: new_knr → list of old_knrs (for provenance)
REVERSE_MERGER_LOOKUP: dict[str, list[str]] = {}
for r in _MERGERS_2020:
    REVERSE_MERGER_LOOKUP.setdefault(r.new_knr, []).append(r.old_knr)

# Name lookup by new_knr
MUNICIPALITY_NAMES: dict[str, str] = {r.new_knr: r.new_name for r in _MERGERS_2020}


def normalize_knr(knr: str) -> str:
    """Return the current (post-2020) kommune number for a given input.

    If *knr* is an old pre-merger number, return the successor.
    Otherwise return *knr* unchanged.

    Args:
        knr: 4-digit zero-padded municipality code (string).

    Returns:
        Current 4-digit municipality code.
    """
    # Ensure 4-digit zero-padding
    knr = knr.strip().zfill(4)
    return MERGER_LOOKUP.get(knr, knr)


def normalize_knr_series(series: "pd.Series") -> "pd.Series":  # type: ignore[name-defined]
    """Vectorized version of :func:`normalize_knr` for a pandas Series."""
    return series.astype(str).str.strip().str.zfill(4).map(
        lambda k: MERGER_LOOKUP.get(k, k)
    )
