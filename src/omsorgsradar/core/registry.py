"""Stage registry + execution context + instance extension point.

An *analysis instance* may ship ``analyses/<name>/stages.py`` exposing
``register(registry)``; its registrations (with ``override=True``) shadow core
stages for that analysis only. Core is never edited for a variant
(DECISIONS.md). Hard rule enforced here: ``verify`` always precedes
``report`` regardless of what the config says.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import RunConfig
from .journal import RunJournal


class StageNotFoundError(KeyError):
    """Requested stage is not registered."""


class PipelineGateError(RuntimeError):
    """A hard gate (verification) failed — downstream stages must not run."""


@dataclass
class StageContext:
    """Everything a stage may touch. Stages communicate via ``state``
    (in-memory, this run only) and ``artifacts`` (files, source of truth)."""

    config: RunConfig
    data_dir: Path
    reports_dir: Path
    journal: RunJournal
    state: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)


StageFn = Callable[[StageContext], None]


class StageRegistry:
    def __init__(self) -> None:
        self._stages: dict[str, StageFn] = {}

    def register(self, name: str, fn: StageFn, *, override: bool = False) -> None:
        if name in self._stages and not override:
            raise ValueError(
                f"stage '{name}' already registered — pass override=True to shadow it"
            )
        self._stages[name] = fn

    def get(self, name: str) -> StageFn:
        try:
            return self._stages[name]
        except KeyError:
            raise StageNotFoundError(
                f"unknown stage '{name}' (known: {sorted(self._stages)})"
            ) from None


def resolve_stage_list(stages: list[str]) -> list[str]:
    """Return the stage list with the verify-before-report rule enforced."""
    out = list(stages)
    if "report" in out:
        if "verify" in out:
            out.remove("verify")
        out.insert(out.index("report"), "verify")
    return out


def load_extensions(analysis_dir: Path, registry: StageRegistry) -> bool:
    """Import ``<analysis_dir>/stages.py`` (if present) and let it register.

    Returns True if an extension module was loaded.
    """
    ext = Path(analysis_dir) / "stages.py"
    if not ext.exists():
        return False
    spec = importlib.util.spec_from_file_location(
        f"omsorgsradar_ext_{Path(analysis_dir).name}", ext
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register", None)
    if not callable(register):
        raise ValueError(f"{ext} must define register(registry)")
    register(registry)
    return True
