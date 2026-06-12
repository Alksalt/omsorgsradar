"""The data-read hook: row-level data never enters model context."""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block_raw_data_reads.py"


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestHook:
    def test_blocks_cache_read(self) -> None:
        p = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "data/cache/12209.json"}}
        )
        assert p.returncode == 2
        assert "row-level" in p.stderr

    def test_blocks_duckdb_read(self) -> None:
        p = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "data/omsorgsradar.duckdb"}}
        )
        assert p.returncode == 2

    def test_blocks_grep_in_cache(self) -> None:
        p = _run_hook({"tool_name": "Grep", "tool_input": {"path": "data/cache"}})
        assert p.returncode == 2

    def test_allows_findings_read(self) -> None:
        p = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "data/findings.json"}}
        )
        assert p.returncode == 0

    def test_allows_other_tools(self) -> None:
        p = _run_hook({"tool_name": "Bash", "tool_input": {"command": "ls data/cache"}})
        assert p.returncode == 0

    def test_garbage_input_does_not_crash_open(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(HOOK)], input="not json", capture_output=True,
            text=True, timeout=10,
        )
        assert proc.returncode == 0  # fail-open for malformed harness input

    def test_microdata_path_blocked(self) -> None:
        p = _run_hook(
            {"tool_name": "Read", "tool_input": {"file_path": "analyses/brfss-demo/microdata/raw.csv"}}
        )
        assert p.returncode == 2
