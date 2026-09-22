# Career strategy calibration — final pass v3

Updated 2026-09-22. This replaces the earlier recommendation/scoring sections in this report.
[Historical v1 report](strategy-calibration-v1-2026-09-15.md) and
[v2 semantics](recommendation-semantics-v2.md) remain available for comparison.

## Exact rule changes

1. `opportunity_score` now means **current evidence-based candidacy**, after caps. It equals
   `candidate_strength.score`. The configured weighted dimensions are career-lane evidence
   20%, capability 30%, domain evidence 20%, and evidence strength 30%. Location and access
   remain visible dimensions with zero score weight; they are decision gates, not capability.
2. Strategic value is separate: `explanation.strategic_value` reports the aligned search lane,
   55/25/20 search allocation and role relevance. Allocation is a planning percentage, not a
   fit probability or bonus. No public schema-v1 field is removed. Strategy and score metadata
   live in the already backward-compatible `explanation` object, now `semantics_version: 3`.
   Old saved records keep their old meaning/version until an explicitly requested reassessment.
3. The former 85-point keyword floor is gone. Configuration allows an 85 **dimension anchor**
   only with documented professional role **and** domain capabilities matched to the role.
   Transferable/adjacent evidence has a 75 lane anchor and a total cap of 75. AI bridges remain
   adjacent even when automotive domain evidence is direct. Unknown role evidence caps at 30.
   Repeating keywords or increasing search priority cannot strengthen the evidence score.
4. Material commercial, technical, formal-PO, multi-year robotics and executive-ownership gaps
   cap current candidacy at 40 and require WATCH (or SKIP for exclusions). Specialist engineering
   and unsupported senior enterprise-AI leadership cap at 25 and remain SKIP. Hard constraints
   override candidacy: a strong fit for a role requiring Munich relocation is still SKIP.
5. APPLY requires candidacy >=65, evidence >=60, known compatible location, relevant role
   scope, and no material gap or overriding risk. Confirmed warm/direct access is adequate;
   cold access need not delay a verified customer/program deployment role. AMR APPLY additionally
   requires sourced confirmation that hands-on robotics engineering/commissioning is not core.
6. NETWORK FIRST requires candidacy >=60, evidence >=60, sufficient role relevance, compatible
   location, no blocking gap and cold access as the main actionable weakness. Referral,
   hiring-manager, internal-team, sponsor, warm-introduction and prior-working access prevent it.
   HERE-style solution/professional-services roles use a configurable cold-access review rule.
7. WATCH handles material gaps, unclear scope, unknown location, weak confirmed budget/hiring
   intent or an executive role still needing review. SKIP handles hard location constraints,
   excluded specialist roles, unrelated/seniority-inappropriate roles and decisive mismatches.
   No networking recommendation compensates for missing capability evidence.
8. Chief of Staff assessments inspect founder execution, company-building, finance, fundraising,
   commercial ownership and seniority separately. Unstated requirements remain unstated; domain
   keywords cannot establish company-building evidence. Financing/commercial/experience gaps
   remain explicit. Technical operating-execution variants can qualify for conditional networking.
9. Every assessment exposes weighted-before-cap candidacy, dimensions, cap, matched evidence,
   transition, access, blocking gaps and `explanation.gates`. Silver freshness retains a separate
   `freshness_ranking_score` and may downgrade action to WATCH; it does not alter v3 candidacy
   or create NETWORK FIRST. ATS identity-only inputs cannot establish candidate evidence.

## Named cases and scope integrity

- **dx.one:** confirmed role-specific employee referral retained. Formal multi-year PO evidence
  remains material: WATCH. Final-round history supplies no capability points or outcome leakage.
- **FREENOW:** real user-reported “very commercial heavy” feedback is sourced role evidence,
  separate from representative job text. Core commercial ownership is a capability gap: WATCH.
- **Robotics TPM:** technical program/deployment fixture reaches NETWORK FIRST with cold access,
  capped at 75. A separate fixture requiring multiple years of direct robotics-product experience
  reaches WATCH. Neither claims established professional robotics experience.
