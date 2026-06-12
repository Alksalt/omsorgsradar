import pandas as pd
from omsorgsradar.core.anonymize.kanon import generalize, k_suppress, KAnonResult

def _df():
    return pd.DataFrame({
        "state": ["06"]*8 + ["48"]*2,
        "age":   [20,21,22,23,24,25,26,27, 80, 81],
        "sex":   [1]*10,
        "diabetes": [0,1,0,0,1,0,0,1, 1, 0],
    })

CFG = {"quasi_identifiers": ["state","age","sex"], "sensitive": "diabetes", "k": 5,
       "generalize": {"age": {"bins":[18,30,45,60,75,200],
                              "labels":["18-29","30-44","45-59","60-74","75+"]}}}

class TestGeneralize:
    def test_age_binned(self):
        g = generalize(_df(), CFG)
        assert set(g["age"]) <= {"18-29","75+"}

class TestSuppress:
    def test_small_classes_dropped(self):
        res = k_suppress(generalize(_df(), CFG), CFG)
        assert isinstance(res, KAnonResult)
        # state 48 / 75+ class has 2 < k=5 -> suppressed; state 06 / 18-29 has 8 >= 5 -> kept
        assert res.min_class_size >= 5
        assert res.n_suppressed == 2
        assert len(res.frame) == 8
    def test_suppression_rate_reported(self):
        res = k_suppress(generalize(_df(), CFG), CFG)
        assert abs(res.suppression_rate - 0.2) < 1e-9
    def test_empty_after_suppression_is_safe(self):
        cfg = dict(CFG); cfg["k"] = 100
        res = k_suppress(generalize(_df(), cfg), cfg)
        assert len(res.frame) == 0
        assert res.min_class_size == 0
        assert res.n_classes == 0
