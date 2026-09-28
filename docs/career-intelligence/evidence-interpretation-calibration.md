# Generic evidence interpretation calibration

Date: 2026-09-26. Assessment semantics remain v4; new explanations carry
`evidence_interpretation_version: 1`. This is an offline diagnostic, not a
publication-approved reassessment preview.

## Confirmed causes and corrections

1. Capability and role-keyword matching previously searched entire descriptions.
   Employer introductions could supply product ownership and direct leadership
   anchors. The new source-independent section parser separates employer context,
   responsibilities, required qualifications, preferred qualifications and benefits.
   It handles plain text and HTML, including common English/German headings.
   Employer context still supplies market/domain relevance, explicitly reported as
   `employer_context_matches`; it does not supply direct capability matches.
   Collaboration/delivery words alone do not establish technical-program ownership.
2. Mandatory specialist coverage omitted regulatory/legal programs, emergency
   response and automotive diagnostics. Explicit required sections/clauses now
   detect these practices and specialist tenure. Preferred/optional qualifications
   are excluded; a preferred certificate in parentheses does not negate a mandatory
   practice requirement. Existing mandatory core checks also use role-scoped text.
   Generic licensed-practice requirements are supported without guessing credentials.
   Candidate practice must be documented under the relevant capability; numeric
   tenure additionally needs sufficient `professional_years`. Planned/unknown
   evidence cannot satisfy a requirement. Program leadership cannot substitute.
3. The Silver adapter previously omitted location from assessment inputs. The optional
   `structured_location` object (`name`, `source`) now flows through the adapter,
   assessor, constraints and saved evidence snapshot. Captured provider location is
   preferred, with Silver city/country fallback. Reassessment preserves an existing
   location snapshot; historical inputs lacking that field use validated source
   metadata. Malformed saved location evidence blocks reassessment.
   Workplace evidence distinguishes Berlin, Munich, Germany-wide, remote and unknown.
   Munich hybrid/in-person attendance conflicts with Berlin-based circumstances;
   Munich without an attendance arrangement remains unknown. Stakeholder-city
   references cannot supply Berlin preference. No relocation claim is invented.
4. Travel percentages were previously treated alike. `travel_details` now preserves
   ceiling, approximate, minimum, expected and frequent qualifiers, percentages,
   source wording and domestic/European/international scope. A ceiling alone remains
   unknown. Explicit frequent travel and expected/minimum travel at the existing
   threshold retain the practical gate. Travel does not alter candidacy weights.

No strategic allocation, company priority, network scoring or candidacy weights
were changed. The existing mandatory-gap cap determines the new totals below.

## Three saved Waymo assessments: offline comparison

The public captured descriptions are retained in
`tests/fixtures/career_intelligence/waymo_evidence_interpretation_v1.json`, with
provider IDs, Silver/Bronze IDs and description SHA-256 values. They were read from
the database in a read-only transaction. Current vacancy availability was not checked.

Dimensions are lane / capability / domain / evidence / location / network.

| Role | Previous score/action | Diagnostic score/action | Previous dimensions | Diagnostic dimensions |
|---|---|---|---|---|
| Program Manager, Germany Regulatory | 83.5 / WATCH | 40 / SKIP | 85 / 86.7 / 85 / 78.3 / 60 / 30 | 85 / 95 / 85 / 88.5 / 0 / 30 |
| Emergency Services Liaison, Germany | 75 / SKIP | 40 / SKIP | 75 / 86.7 / 85 / 75 / 0 / 30 | 75 / 95 / 85 / 88.5 / 0 / 30 |
| Lead Diagnostic Technician | 83.5 / SKIP | 40 / SKIP | 85 / 86.7 / 85 / 78.3 / 0 / 30 | 75 / 100 / 85 / 90 / 0 / 30 |

- Regulatory: genuine program leadership remains directly recognized. Required
  experience leading large Regulatory/Legal programs is not documented. Structured
  Munich location plus hybrid schedule supplies the presence conflict. Travel is unknown.