- **AMR:** original ambiguous scope is WATCH; sourced non-core engineering/commissioning scope
  yields APPLY. Linux commissioning, robot configuration or field-engineering ownership yields
  WATCH because access cannot resolve those missing capabilities. Positive scope confirmation
  is a synthetic calibration input, not a claim about a live vacancy.
- **HERE:** direct ADAS/program evidence supports a high score and NETWORK FIRST when cold.
  Pre-sales support remains a review gap; core commercial ownership would block application.
- **CARIAD:** the exact historical description says “Data-platform and DevOps depth required”.
  It remains WATCH. The separate `cariad_bridge_scope` variant expresses the requested product/
  adoption interpretation with specialist platform collaboration and retains internal-team access:
  APPLY, capped at 75, with platform/DevOps depth still visible as a gap. This is an explicitly
  labelled scope variant, **not a newly verified actual CARIAD description**. Confirm actual scope
  before treating the real role as APPLY. No historical text was silently weakened.

## Bliq — missing input, no fabricated fixtures

Repository content and filenames were searched case-insensitively for Bliq, including hidden,
ignored, generated and runtime files while excluding Git internals, dependencies and build output.
No saved descriptions were found. All three named fixtures remain blocked:

- **Bliq Product Delivery Engineer:** full responsibilities, required software/hands-on engineering,
  customer delivery/commissioning ownership, experience level, location/attendance terms.
- **Bliq Chief of Staff:** full responsibilities and requirements, especially founder-facing
  execution, company-building, finance, fundraising, commercial ownership, seniority and location.
- **Bliq Founder’s Associate:** full responsibilities, required experience, seniority, administrative
  versus technical execution scope, commercial/finance duties and location.

Paste the complete description text for each (including required versus preferred qualifications).
No generic role has been relabelled Bliq and no actual Bliq ordering is asserted without those texts.

## Historical → current → recalibrated comparison

v0 is the original checked-out evaluator; v1 is the first strategy pass; v2 is the prior semantics
refinement; v3 is this final calibration. Composite totals across versions have different meanings;
v3 alone is the weighted current-candidacy measure. The historical dx.one **27.5/SKIP remains
unverified**; v0 recorded 48.3/WATCH, and no reproduction of 27.5 has been manufactured.

| Fixture | Original v0 | First pass v1 | Prior/current v2 | Recalibrated v3 |
|---|---|---|---|---|
| robotics_tpm | 63.6 / EXPLORE | 82.5 / NETWORK_FIRST | 62.9 / NETWORK_FIRST | 75 / NETWORK_FIRST |
| amr | 58.1 / WATCH | 81.5 / APPLY_NOW | 61.2 / WATCH | 75 / WATCH |
| perception | 58.7 / WATCH | 24.4 / SKIP | 51.4 / SKIP | 25 / SKIP |
| architect | 56.1 / WATCH | 24.4 / SKIP | 51.4 / SKIP | 25 / SKIP |
| here | 52.6 / WATCH | 80.5 / NETWORK_FIRST | 64.7 / APPLY_NOW | 88.4 / NETWORK_FIRST |
| cariad | 51.3 / WATCH | 84.3 / APPLY_NOW | 75.5 / WATCH | 40 / WATCH |
| enterprise_ai | 52.8 / WATCH | 30.0 / SKIP | 50.2 / SKIP | 25 / SKIP |
| founder | 10.0 / SKIP | 10.0 / SKIP | 10.0 / SKIP | 0.0 / SKIP |
| cos | 52.6 / WATCH | 79.5 / NETWORK_FIRST | 52.4 / NETWORK_FIRST | 75 / NETWORK_FIRST |
| munich | 46.1 / SKIP | 74.0 / SKIP | 42.5 / SKIP | 94.0 / SKIP |
| china | 45.3 / SKIP | 45.9 / SKIP | 45.9 / SKIP | 30 / SKIP |
| dx | 48.3 / WATCH | 73.8 / NETWORK_FIRST | 57.3 / WATCH | 40 / WATCH |
| freenow | 64.1 / WATCH | 82.2 / NETWORK_FIRST | 56.5 / WATCH | 40 / WATCH |
| amr_confirmed_delivery | — | — | 61.2 / APPLY_NOW | 75 / APPLY_NOW |
| amr_core_commissioning | — | — | 61.2 / WATCH | 40 / WATCH |
| robotics_tpm_direct_years | — | — | — | 40 / WATCH |
| amr_linux_field_engineering | — | — | — | 40 / WATCH |
| cos_finance_fundraising | — | — | — | 40 / WATCH |
| cariad_bridge_scope | — | — | — | 75 / APPLY_NOW |

