"""k-anonymity by full-domain generalization + record suppression.

Generalization hierarchies come entirely from [params.anonymize].generalize —
no hardcoded bins. Equivalence classes smaller than k on the quasi-identifiers
are suppressed (dropped); stats are returned for the identifiability receipt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import pandas as pd

@dataclass
class KAnonResult:
    frame: pd.DataFrame          # k-anonymized rows (generalized QIs + sensitive)
    quasi_identifiers: list[str]
    k: int
    min_class_size: int
    n_input: int
    n_suppressed: int
    suppression_rate: float
    n_classes: int

    def n_suppressed_below_k_zero(self) -> bool:
        """True iff every released class meets k (min_class_size >= k)."""
        return self.min_class_size >= self.k

def generalize(df: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.DataFrame:
    out = df.copy()
    gen = dict(cfg.get("generalize", {}))
    for col, spec in gen.items():
        if "bins" in spec:                       # numeric -> labelled band
            out[col] = pd.cut(pd.to_numeric(out[col], errors="coerce"),
                              bins=list(spec["bins"]), labels=list(spec["labels"]),
                              right=False, include_lowest=True).astype("object")
        elif "map" in spec:                      # categorical -> coarser category
            out[col] = out[col].map(dict(spec["map"])).fillna(out[col])
    return out

def k_suppress(df: pd.DataFrame, cfg: Mapping[str, Any]) -> KAnonResult:
    qis = list(cfg["quasi_identifiers"])
    k = int(cfg["k"])
    # Fill NaN sentinels before groupby so dropna=False isn't needed on object columns
    # (avoids pandas 3 quirks with categorical/object NaN in transform).
    _SENTINEL = "__NA__"
    work = df.copy()
    for col in qis:
        if work[col].dtype == object or str(work[col].dtype) == "category":
            work[col] = work[col].fillna(_SENTINEL)
    class_size = work.groupby(qis)[qis[0]].transform("size")
    keep = class_size >= k
    kept = df[keep].copy()
    n_input = len(df)
    n_suppressed = int((~keep).sum())
    if len(kept):
        work_kept = kept.copy()
        for col in qis:
            if work_kept[col].dtype == object or str(work_kept[col].dtype) == "category":
                work_kept[col] = work_kept[col].fillna(_SENTINEL)
        surviving = work_kept.groupby(qis)[qis[0]].transform("size")
        min_class = int(surviving.min())
        n_classes = int(work_kept.groupby(qis).ngroups)
    else:
        min_class = 0
        n_classes = 0
    return KAnonResult(
        frame=kept.reset_index(drop=True),
        quasi_identifiers=qis,
        k=k,
        min_class_size=min_class,
        n_input=n_input,
        n_suppressed=n_suppressed,
        suppression_rate=round(n_suppressed / n_input, 6) if n_input else 0.0,
        n_classes=n_classes,
    )
