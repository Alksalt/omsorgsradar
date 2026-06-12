---
name: add-dataset
description: Koble en ny åpen data-API eller fil inn i pipelinen — inspiser API-formen med ÉN prøvespørring, skriv en [[sources]]-blokk for en eksisterende adapter, eller skaff ny adapter-modul + offline fixture + known-value-test etter G1-mønsteret. Use when the owner says "/add-dataset <url>" or asks to wire in a new data source/API.
---

# /add-dataset <api-url>

## Hard rules

- **Never edit an existing adapter's behavior** for a new dataset
  (DECISIONS.md). New API shape = new module.
- Every new adapter ships with: offline fixture captured from the REAL API,
  a known-value test pinning real printed literals (never invented numbers),
  and a `@pytest.mark.live` test. `sotkanet.py` and `kolada.py` are the
  cleanest templates to copy.
- Output is a commit-ready diff; the owner reviews and commits.

## Flow

1. **Classify:** `classify_pointer('<url>')` (see /magic-analyze step 1).
   Known adapter → just write the `[[sources]]` block per `docs/adapters.md`,
   check it with `--validate-only`, add a row to `docs/dataset-registry.md`,
   done — no code.
2. **Unknown shape:** make ONE small sample call (curl, a few KB). Identify:
   JSON-stat2 (→ `pxweb` likely covers it)? Flat JSON rows? Paginated
   (response-supplied next-links MUST be host-pinned — copy the kolada/
   socialstyrelsen guard)? Document the exact request/response shape in the
   new module docstring with today's date, exactly like the existing adapters.
3. **New adapter checklist** (G1 pattern, in order):
   - `src/omsorgsradar/core/adapters/<name>.py` — use `JsonCache`,
     `DEFAULT_TIMEOUT`; geographic data emits the tidy contract
     (`country, geo_code, geo_id, geo_name, aar, indicator, value`,
     `geo_id` via `core/geo.py` where NO/SE/FI).
   - Register: `REQUIRED_SOURCE_FIELDS` + factory + `ADAPTER_FACTORIES` in
     `core/adapters/__init__.py`; host into `ALLOWED_BASE_URL_HOSTS`;
     `realness.py` `KNOWN_HOSTS` + `ADAPTER_PROVENANCE`.
   - Fixture capture script run once; paste the printed literals into the
     known-value test.
   - Tests: seeded-cache offline (unreachable `base_url`), known-value,
     registry/provenance, live-marked.
   - Docs: section in `docs/adapters.md` + row in `docs/dataset-registry.md`.
4. **Prove it:** `uv run pytest -q` green and the new live test green
   (`uv run pytest tests/core/test_<name>_adapter.py -m live -q`).
   Present the diff to the owner.
