"""Regenerate kommune_mergers.py data from SSB KLASS classification 131.

Run this script when a new wave of mergers occurs. Its printed output
is pasted into src/omsorgsradar/kommune_mergers.py.

Usage:
    uv run python scripts/regen_kommune_mergers.py

Source:
    https://data.ssb.no/api/klass/v1/classifications/131/changes.json
    Queried: 2017-12-31 -> 2018-01-02  (2018 wave)
             2019-12-31 -> 2020-01-02  (2020 wave)
             2023-12-31 -> 2024-01-02  (2024 wave — Viken/Troms-Finnmark
                                        dissolution renumberings 30xx→31xx etc.)
    Fetch date: 2026-06-12

Split-exclusion rule:
    Old codes that map to MORE THAN ONE new code (municipality splits)
    cannot be attributed to a single successor and are excluded from the
    normalisation table. They are collected in SPLIT_CODES_EXCLUDED.

Transitive-closure rule:
    A code may be renumbered across multiple waves (e.g. 0111 → 3011 in 2020,
    then 3011 → 3110 in 2024). KLASS records each hop separately. We resolve
    every old code to its TERMINAL successor at generation time via a
    cycle-guarded fixpoint, so the emitted table maps 0111 → 3110 directly and
    no emitted VALUE is itself a KEY (fully resolved). Codes that resolve into
    a split mid-chain are dropped (no single terminal successor).
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
    ("2023-12-31", "2024-01-02"),
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
    """Build the resolved 1-to-1 merger table and the excluded-splits dict.

    A *split* is an old code that maps to 2+ DISTINCT new codes WITHIN A SINGLE
    wave (same ``changeOccurred`` date) — attribution to one successor is
    impossible. A code that changes once per wave across several waves
    (0111→3011 in 2020, then 3011→3110 in 2024) is a *chain*, not a split, and
    is resolved transitively below.
    """
    # Per-wave hops, keyed by (oldCode, changeOccurred) → set of newCodes.
    by_old_wave: dict[tuple[str, str], set[str]] = defaultdict(set)
    name_of: dict[str, str] = {}      # newCode → newName (last seen wins)
    hop: dict[str, tuple[str, str]] = {}  # oldCode → (newCode, changeOccurred)

    for c in changes:
        old, new = c["oldCode"], c["newCode"]
        dt = c["changeOccurred"]
        by_old_wave[(old, dt)].add(new)
        name_of[new] = c["newName"]

    # Genuine splits: 2+ distinct targets in the same wave.
    splits: dict[str, list[tuple]] = {}
    for (old, dt), targets in by_old_wave.items():
        if len(targets) > 1:
            splits.setdefault(old, [])
            for nc in sorted(targets):
                splits[old].append((nc, name_of.get(nc, ""), dt))

    split_codes = set(splits.keys())

    # Single-hop map (exclude self-renames and split sources). When a code has
    # one hop per wave across multiple waves, the later wave's hop is the one we
    # chain FROM its intermediate — captured because each hop's oldCode differs.
    raw_hops: dict[str, str] = {}
    for (old, dt), targets in by_old_wave.items():
        if old in split_codes:
            continue
        (new,) = tuple(targets)
        if old == new:
            continue  # self-referential: only the name changed
        # If the same oldCode appears in two waves (rare), keep the latest hop.
        if old in raw_hops and raw_hops[old] != new:
            prev_dt = hop[old][1]
            if dt <= prev_dt:
                continue
        raw_hops[old] = new
        hop[old] = (new, dt)

    # ── Transitive closure to terminal codes (cycle-guarded fixpoint) ─────────
    resolved: dict[str, str] = {}
    dropped_into_split: list[str] = []
    for old in raw_hops:
        seen = {old}
        cur = old
        terminal: str | None = None
        while True:
            nxt = raw_hops.get(cur)
            if nxt is None:
                terminal = cur  # cur is terminal (not itself a key)
                break
            if nxt in split_codes:
                # chain runs into a split: no single terminal successor
                terminal = None
                dropped_into_split.append(old)
                break
            if nxt in seen:
                raise ValueError(
                    f"cycle detected in KLASS chain starting at {old}: "
                    f"revisited {nxt} (seen={seen})"
                )
            seen.add(nxt)
            cur = nxt
        if terminal is not None and terminal != old:
            resolved[old] = terminal

    one_to_one: list[tuple] = []
    for old, terminal in resolved.items():
        # name + an effective_year derived from the FIRST hop of this chain
        first_dt = hop[old][1]
        one_to_one.append(
            (old, terminal, name_of.get(terminal, ""), first_dt)
        )
    one_to_one.sort(key=lambda x: x[0])

    if dropped_into_split:
        print(
            f"  Dropped {len(dropped_into_split)} code(s) whose chain ran into a "
            f"split: {sorted(set(dropped_into_split))}",
            file=sys.stderr,
        )

    # Post-conditions: fully resolved (no value is a key), no split source kept.
    values = {t for _, t, _, _ in one_to_one}
    keys = {k for k, _, _, _ in one_to_one}
    leaked = values & keys
    assert not leaked, f"closure incomplete: values that are also keys: {sorted(leaked)}"
    assert not (keys & split_codes), "split source leaked into one_to_one keys"

    return one_to_one, splits


def print_module_data(one_to_one: list[tuple], splits: dict) -> None:
    split_codes = sorted(splits.keys())
    # Build a readable split description
    split_desc_lines = []
    for k in split_codes:
        targets = ", ".join(f"{nc} ({nn})" for nc, nn, _ in splits[k])
        split_desc_lines.append(f"#   {k} -> {targets}")

    print("# ── GENERATED DATA — do not edit by hand ─────────────────────────────────")
    print("# Source: https://data.ssb.no/api/klass/v1/classifications/131/changes.json")
    print("# Query dates: 2017-12-31→2018-01-02 (2018), 2019-12-31→2020-01-02 (2020),")
    print("#              2023-12-31→2024-01-02 (2024 — Viken/Troms-Finnmark renumbering)")
    print("# Fetch date: 2026-06-12")
    print("# Split-exclusion rule: old codes mapping to 2+ new codes in one wave excluded.")
    print("# Chains resolved transitively to terminal codes (0111→3110 directly).")
    print("# Regenerate with: uv run python scripts/regen_kommune_mergers.py")
    print()
    print(f"# Split codes excluded ({len(split_codes)} total):")
    for line in split_desc_lines:
        print(line)
    print()
    print("SPLIT_CODES_EXCLUDED: frozenset[str] = frozenset({")
    for k in split_codes:
        # find old name
        print(f'    {k!r},  # {splits[k][0][1]} / {splits[k][1][1]}', end="")
        if len(splits[k]) > 2:
            print(f' / {splits[k][2][1]}', end="")
        print()
    print("})")
    print()

    # ── MIXED_SOURCE_KNRS: terminal codes that are the target of BOTH a 1-to-1
    # closure AND an excluded split. Their pre-reform series covers only the
    # renamed predecessor, not the split portion → growth_pct would be
    # systematically inflated. Callers treat these as a discontinuous baseline.
    one_to_one_targets = {t for _, t, _, _ in one_to_one}
    split_targets = {nc for vs in splits.values() for nc, _, _ in vs}
    mixed = sorted(one_to_one_targets & split_targets)
    print("# Mixed-source new codes: target of BOTH a 1-to-1 rename AND a split.")
    print("# Pre-reform series covers only the renamed predecessor → inflated growth.")
    print("# Derived from KLASS (one_to_one targets ∩ split targets).")
    print("MIXED_SOURCE_KNRS: frozenset[str] = frozenset({")
    for k in mixed:
        print(f"    {k!r},  # {name_for(one_to_one, k)}")
    print("})")
    print()
    print(f"_ALL_CHANGES: list[MergerRecord] = [  # {len(one_to_one)} entries")
    for old_k, nc, nn, dt in one_to_one:
        yr = int(dt[:4])
        print(f"    MergerRecord({old_k!r}, {nc!r}, {nn!r}, {yr}),")
    print("]")


def name_for(one_to_one: list[tuple], code: str) -> str:
    """Return the municipality name for a terminal code from the table."""
    for _, nc, nn, _ in one_to_one:
        if nc == code:
            return nn
    return ""


if __name__ == "__main__":
    print("Fetching KLASS classification 131 changes...", file=sys.stderr)
    changes = fetch_changes()
    print(f"Total raw changes: {len(changes)}", file=sys.stderr)
    one_to_one, splits = build_table(changes)
    print(f"One-to-one (non-self): {len(one_to_one)}", file=sys.stderr)
    print(f"Splits excluded: {sorted(splits.keys())}", file=sys.stderr)
    print()
    print_module_data(one_to_one, splits)