- Liaison: required 15+ years in German emergency services and emergency-response
  expertise are not documented. Munich hybrid location and approximately 20% domestic
  and international travel are recognized. Berlin stakeholder names give no preference.
- Technician: automotive technician/engineering tenure, diagnostics mastery and
  electric/hybrid vehicle servicing are explicit specialist gaps. Project coordination
  is transferable, not direct technical-program ownership. The role is in person in
  Munich. Up to 20% travel is an upper bound, not established frequent travel.

The capability/evidence sub-scores rise when weak boilerplate matches are removed:
the existing formula averages the remaining matched capabilities, rather than
measuring mandatory-requirement coverage. The explicit specialist gaps cap total
candidacy at 40. These sub-scores are not proof that specialist requirements are met.

Detailed local comparison (not an apply artifact):
`.runtime/career_intelligence/diagnostics/evidence-interpretation-2026-09-26/diagnostic.json`.
It includes saved identities, all dimensions, matched capabilities, requirements,
location/travel evidence and original production/historical file hashes.

## Historical regression comparison

Compared 95 fixture assessments across the retained historical input versions and
the three earlier leadership examples. No total score or recommendation changed.
Eight versioned entries (CARIAD's strict and bridge variants across historical
versions) change evidence strength from 75 to 70: generic delivery words now receive
transferable rather than direct technical-program credit. Other final scoring
dimensions are unchanged. Explicit `Berlin/hybrid` and German `internationale`
role responsibilities remain recognized.

All original fixtures are byte-for-byte unchanged, including original v4 results.
The revised exact snapshot is a separate file:
`strategy_calibration.v4.interpretation1.results.json`.
Tests protect both the new snapshot and the original v4 manifest hashes.

## Files changed in this task

Existing changes from earlier tasks were preserved; they are not part of this list.

Production code under `src/career_intelligence/`:

- `role_text.py` (new), `capability_matcher.py`, `classifier.py`
- `specialist_requirements.py`, `assessor.py`
- `work_location.py` (new), `practical_constraints.py`, `location_matcher.py`, `constraints.py`
- `silver_adapter.py`, `ingest_silver.py`, `batch.py`
- `reassess.py`, `reassessment_evidence.py`

Tests under `tests/career_intelligence/`:

- `test_evidence_interpretation.py` (new)
- `test_ingest_silver.py`, `test_silver_adapter.py`, `test_reassess.py`
- `test_strategy_alignment.py`, `test_recommendation_semantics.py`

New fixtures under `tests/fixtures/career_intelligence/`:

- `waymo_evidence_interpretation_v1.json`
- `strategy_calibration.v4.interpretation1.results.json`

Documentation: this file. Local diagnostic output: the JSON path above.

## Validation and next step

Final relevant suite: **511 passed in 41.31 seconds; no failures**. Configuration
validation, changed-file Ruff and `git diff --check` pass. Production opportunities,
provenance and radar hashes match the starting snapshot, as do all original fixtures.

Relevant regression command (offline fixtures and temporary test directories only):

```sh
.venv/bin/python -m pytest -q tests/career_intelligence \
  tests/test_greenhouse_connector.py tests/test_waymo_controlled_preparation.py \
  tests/test_silver_transformer_canonicalization.py tests/test_controlled_activation_cap.py \
  tests/test_employer_origin_activation_readiness.py \
  tests/test_greenhouse_delegated_detail_repair.py \
  tests/test_employer_origin_acquisition_v4_greenhouse.py
.venv/bin/python scripts/validate_career_config.py
git diff --check
```

Changed-file Ruff also passes. One exploratory directory-wide Ruff check found a
pre-existing F541 in unchanged `moia_live_source.py:510`; it was left untouched.

A fresh controlled reassessment preview is recommended for review before any
publication. This diagnostic is deliberately not publication-eligible and cannot
be passed to apply. Existing previews must not be reused: controlled reassessment
fingerprints include the changed interpretation code. No production assessment,
source activation, ingestion, commit or push was performed.

The parser is deterministic, not an exhaustive understanding of every job layout.
Unrecognized unstructured historical text remains usable; unknown location/travel
and unsupported specialist evidence remain reviewable rather than invented.