## Dimension-level scores (v3, 0–100)

Strategy column shows search lane/allocation, not candidate strength. Total is weighted current
candidacy after caps; location and network are reported but have no score weight. Career-lane and
domain values reflect evidence anchors, not keyword counts. Detailed source text and role/market
facts are in the versioned fixtures; all market evidence is unknown unless explicitly supplied.

| Fixture | Strategic lane / allocation | Lane | Capability | Domain | Evidence | Location | Network | Weighted before cap | Cap | Total | Transition | Action |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| robotics_tpm | autonomy_robotics / 55% | 75 | 100.0 | 75 | 90.0 | 100.0 | 0.0 | 87.0 | 75 | 75 | adjacent | NETWORK_FIRST |
| amr | autonomy_robotics / 55% | 75 | 100.0 | 75 | 83.3 | 100.0 | 0.0 | 85.0 | 75 | 75 | adjacent | WATCH |
| perception | autonomy_robotics / 55% | 0 | 100.0 | 0 | 80.0 | 100.0 | 0.0 | 54.0 | 25 | 25 | unrealistic | SKIP |
| architect | autonomy_robotics / 55% | 0 | 100.0 | 0 | 80.0 | 100.0 | 0.0 | 54.0 | 25 | 25 | unrealistic | SKIP |
| here | technology_programs / 25% | 85 | 93.3 | 85 | 88.0 | 100.0 | 0.0 | 88.4 | 100 | 88.4 | direct | NETWORK_FIRST |
| cariad | ai_data_transformation / 20% | 75 | 85.0 | 85 | 75.0 | 100.0 | 80.0 | 80.0 | 40 | 40 | bridge | WATCH |
| enterprise_ai | None / 0% | 0 | 82.9 | 0 | 62.9 | 100.0 | 0.0 | 43.7 | 25 | 25 | unrealistic | SKIP |
| founder | None / 0% | 0 | 0 | 0 | 0.0 | 100.0 | 0.0 | 0.0 | 30 | 0.0 | unrealistic | SKIP |
| cos | autonomy_robotics / 55% | 75 | 93.3 | 75 | 81.3 | 100.0 | 0.0 | 82.4 | 75 | 75 | adjacent | NETWORK_FIRST |
| munich | technology_programs / 25% | 85 | 100.0 | 85 | 100.0 | 0.0 | 0.0 | 94.0 | 100 | 94.0 | direct | SKIP |
| china | technology_programs / 25% | 0 | 100.0 | 85 | 95.0 | 0.0 | 0.0 | 75.5 | 30 | 30 | unknown | SKIP |
| dx | ai_data_transformation / 20% | 75 | 70.0 | 85 | 54.0 | 100.0 | 90.0 | 69.2 | 40 | 40 | bridge | WATCH |
| freenow | autonomy_robotics / 55% | 75 | 96.0 | 85 | 86.8 | 60.0 | 58.0 | 86.8 | 40 | 40 | adjacent | WATCH |
| amr_confirmed_delivery | autonomy_robotics / 55% | 75 | 100.0 | 75 | 83.3 | 100.0 | 0.0 | 85.0 | 75 | 75 | adjacent | APPLY_NOW |
| amr_core_commissioning | autonomy_robotics / 55% | 75 | 100.0 | 75 | 83.3 | 100.0 | 0.0 | 85.0 | 40 | 40 | adjacent | WATCH |
| robotics_tpm_direct_years | autonomy_robotics / 55% | 75 | 93.3 | 75 | 81.3 | 100.0 | 0.0 | 82.4 | 40 | 40 | adjacent | WATCH |
| amr_linux_field_engineering | autonomy_robotics / 55% | 75 | 100.0 | 75 | 90.0 | 100.0 | 0.0 | 87.0 | 40 | 40 | adjacent | WATCH |
| cos_finance_fundraising | autonomy_robotics / 55% | 75 | 93.3 | 75 | 81.3 | 100.0 | 0.0 | 82.4 | 40 | 40 | adjacent | WATCH |
| cariad_bridge_scope | ai_data_transformation / 20% | 75 | 85.0 | 85 | 75.0 | 100.0 | 80.0 | 80.0 | 75 | 75 | bridge | APPLY_NOW |

