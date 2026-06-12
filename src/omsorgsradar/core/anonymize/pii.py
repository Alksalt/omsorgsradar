"""Norwegian PII detection + redaction over Presidio.

Direct-identifier recognizers are pure regex + checksum (offline, deterministic).
Free-text name/location NER via spaCy nb_core_news_lg is OPTIONAL and loaded
lazily only when a spacy_model is passed (live tests only — the offline suite
never downloads the 568 MB model; it uses spacy.blank("nb"), tokenizer-only).
"""
from __future__ import annotations

from typing import Sequence
import pandas as pd

import spacy
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

LANG = "nb"  # Norwegian Bokmål — spacy.blank("nb") + live nb_core_news_lg both use this

_FNR_K1_W = [3, 7, 6, 1, 8, 9, 4, 5, 2]
_FNR_K2_W = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]

def _control_digit(digits: list[int], weights: list[int]) -> int | None:
    s = sum(d * w for d, w in zip(digits, weights))
    k = 11 - (s % 11)
    if k == 11:
        return 0
    if k == 10:
        return None
    return k

def valid_fnr_checksum(fnr: str) -> bool:
    if len(fnr) != 11 or not fnr.isdigit():
        return False
    d = [int(c) for c in fnr]
    k1 = _control_digit(d[:9], _FNR_K1_W)
    k2 = _control_digit(d[:10], _FNR_K2_W)
    return k1 is not None and k2 is not None and k1 == d[9] and k2 == d[10]

def append_fnr_control_digits(stem9: str) -> str:
    """Append valid control digits to a 9-digit stem (DDMMYY+individ). Used by
    tests AND fixtures — never hardcode a magic fnr."""
    d = [int(c) for c in stem9]
    k1 = _control_digit(d, _FNR_K1_W)
    if k1 is None:
        raise ValueError("stem yields invalid k1; pick another individ number")
    k2 = _control_digit(d + [k1], _FNR_K2_W)
    if k2 is None:
        raise ValueError("stem yields invalid k2; pick another individ number")
    return stem9 + str(k1) + str(k2)

class _FnrRecognizer(PatternRecognizer):
    """11 consecutive digits that pass the mod-11 checksum (fnr or D-nummer)."""
    def __init__(self) -> None:
        super().__init__(
            supported_entity="NO_FODSELSNUMMER",
            patterns=[Pattern("fnr-11d", r"\b\d{11}\b", 0.3)],
            name="NoFodselsnummerRecognizer",
            supported_language=LANG,
        )
    def validate_result(self, pattern_text: str):
        return True if valid_fnr_checksum(pattern_text) else False

def _phone_recognizer() -> PatternRecognizer:
    # (?<!\d) / (?!\d) prevent matching digit substrings inside longer runs (e.g.
    # the 8-digit alt inside an 11-digit fnr). Without word boundaries on both sides
    # the 8-digit branch fires on any prefix of a longer digit sequence.
    return PatternRecognizer(
        supported_entity="NO_TELEFON",
        patterns=[Pattern("no-phone", r"(?<!\d)(\+47[\s]?)?(\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}|\d{3}[\s]?\d{2}[\s]?\d{3})(?!\d)", 0.4)],
        name="NoTelefonRecognizer",
        supported_language=LANG,
    )

def _konto_recognizer() -> PatternRecognizer:
    # Require at least one separator (. or space) so bare 11-digit runs (fnr/d-nummer)
    # are not mistaken for a kontonummer. Format: NNNN.NN.NNNNN or NNNN NN NNNNN.
    return PatternRecognizer(
        supported_entity="NO_KONTONUMMER",
        patterns=[Pattern("no-konto", r"\b\d{4}[.\s]\d{2}[.\s]\d{5}\b", 0.3)],
        name="NoKontonummerRecognizer",
        supported_language=LANG,
    )

class _BlankSpacyNlpEngine(SpacyNlpEngine):
    """Tokenizer-only spaCy pipeline — real NlpArtifacts, NO model download,
    empty NER. The OFFLINE path: pattern recognizers fire, names not detected."""
    def __init__(self, lang: str = LANG) -> None:
        super().__init__(models=[{"lang_code": lang, "model_name": "blank"}])
        self.nlp = {lang: spacy.blank(lang)}

def build_analyzer(spacy_model: str | None = None) -> AnalyzerEngine:
    registry = RecognizerRegistry(supported_languages=[LANG])
    registry.add_recognizer(_FnrRecognizer())
    registry.add_recognizer(_phone_recognizer())
    registry.add_recognizer(_konto_recognizer())
    if spacy_model:
        nlp = SpacyNlpEngine(models=[{"lang_code": LANG, "model_name": spacy_model}])
    else:
        nlp = _BlankSpacyNlpEngine(LANG)
    return AnalyzerEngine(registry=registry, nlp_engine=nlp, supported_languages=[LANG])

def scan_pii(df: pd.DataFrame, columns: Sequence[str], spacy_model: str | None = None) -> pd.DataFrame:
    """Per-row PII scan over the named columns. Returns a frame indexed like df
    with n_entities (int) + entity_types (sorted unique list) per row. No raw
    values returned."""
    analyzer = build_analyzer(spacy_model)
    rows = []
    for _, row in df.iterrows():
        types, n = set(), 0
        for col in columns:
            text = "" if pd.isna(row.get(col)) else str(row[col])
            res = analyzer.analyze(text=text, language=LANG)
            n += len(res)
            types.update(r.entity_type for r in res)
        rows.append({"n_entities": n, "entity_types": sorted(types)})
    return pd.DataFrame(rows, index=df.index)

def redact_pii(df: pd.DataFrame, columns: Sequence[str], spacy_model: str | None = None) -> tuple[pd.DataFrame, int]:
    """Replace detected entities with <ENTITY_TYPE> in the named columns.
    Returns (redacted_copy, total_entities_redacted)."""
    analyzer = build_analyzer(spacy_model)
    anonymizer = AnonymizerEngine()
    out = df.copy()
    total = 0
    for col in columns:
        new_vals = []
        for v in out[col]:
            text = "" if pd.isna(v) else str(v)
            res = analyzer.analyze(text=text, language=LANG)
            total += len(res)
            if res:
                operators = {r.entity_type: OperatorConfig("replace",
                            {"new_value": f"<{r.entity_type}>"}) for r in res}
                text = anonymizer.anonymize(text=text, analyzer_results=res, operators=operators).text
            new_vals.append(text)
        out[col] = new_vals
    return out, total
