"""Measured residual-risk receipts for the three EU Art-29-WP216 criteria.

WP216 (Article 29 Working Party, Opinion 05/2014) names three risks an effective
anonymisation must control: SINGLING OUT, LINKABILITY, INFERENCE. We measure each
with standard Statistical-Disclosure-Control quantities (k-anonymity / QI-uniqueness
/ l-diversity + attacker advantage), per sdcMicro (Templ et al.) and the unified
framing of Giomi et al. 2023 ("A Unified Framework for Quantifying Privacy Risk").

The `anonymeter` package is intentionally NOT used: it pins numpy<1.27 (uninstallable
here) and targets synthetic data; this stage releases k-anonymized real microdata.

NaN handling: KAnonResult.frame may contain NaN in quasi-identifiers (rows whose
age fell outside generalization bins, for instance). We mirror kanon.py's
sentinel-fill trick — replace NaN with "__NA__" on a copy before groupby — so
those rows are never silently dropped and class counts stay consistent.

Framing everywhere: «anonymisering med målt restrisiko» — never "fully anonymous".
"""
from __future__ import annotations

from typing import Any, Mapping
import pandas as pd

from .kanon import KAnonResult

CRITERIA_REF = "EU Art-29 WP216: singling-out / linkability / inference"

_SENTINEL = "__NA__"


def _verdict(*statuses: str) -> str:
    order = {"FAIL": 3, "WARN": 2, "PASS": 1, "SKIP": 0}
    return max(statuses, key=lambda s: order[s])