## Evidence, decisive gaps and action overrides by fixture

### robotics_tpm — Example Robotics: Robotics Technical Program Manager

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs).
- Material/decisive gaps: none established.
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: candidacy_cap: adjacent (cap 75); cold_access: Fit/evidence thresholds passed; access is the remaining actionable weakness..

### amr — Example AMR: AMR Customer Deployment Lead

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (transferable, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs); international_cross_border (differentiator, 5/5; professional experience in Germany and China).
- Material/decisive gaps: none established.
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; cold_access: No documented referral, hiring-manager contact or warm access.; commissioning_scope_unknown: Confirm hands-on robotics engineering/commissioning is not a core requirement..
- Gates/overrides: candidacy_cap: adjacent (cap 75); commissioning_scope_unknown: Confirm hands-on robotics engineering/commissioning is not a core requirement.; evidence_or_scope_review: Current evidence, role scope or seniority does not yet justify APPLY..
- Score/action explanation: **75 reflects supported capabilities, not eligibility. WATCH remains correct because the gates above override the numeric fit.**

### perception — Example Robotics: Robotics Perception Engineer

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (transferable, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs).
- Material/decisive gaps: perception_engineer: Perception engineering requires specialist hands-on technical depth.; core_engineering_gap: Core engineering ownership is required but candidate evidence is missing.; decisive_capability_mismatch: Specialist role is outside supported evidence..
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; production_ros2_missing: Production ROS 2 experience is missing; planned AMR work remains evidence in development.; perception_planning_control_missing: Specialist perception/planning/control engineering is not evidenced.; engineering_heavy_role: Role requires specialist engineering beyond supported evidence.; cold_access: No documented referral, hiring-manager contact or warm access.; unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge..
- Gates/overrides: candidacy_cap: unknown (cap 25); unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge.; perception_engineer: Perception engineering requires specialist hands-on technical depth.; core_engineering_gap: Core engineering ownership is required but candidate evidence is missing.; decisive_capability_mismatch: Specialist role is outside supported evidence..

### architect — Example Robotics: Senior Robotics Architect

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (transferable, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs).
- Material/decisive gaps: core_engineering_gap: Core engineering ownership is required but candidate evidence is missing.; decisive_capability_mismatch: Specialist role is outside supported evidence..
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; perception_planning_control_missing: Specialist perception/planning/control engineering is not evidenced.; robot_hardware_missing: Robot hardware or mechatronics engineering ownership is not evidenced.; engineering_heavy_role: Role requires specialist engineering beyond supported evidence.; cold_access: No documented referral, hiring-manager contact or warm access.; unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge..
- Gates/overrides: candidacy_cap: unknown (cap 25); unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge.; core_engineering_gap: Core engineering ownership is required but candidate evidence is missing.; decisive_capability_mismatch: Specialist role is outside supported evidence..

### here — HERE: Solution Lead Professional Services ADAS/AD EMEA

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (domain, 5/5; ADAS and automated-driving programs); product_delivery (transferable, 4/5; requirements and dependency management).
- Material/decisive gaps: none established.
- Other visible gaps: commercial_ownership_needs_evidence: Commercial/pre-sales ownership needs evidence; stakeholder coordination is not sales ownership.; cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: cold_access: Fit/evidence thresholds passed; access is the remaining actionable weakness..

### cariad — CARIAD: Internal A.I. Reporting Specialist

- Fixture provenance: `representative_text_with_user_evidence`; candidate/config version `career-calibration-v3`.
- Network: **warm** (internal_team_access, 80.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); automotive_mobility (domain, 5/5; more than 20 years in automotive and mobility); product_delivery (transferable, 4/5; requirements and dependency management); ai_data_transformation (emerging, 3/5; AI and machine-learning upskilling).
- Material/decisive gaps: core_technical_gap: Core technical ownership is required but candidate evidence is missing..
- Other visible gaps: production_ai_platform_missing: Production AI/data-platform ownership is not evidenced.; cloud_mlops_depth_missing: Deep DevOps/MLOps/cloud architecture experience is not evidenced..
- Gates/overrides: candidacy_cap: adjacent (cap 40); core_technical_gap: Core technical ownership is required but candidate evidence is missing.; adequate_access: Confirmed access excludes NETWORK FIRST..

