"""Anonymize subpackage: PII redaction, k-anonymization, WP216 risk receipts."""
from .pii import scan_pii, redact_pii, valid_fnr_checksum, append_fnr_control_digits  # noqa: F401
