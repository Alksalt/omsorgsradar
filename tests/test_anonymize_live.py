"""Live spaCy NER for the anonymize stage.

Marked ``live``: requires the Norwegian model ``nb_core_news_lg`` (~568 MB,
``uv run python -m spacy download nb_core_news_lg``). The offline suite uses
``spacy.blank("nb")`` (tokenizer only) and never exercises NER — this test
covers the optional name/location detection path.
"""

from __future__ import annotations

import pandas as pd
import pytest

MODEL = "nb_core_news_lg"


def _model_available() -> bool:
    try:
        import spacy

        spacy.load(MODEL)
        return True
    except Exception:
        return False


@pytest.mark.live
@pytest.mark.skipif(not _model_available(), reason=f"{MODEL} not installed")
class TestSpacyNer:
    def test_person_name_detected_and_redacted(self) -> None:
        from omsorgsradar.core.anonymize.pii import redact_pii, scan_pii

        df = pd.DataFrame({"notes": ["Pasienten Kari Nordmann ble innlagt i Bergen."]})
        hits = scan_pii(df, columns=["notes"], spacy_model=MODEL)
        assert "PERSON" in hits.loc[0, "entity_types"]

        out, n = redact_pii(df, columns=["notes"], spacy_model=MODEL)
        assert "Kari Nordmann" not in out.loc[0, "notes"]
        assert n >= 1