### enterprise_ai — Example Retail: Head of Enterprise AI Transformation

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (transferable, 5/5; 20+ years of experience in complex automotive and technology programs); executive_stakeholder_management (transferable, 5/5; senior management communication); technical_business_translation (transferable, 5/5; translating technical topics into management-ready decisions); transformation_execution (transferable, 4/5; organizational transformation); ai_data_transformation (emerging, 3/5; AI and machine-learning upskilling); mlops (emerging, 3/5; MLOps coursework and projects); strategy (transferable, 4/5; executive decision preparation).
- Material/decisive gaps: decisive_capability_mismatch: Specialist role is outside supported evidence..
- Other visible gaps: enterprise_ai_ownership_missing: Commercial enterprise AI transformation ownership is not evidenced.; cold_access: No documented referral, hiring-manager contact or warm access.; unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge..
- Gates/overrides: candidacy_cap: unknown (cap 25); unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge.; decisive_capability_mismatch: Specialist role is outside supported evidence..

### founder — Example Retail: Founder’s Associate

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: none.
- Material/decisive gaps: none established.
- Other visible gaps: seniority_mismatch: Role may undervalue 20+ years of seniority.; cold_access: No documented referral, hiring-manager contact or warm access.; unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge..
- Gates/overrides: unsupported_role_transition: Role requirements lack a supported direct, adjacent or selective bridge..

### cos — Example Robotics: Chief of Staff Autonomous Systems

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs); strategy (transferable, 4/5; executive decision preparation).
- Material/decisive gaps: none established.
- Other visible gaps: cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: candidacy_cap: adjacent (cap 75); cold_access: Fit/evidence thresholds passed; access is the remaining actionable weakness..

### munich — Example Mobility: ADAS Program Lead

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (domain, 5/5; ADAS and automated-driving programs).
- Material/decisive gaps: none established.
- Other visible gaps: cold_access: No documented referral, hiring-manager contact or warm access.; relocation_conflict: Required presence conflicts with Berlin-region constraints.; relocation_required: Candidate does not currently want to relocate.; location_conflict: Required presence conflicts with location constraints..
- Gates/overrides: relocation_required: Candidate does not currently want to relocate.; location_conflict: Required presence conflicts with location constraints..
- Score/action explanation: **94.0 reflects supported capabilities, not eligibility. SKIP remains correct because the gates above override the numeric fit.**

### china — Example Mobility: ADAS Leadership

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: adas_autonomous_driving (domain, 5/5; ADAS and automated-driving programs); international_cross_border (differentiator, 5/5; professional experience in Germany and China).
- Material/decisive gaps: none established.
- Other visible gaps: cold_access: No documented referral, hiring-manager contact or warm access.; relocation_conflict: Required presence conflicts with Berlin-region constraints.; relocation_required: Candidate does not currently want to relocate.; china_based_role: China-based relocation is currently not preferred.; location_conflict: Required presence conflicts with location constraints..
- Gates/overrides: candidacy_cap: unknown (cap 30); relocation_required: Candidate does not currently want to relocate.; china_based_role: China-based relocation is currently not preferred.; location_conflict: Required presence conflicts with location constraints..

### dx — dx.one: Product Owner - Vehicle & Customer Analytics

- Fixture provenance: `representative_text_with_user_evidence`; candidate/config version `career-calibration-v3`.
- Network: **referral-based** (employee_referral, 90.0).
- Matched supporting evidence: automotive_mobility (domain, 5/5; more than 20 years in automotive and mobility); product_delivery (transferable, 4/5; requirements and dependency management); ai_data_transformation (emerging, 3/5; AI and machine-learning upskilling); product_owner (adjacent, 2/5; experience working in agile and product environments).
- Material/decisive gaps: several_years_formal_product_owner_required: Candidate has product-adjacent experience but not a long formal PO track record..
- Other visible gaps: none.
- Gates/overrides: candidacy_cap: adjacent (cap 40); several_years_formal_product_owner_required: Candidate has product-adjacent experience but not a long formal PO track record.; adequate_access: Confirmed access excludes NETWORK FIRST..

