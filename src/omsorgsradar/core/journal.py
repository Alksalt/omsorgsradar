"""Per-run journal: ``runs/<run-id>/run.json``.

Flushed after every mutation so a crashed run still leaves a readable record.
File-based by design (see DECISIONS.md — no vector/graph memory).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunJournal:
    run_dir: Path
    record: dict[str, Any]

    @classmethod
    def start(
        cls,
        runs_dir: Path,
        *,
        analysis: str,
        config_snapshot: dict[str, Any] | None = None,
    ) -> "RunJournal":
        run_id = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + analysis
        )
        run_dir = Path(runs_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "run_id": run_id,
            "analysis": analysis,
            "started_at": _utcnow(),
            "status": "running",
            "config": config_snapshot or {},
            "stages": [],
        }
        journal = cls(run_dir=run_dir, record=record)
        journal._flush()
        return journal

    def record_stage(
        self,
        stage: str,
        *,
        artifacts: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        duration_s: float | None = None,
    ) -> None:
        self.record["stages"].append(
            {
                "stage": stage,
                "finished_at": _utcnow(),
                "duration_s": duration_s,
                "artifacts": list(artifacts or []),
                "meta": meta or {},
            }
        )
        self._flush()

    def finalize(self, status: str = "ok") -> None:
        self.record["status"] = status
        self.record["finished_at"] = _utcnow()
        self._flush()

    def _flush(self) -> None:
        (self.run_dir / "run.json").write_text(
            json.dumps(self.record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
