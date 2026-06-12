import pandas as pd
from omsorgsradar.core.anonymize.kanon import generalize, k_suppress
from omsorgsradar.core.anonymize.risk import assess_identifiability

CFG = {"quasi_identifiers": ["state","age","sex"], "sensitive": "diabetes", "k": 5,
       "generalize": {"age": {"bins":[18,30,45,60,75,200],
                              "labels":["18-29","30-44","45-59","60-74","75+"]}},
       "thresholds": {"l_min": 2, "inference": 0.5, "linkability": 0.0}}

def _bigdf():
    import numpy as np
    rng = np.random.default_rng(0)
    n = 200
    return pd.DataFrame({
        "state": rng.choice(["06","48","36"], n),
        "age": rng.integers(18, 90, n),
        "sex": rng.integers(1, 3, n),
        "diabetes": rng.integers(0, 2, n),
    })

class TestAssess:
    def test_passes_after_ksuppress(self):
        res = k_suppress(generalize(_bigdf(), CFG), CFG)
        rep = assess_identifiability(res, generalize(_bigdf(), CFG), CFG)
        assert rep["singling_out"]["min_class_size"] >= 5
        assert rep["singling_out"]["verdict"] == "PASS"
        assert rep["verdict"] in {"PASS", "WARN"}
        assert "singling-out" in rep["criteria_ref"]

    def test_homogeneous_sensitive_flags_inference(self):
        df = _bigdf()
        df["diabetes"] = 1                      # every class fully homogeneous
        res = k_suppress(generalize(df, CFG), CFG)
        rep = assess_identifiability(res, generalize(df, CFG), CFG)
        assert rep["inference"]["min_l_diversity"] == 1
        assert rep["inference"]["verdict"] == "FAIL"
        assert rep["verdict"] == "FAIL"

    def test_empty_release_skips_inference(self):
        cfg = dict(CFG); cfg["k"] = 100000
        res = k_suppress(generalize(_bigdf(), cfg), cfg)
        rep = assess_identifiability(res, generalize(_bigdf(), cfg), cfg)
        assert rep["inference"]["verdict"] == "SKIP"
        assert rep["singling_out"]["verdict"] == "FAIL"  # min_class_size 0 < k