### freenow — FREENOW: Senior Autonomous Vehicle Partnership Manager

- Fixture provenance: `representative_text_with_user_evidence`; candidate/config version `career-calibration-v3`.
- Network: **warm** (warm_contact, 58.0).
- Matched supporting evidence: technical_program_leadership (transferable, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (domain, 5/5; ADAS and automated-driving programs); automotive_mobility (domain, 5/5; more than 20 years in automotive and mobility); international_cross_border (differentiator, 5/5; professional experience in Germany and China); mobility_service_deployment (transferable, 4/5; mobility and autonomous-driving program experience).
- Material/decisive gaps: core_commercial_gap: Core commercial ownership is required but candidate evidence is missing..
- Other visible gaps: commercial_ownership_needs_evidence: Commercial/pre-sales ownership needs evidence; stakeholder coordination is not sales ownership.; location_unknown: Confirm Berlin-compatible presence and travel requirements..
- Gates/overrides: candidacy_cap: adjacent (cap 40); core_commercial_gap: Core commercial ownership is required but candidate evidence is missing.; location_unknown: Confirm Berlin-compatible presence and travel requirements.; adequate_access: Confirmed access excludes NETWORK FIRST..

### amr_confirmed_delivery — Example AMR: AMR Customer Deployment Lead

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (transferable, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs); international_cross_border (differentiator, 5/5; professional experience in Germany and China).
- Material/decisive gaps: none established.
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: candidacy_cap: adjacent (cap 75); apply_eligible: Fit, evidence and location qualify; no decisive gap. Cold access need not delay this role..

### amr_core_commissioning — Example AMR: AMR Customer Deployment Lead

- Fixture provenance: `synthetic_calibration`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (transferable, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs); international_cross_border (differentiator, 5/5; professional experience in Germany and China).
- Material/decisive gaps: core_engineering_gap: Core engineering ownership is required but candidate evidence is missing..
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: candidacy_cap: adjacent (cap 40); core_engineering_gap: Core engineering ownership is required but candidate evidence is missing..

### robotics_tpm_direct_years — Example Robotics: Robotics Technical Program Manager

- Fixture provenance: `synthetic_scope_variant`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs); product_delivery (transferable, 4/5; requirements and dependency management).
- Material/decisive gaps: professional_robotics_years_missing: Multiple years of direct robotics-product experience required; vehicle programs are transferable only..
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: candidacy_cap: adjacent (cap 40); professional_robotics_years_missing: Multiple years of direct robotics-product experience required; vehicle programs are transferable only..

### amr_linux_field_engineering — Example AMR: AMR Customer Deployment Lead

- Fixture provenance: `synthetic_scope_variant`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: international_cross_border (differentiator, 5/5; professional experience in Germany and China).
- Material/decisive gaps: core_engineering_gap: Core engineering ownership is required but candidate evidence is missing..
- Other visible gaps: direct_professional_robotics_missing: Direct professional robotics experience is not evidenced; vehicle integration is transferable.; production_ros2_missing: Production ROS 2 experience is missing; planned AMR work remains evidence in development.; cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: candidacy_cap: adjacent (cap 40); core_engineering_gap: Core engineering ownership is required but candidate evidence is missing..

### cos_finance_fundraising — Example Robotics: Chief of Staff Autonomous Systems

- Fixture provenance: `synthetic_scope_variant`; candidate/config version `career-calibration-v3`.
- Network: **cold** (none, 0.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); adas_autonomous_driving (transferable, 5/5; ADAS and automated-driving programs); strategy (transferable, 4/5; executive decision preparation).
- Material/decisive gaps: executive_finance_gap: Executive finance responsibility needs direct evidence.; executive_fundraising_gap: Executive fundraising responsibility needs direct evidence.; executive_company_building_gap: Executive company_building responsibility needs direct evidence..
- Other visible gaps: cold_access: No documented referral, hiring-manager contact or warm access..
- Gates/overrides: candidacy_cap: adjacent (cap 40); executive_finance_gap: Executive finance responsibility needs direct evidence.; executive_fundraising_gap: Executive fundraising responsibility needs direct evidence.; executive_company_building_gap: Executive company_building responsibility needs direct evidence..

