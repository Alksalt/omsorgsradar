"""Regenerate kommune_mergers.py data from SSB KLASS classification 131.

Run this script when a new wave of mergers occurs. Its printed output
is pasted into src/omsorgsradar/kommune_mergers.py.

Usage:
    uv run python scripts/regen_kommune_mergers.py

Source:
    https://data.ssb.no/api/klass/v1/classifications/131/changes.json
    Queried: 2017-12-31 -> 2018-01-02  (2018 wave)
             2019-12-31 -> 2020-01-02  (2020 wave)
    Fetch date: 2026-06-12

Split-exclusion rule:
    Old codes that map to MORE THAN ONE new code (municipality splits)
    cannot be attributed to a single successor and are excluded from the
    normalisation table. They are collected in SPLIT_CODES_EXCLUDED.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

try:
    import requests
except ImportError:
    print("requests not installed — run: uv add requests", file=sys.stderr)
    sys.exit(1)

KLASS_URL = "https://data.ssb.no/api/klass/v1/classifications/131/changes.json"
QUERY_WINDOWS = [
    ("2017-12-31", "2018-01-02"),
    ("2019-12-31", "2020-01-02"),
]


def fetch_changes() -> list[dict]:
    changes: list[dict] = []
    for frm, to in QUERY_WINDOWS:
        r = requests.get(
            KLASS_URL,
            params={"from": frm, "to": to},
            timeout=60,
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        batch = r.json().get("codeChanges", [])
        print(f"  {frm} -> {to}: {len(batch)} code changes", file=sys.stderr)
        changes.extend(batch)
    return changes


def build_table(changes: list[dict]) -> tuple[list[tuple], dict]:
    old_to_new: dict[str, list[tuple]] = defaultdict(list)
    for c in changes:
        old_to_new[c["oldCode"]].append(
            (c["newCode"], c["newName"], c["changeOccurred"])
        )

    splits: dict[str, list[tuple]] = {
        k: v for k, v in old_to_new.items() if len(v) > 1
    }
    one_to_one: list[tuple] = [
        (k, nc, nn, dt)
        for k, [(nc, nn, dt)] in [
            (k, v) for k, v in old_to_new.items() if len(v) == 1
        ]
        # exclude self-referential: code did not change, only name changed
        if k != nc
    ]
    one_to_one.sort(key=lambda x: x[0])
    return one_to_one, splits


def print_module_data(one_to_one: list[tuple], splits: dict) -> None:
    split_codes = sorted(splits.keys())
    split_names = {
        k: next(
            nn for nc, nn, _ in vs for _ in [None]
        )
        for k, vs in splits.items()
    }
    # Build a readable split description
    split_desc_lines = []
    for k in split_codes:
        targets = ", ".join(f"{nc} ({nn})" for nc, nn, _ in splits[k])
        split_desc_lines.append(f"#   {k} -> {targets}")

    print("# ── GENERATED DATA — do not edit by hand ─────────────────────────────────")
    print("# Source: https://data.ssb.no/api/klass/v1/classifications/131/changes.json")
    print("# Query dates: 2017-12-31→2018-01-02 (2018 wave), 2019-12-31→2020-01-02 (2020 wave)")
    print("# Fetch date: 2026-06-12")
    print("# Split-exclusion rule: old codes mapping to 2+ new codes are excluded.")
    print("# Regenerate with: uv run python scripts/regen_kommune_mergers.py")
    print()
    print(f"# Split codes excluded ({len(split_codes)} total):")
    for line in split_desc_lines:
        print(line)
    print()
    print(f"SPLIT_CODES_EXCLUDED: frozenset[str] = frozenset({{")
    for k in split_codes:
        # find old name
        print(f'    "{k}",  # {splits[k][0][1]} / {splits[k][1][1]}', end="")
        if len(splits[k]) > 2:
            print(f' / {splits[k][2][1]}', end="")
        print()
    print("})")
    print()
    print(f"_ALL_CHANGES: list[MergerRecord] = [  # {len(one_to_one)} entries")
    for old_k, nc, nn, dt in one_to_one:
        yr = int(dt[:4])
        print(f'    MergerRecord("{old_k}", "{nc}", "{nn}", {yr}),')
    print("]")


if __name__ == "__main__":
    print("Fetching KLASS classification 131 changes...", file=sys.stderr)
    changes = fetch_changes()
    print(f"Total raw changes: {len(changes)}", file=sys.stderr)
    one_to_one, splits = build_table(changes)
    print(f"One-to-one (non-self): {len(one_to_one)}", file=sys.stderr)
    print(f"Splits excluded: {sorted(splits.keys())}", file=sys.stderr)
    print()
    print_module_data(one_to_one, splits)
