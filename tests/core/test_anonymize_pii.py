import pandas as pd
import pytest
from omsorgsradar.core.anonymize.pii import (
    valid_fnr_checksum, append_fnr_control_digits, scan_pii, redact_pii,
)

def _make_fnr(stem9: str) -> str:
    return append_fnr_control_digits(stem9)

# "010190100" — DDMMYY=010190 (01 Jan 1990), individ=100 — yields valid k1 and k2
_STEM = "010190100"

class TestChecksum:
    def test_appended_control_digits_validate(self):
        fnr = _make_fnr(_STEM)
        assert len(fnr) == 11
        assert valid_fnr_checksum(fnr)

    def test_wrong_checksum_rejected(self):
        # Take the valid fnr, flip the last digit — must fail
        fnr = _make_fnr(_STEM)
        bad = fnr[:-1] + str((int(fnr[-1]) + 1) % 10)
        assert not valid_fnr_checksum(bad)

class TestScan:
    def test_detects_valid_fnr_only(self):
        good = _make_fnr(_STEM)
        # Row 1: plain text — no digit sequences that could match fnr/phone/konto.
        # Note: "00000000000" is NOT used here because all-zeros actually passes the
        # mod-11 checksum (sum=0 → k=11→0, matching d[9]=d[10]=0). That is a
        # mathematically correct outcome, not a bug; the test row must be truly PII-free.
        df = pd.DataFrame({"notes": [f"pasient {good}", "ringte ingen PII her"]})
        hits = scan_pii(df, columns=["notes"])
        assert hits.loc[0, "n_entities"] >= 1
        assert "NO_FODSELSNUMMER" in hits.loc[0, "entity_types"]
        assert hits.loc[1, "n_entities"] == 0

    def test_phone_detected(self):
        df = pd.DataFrame({"t": ["tlf +47 911 23 456"]})
        hits = scan_pii(df, columns=["t"])
        assert "NO_TELEFON" in hits.loc[0, "entity_types"]

class TestRedact:
    def test_redacts_fnr_in_place(self):
        good = _make_fnr(_STEM)
        df = pd.DataFrame({"notes": [f"pasient {good} innlagt"]})
        out, n = redact_pii(df, columns=["notes"])
        assert good not in out.loc[0, "notes"]
        assert "<NO_FODSELSNUMMER>" in out.loc[0, "notes"]
        assert n == 1


class TestSpacyModelAllowlist:
    """spacy.load executes model code → spacy_model must be an allowlisted name,
    never a path (machine-authored-config security gate, mirrors G3 host allowlist)."""

    def test_path_or_unknown_model_rejected(self):
        from omsorgsradar.core.anonymize.pii import build_analyzer

        with pytest.raises(ValueError, match="not allowlisted"):
            build_analyzer(spacy_model="../evil/model")
        with pytest.raises(ValueError, match="not allowlisted"):
            build_analyzer(spacy_model="en_core_web_lg")

    def test_offline_blank_path_constructs(self):
        from omsorgsradar.core.anonymize.pii import build_analyzer

        assert build_analyzer() is not None  # no model → spacy.blank, no download