### cariad_bridge_scope — CARIAD: Internal A.I. Reporting Specialist

- Fixture provenance: `synthetic_scope_variant`; candidate/config version `career-calibration-v3`.
- Network: **warm** (internal_team_access, 80.0).
- Matched supporting evidence: technical_program_leadership (core, 5/5; 20+ years of experience in complex automotive and technology programs); automotive_mobility (domain, 5/5; more than 20 years in automotive and mobility); product_delivery (transferable, 4/5; requirements and dependency management); ai_data_transformation (emerging, 3/5; AI and machine-learning upskilling).
- Material/decisive gaps: none established.
- Other visible gaps: production_ai_platform_missing: Production AI/data-platform ownership is not evidenced.; cloud_mlops_depth_missing: Deep DevOps/MLOps/cloud architecture experience is not evidenced..
- Gates/overrides: candidacy_cap: adjacent (cap 75); adequate_access: Confirmed access excludes NETWORK FIRST.; apply_eligible: Fit, evidence and location qualify; no decisive gap. Cold access need not delay this role..

## Reproducibility and schema choice

Versioned `strategy_calibration.v0/v1/v2` inputs/results and manifests are unchanged. v3 preserves
all existing company/title/description text, adds explicitly named scope variants, and records role
evidence, market evidence, config version and expected actions. `strategy_calibration.v3.config.json`
contains exact YAML configuration content and the candidate-profile fingerprint; the v3 manifest
records source/config/input/output SHA-256 fingerprints and the base Git commit. No new commit
is implied. Exact v3 result snapshots are tested against current deterministic evaluation.

New metadata is nested under schema-v1 `explanation`; old records without explanation still load.
`opportunity_score` is deliberately recalibrated in v3; `score_semantics` identifies the change.
No saved runtime records have been reassessed. v1/v2 records should not be interpreted as v3 totals.

## Remaining assumptions and limits

- Bliq exact descriptions are missing; these three calibrations are not complete.
- CARIAD actual responsibility depth must be confirmed to choose between the preserved required-depth
  WATCH fixture and the product/adoption bridge APPLY variant.
- AMR non-core engineering confirmation remains synthetic until verified against an actual role.
- Text matching is deterministic and conservative, not a complete natural-language requirements
  interpreter. Complex negation, multilingual requirements and ambiguous attendance need review.
- No live market facts were fetched. Unknown budget, hiring intent, evidence freshness and role
  scope remain unknown. Portfolio AI and planned ROS 2 work do not become production experience.
- Existing unrelated user changes (including newly present `.DS_Store` files) are untouched.
- No commit, push, PR, provider activation, runtime reassessment or application submission occurred.

## Validation results (2026-09-22)

- `.venv/bin/python -m pytest -q tests/career_intelligence`: **278 passed**.
- `.venv/bin/python -m pytest -q tests/career_intelligence/test_strategy_calibration.py tests/career_intelligence/test_recommendation_semantics.py`: **120 passed**.
- `.venv/bin/python -m pytest -q`: **3347 passed, 4 failed**.
  - Three `tests/test_daily_pipeline_failure_domains.py` failures were reproduced again with
    pristine HEAD script/test files in a temporary directory. Local macOS Bash lacks `mapfile`;
    the unchanged script then encounters an unbound array. No shell fix was attempted.
  - The fourth failure is `test_doc001l_current_repository_uses_target_docs_top_level_structure`:
    the architecture checker reports only the unrelated `docs/.DS_Store` as an unexpected file.
    That newly present user-workspace file is preserved. A read-only symlink projection of the
    same docs tree excluding OS metadata passes the architecture checker. The real-workspace
    full-suite result remains four failures; this projection is not claimed as a full-suite pass.
- Ruff on all changed/new Python files: **passed**.
- `scripts/validate_career_config.py`: **passed**, including weight, evidence-anchor and allocation checks.
- `git diff --check`: **passed**.

All saved runtime records and source/provider states remain unchanged. No commit, push or PR.
