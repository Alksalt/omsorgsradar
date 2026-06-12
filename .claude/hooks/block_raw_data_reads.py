#!/usr/bin/env python3
"""PreToolUse hook: deny model-context access to row-level data.

DECISIONS.md: the LLM orchestrates code; code touches data; only schemas,
profiles, and aggregates enter model context. Blocks Read/Grep on raw API
caches and DuckDB files. Aggregate artifacts (findings.json,
quality_profile.json, verification.json, reports) stay readable.
Stdlib only — runs under any python3 without the project venv.

NOT a security boundary: Bash/cat bypass this by design, and it fails open.
Purpose is to keep row-level data out of *model context* by accident, nothing more.
"""

import json
import re
import sys

BLOCKED_PATTERNS = [
    r"(^|/)data/cache(/|$)",
    r"\.duckdb$",
    r"(^|/)microdata(/|$)",
]

MESSAGE = (
    "Blocked: row-level data must not enter model context (DECISIONS.md). "
    "Use the profile stage output (data/quality_profile.json) or DuckDB "
    "aggregate queries via Bash instead."
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail-open on malformed input; never brick the session
    if payload.get("tool_name") not in ("Read", "Grep"):
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}
    target = str(tool_input.get("file_path") or tool_input.get("path") or "")
    if any(re.search(p, target) for p in BLOCKED_PATTERNS):
        print(MESSAGE, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