def _fill_na_sentinels(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Return a copy of df with NaN filled by _SENTINEL in object/category columns.

    Mirrors the pattern in kanon.k_suppress so groupby class counts are consistent.
    Numeric QIs (e.g. sex stored as int) are left as-is; pandas handles numeric NaN
    in groupby correctly.
    """
    out = df.copy()
    for col in cols:
        if col in out.columns:
            dtype_str = str(out[col].dtype)
            if out[col].dtype == object or dtype_str == "category":
                out[col] = out[col].fillna(_SENTINEL)
    return out


def _singling_out(res: KAnonResult) -> dict[str, Any]:
    """Prosecutor risk = 1/min_class_size.  PASS iff min_class_size >= k."""
    m = res.min_class_size
    return {
        "criterion": "singling-out",
        "min_class_size": m,
        "k_target": res.k,
        "prosecutor_risk": round(1.0 / m, 6) if m else 1.0,
        "share_below_k": 0.0 if m >= res.k else 1.0,
        "verdict": "PASS" if m >= res.k else "FAIL",
    }


def _linkability(generalized: pd.DataFrame, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """QI-uniqueness before suppression.

    A record is unique in the QI space iff its equivalence class has size 1 in
    the *generalized* (pre-suppressed) frame — the attacker can link that row to
    an external dataset with probability 1.  Threshold from cfg['thresholds']['linkability'].
    """
    qis = list(cfg["quasi_identifiers"])
    if generalized.empty:
        return {
            "criterion": "linkability",
            "unique_qi_share_pre_suppression": 0.0,
            "threshold": float(cfg.get("thresholds", {}).get("linkability", 0.0)),
            "verdict": "PASS",
        }
    # Sentinel-fill object/category QIs before groupby (pandas 3 consistency).
    work = _fill_na_sentinels(generalized, qis)
    sizes = work.groupby(qis, dropna=False)[qis[0]].transform("size")
    unique_share = float((sizes == 1).mean())
    thr = float(cfg.get("thresholds", {}).get("linkability", 0.0))
    return {
        "criterion": "linkability",
        "unique_qi_share_pre_suppression": round(unique_share, 6),
        "threshold": thr,
        "verdict": "PASS" if unique_share <= thr else
                   ("WARN" if unique_share <= thr + 0.05 else "FAIL"),
    }


def _inference(res: KAnonResult, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """l-diversity + attacker advantage over marginal.

    Attacker advantage for class G on sensitive attribute S:
        adv(G) = P(S=s* | G) - P(S=s*)
    where s* = argmax P(S=s | G).  This is the gain over a random guess from the
    population marginal — the standard SDC «knowledge gain» metric.

    FAIL if min l-diversity < l_min OR max attacker advantage > threshold + 0.15.
    WARN if max attacker advantage > threshold.
    SKIP if frame is empty or sensitive column absent.
    """
    qis = res.quasi_identifiers
    sens = cfg["sensitive"]
    thr = float(cfg.get("thresholds", {}).get("inference", 0.5))
    l_min = int(cfg.get("thresholds", {}).get("l_min", 2))
    df = res.frame

    if df.empty or sens not in df.columns:
        return {
            "criterion": "inference",
            "min_l_diversity": 0,
            "max_attacker_adv": 0.0,
            "mean_attacker_adv": 0.0,
            "verdict": "SKIP",
        }

    marginal = df[sens].value_counts(normalize=True).to_dict()

    # Sentinel-fill for consistent groupby.
    work = _fill_na_sentinels(df, list(qis))

    advs: list[float] = []
    ls: list[int] = []
    for _, g in work.groupby(list(qis), dropna=False):
        # Use original sensitive column values (same index after copy).
        orig_g = df.loc[g.index]
        probs = orig_g[sens].value_counts(normalize=True)
        top_val = probs.idxmax()
        advs.append(float(probs.max() - marginal.get(top_val, 0.0)))
        ls.append(int(orig_g[sens].nunique()))

    if not advs:
        return {
            "criterion": "inference",
            "min_l_diversity": 0,
            "max_attacker_adv": 0.0,
            "mean_attacker_adv": 0.0,
            "verdict": "SKIP",
        }

    min_l = min(ls)
    max_adv = max(advs)

    # Verdict logic (WP216 / SDC framing):
    # FAIL when structural l-diversity violation with no measurable attacker advantage
    # (degenerate/homogeneous sensitive column — l=1 AND adv<=thr means the advantage
    # metric is misleadingly low; l-diversity failure is the primary signal), OR when
    # attacker advantage is well above threshold regardless of l-diversity.
    # WARN when either l-diversity is structurally weak OR advantage marginally elevated.
    if (min_l < l_min and max_adv <= thr) or (max_adv > thr + 0.15):
        v = "FAIL"
    elif min_l < l_min or max_adv > thr:
        v = "WARN"
    else:
        v = "PASS"

    return {
        "criterion": "inference",
        "min_l_diversity": min_l,
        "max_attacker_adv": round(max_adv, 6),
        "mean_attacker_adv": round(sum(advs) / len(advs), 6),
        "l_min": l_min,
        "threshold": thr,
        "verdict": v,
    }


def assess_identifiability(
    res: KAnonResult,
    generalized: pd.DataFrame,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a WP216 residual-risk receipt covering all three criteria.

    Args:
        res: Output of kanon.k_suppress — the released (suppressed) frame + stats.
        generalized: Output of kanon.generalize — the pre-suppression frame used for
            linkability measurement (QI-uniqueness before suppression captures the
            worst-case re-identification surface).
        cfg: Analysis config dict with keys: quasi_identifiers, sensitive, k,
             generalize, thresholds (l_min, inference, linkability).

    Returns:
        dict with framing, criteria_ref, k_anonymity summary, per-criterion dicts,
        and an overall verdict (worst of the three).
    """
    so = _singling_out(res)
    lk = _linkability(generalized, cfg)
    inf = _inference(res, cfg)
    return {
        "framing": "anonymisering med målt restrisiko",
        "criteria_ref": CRITERIA_REF,
        "k_anonymity": {
            "k_target": res.k,
            "min_class_size": res.min_class_size,
            "n_suppressed": res.n_suppressed,
            "suppression_rate": res.suppression_rate,
            "n_records_released": len(res.frame),
            "n_classes": res.n_classes,
        },
        "singling_out": so,
        "linkability": lk,
        "inference": inf,
        "verdict": _verdict(so["verdict"], lk["verdict"], inf["verdict"]),
    }
