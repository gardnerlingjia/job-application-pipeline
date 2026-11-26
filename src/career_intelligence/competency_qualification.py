"""Versioned, evidence-linked discovery qualification; never writes assessments."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from src.career_intelligence.practical_constraints import practical_evidence
from src.career_intelligence.role_relevance import RoleRelevanceGate
from src.career_intelligence.role_text import description_sections, plain_text
from src.career_intelligence.work_location import workplace_evidence
from src.search_intelligence.candidate_fact_profile import load_candidate_fact_profile_json

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_PATH = ROOT / "config/career_strategy_v34.yaml"
STATUSES = ("STRONG_TRANSFERABLE_FIT", "POSSIBLE_FIT", "INSUFFICIENT_EVIDENCE",
            "CONFIRMED_MISMATCH")


def digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             default=str).encode()).hexdigest()


def load_strategy(path: Path = STRATEGY_PATH) -> dict:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (not isinstance(config, dict)
            or config.get("schema_version") != "career_intelligence.strategy.v1"
            or config.get("strategy_version") != "v3.4"
            or config.get("production_default") is not False):
        raise ValueError("V3.4 must be an explicitly selected preview strategy")
    attention = config.get("role_attention_percent") or config["industry_attention_percent"]
    if sum(attention.values()) != 100 or any(value <= 0 for value in attention.values()):
        raise ValueError("Industry attention must be positive and sum to 100")
    for group in ("industries", "role_families", "competencies", "specialist_requirements",
                  "search_categories"):
        for rule in config.get(group, {}).values():
            for pattern in rule["patterns"]:
                re.compile(pattern, re.I)
    config["config_sha256"] = digest(config)
    return config


def load_candidate_evidence(config: dict, facts_path: Path | None = None) -> dict:
    """Existing evidence is provisional; CV-backed approved facts stay distinct."""
    path = ROOT / config["candidate_evidence"]["capability_profile"]
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    facts = []
    education = []
    review_facts = []
    if facts_path is None and config["candidate_evidence"].get("approved_facts_file"):
        facts_path = ROOT / config["candidate_evidence"]["approved_facts_file"]
    if facts_path:
        profile = load_candidate_fact_profile_json(facts_path.read_text(encoding="utf-8"))
        if profile.status != "approved":
            raise ValueError("Candidate fact profile must already be approved")
        education = [f.canonical_payload() for f in profile.approved_facts
                     if f.evidence_class == "formal_education"]
        facts = [fact.canonical_payload() for fact in profile.production_evidence_facts
                 if any(p.source_type == "canonical_cv" for p in fact.provenance)
                 and (not fact.valid_until or date.fromisoformat(fact.valid_until) >= date.today())]
    review_path = config["candidate_evidence"].get("preview_review_file")
    if config["candidate_evidence"].get("preview_review_enabled") and review_path and not facts_path:
        review_path = ROOT / review_path
        if review_path.exists():
            review = load_candidate_fact_profile_json(review_path.read_text(encoding="utf-8"))
            if review.status == "draft":
                review_facts = [f.canonical_payload() for f in review.facts
                                if f.evidence_class == "professional_employment"
                                and f.approval_status == "proposed"
                                and any(p.source_type == "canonical_cv" for p in f.provenance)]
    capabilities = dict(payload["capabilities"])
    for fact in facts + review_facts:
        for key in fact["capability_tags"]:
            if key in config["competencies"] and key not in capabilities:
                capabilities[key] = {"category": "transferable", "evidence": [fact["statement"]]}
    supplementary = load_supplementary_evidence(config, facts_path)
    context = load_candidate_context(config)
    return {"capabilities": capabilities, "supplementary_evidence": supplementary,
            "candidate_context": context, "approved_education_facts": education,
            "review_professional_facts": review_facts, "source": str(path.relative_to(ROOT)),
            "verified_professional_facts": facts,
            "verification_status": "cv_backed_facts_available" if facts else
                                   "cv_extraction_pending_candidate_approval" if review_facts else
                                   "pending_master_cv_reconciliation",
            "evidence_sha256": digest({"profile": payload, "cv_facts": facts, "preview_review": review_facts,
                                      "supplementary": supplementary, "context": context})}


def _hit(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _clauses(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", c).strip() for c in re.split(r";|\n|\.\s+", text)
            if c.strip()]


def _sections(description: str) -> dict:
    # Broader heading recognition is local to V3.4; historical parsing is unchanged.
    text = plain_text(description)
    for pattern, heading in (
        (r"your tasks and responsibilities|deine mission|was du bei uns bewegst", "Your tasks"),
        (r"your qualifications|desired skills and qualifications|dein skillset|"
         r"was uns überzeugt|what you need to be successful|basic qualifications", "Requirements"),
        (r"key responsibilities", "Responsibilities"),
    ):
        text = re.sub(pattern, heading, text, flags=re.I)
    return description_sections(text)


def _optional(clause: str, config: dict) -> bool:
    # A preferred certification in parentheses must not erase an enclosing requirement.
    clause = re.sub(r"\([^)]*(?:preferred|optional)[^)]*\)", "", clause, flags=re.I)
    return bool(re.search(config["qualification"]["optional_markers"], clause, re.I))


def _positive(clause: str) -> bool:
    return not re.search(r"\b(?:no|not|without|kein\w*|nicht)\b(?! only| nur)", clause, re.I)


def industry_and_family(row: Mapping[str, Any], config: dict) -> dict:
    company = str(row.get("company_name") or row.get("company") or "")
    title = str(row.get("title") or "")
    description = str(row.get("description") or "")
    role_sections = _sections(description)
    text = title + "\n" + role_sections["role"]
    industries = []
    evidence = []
    for key, rule in config["industries"].items():
        aliases = [alias for alias in rule.get("employers", [])
                   if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", company, re.I)]
        if aliases or _hit(rule["patterns"], text):
            industries.append(key)
            evidence.append({"industry": key, "basis": "employer" if aliases else "vacancy_text",
                             "matches": aliases})
    # A single primary bucket reconciles totals; all matching industries remain visible.
    primary = next((item["industry"] for item in evidence if item["basis"] == "employer"),
                   industries[0] if industries else "unknown")
    normalized = re.sub(r"[-–—_/]+", " ", title)
    families = [key for key, rule in config["role_families"].items()
                if _hit(rule["patterns"], normalized)]
    return {"industry": primary, "industries": industries or ["unknown"],
            "industry_evidence": evidence,
            "role_family": families[0] if families else "other",
            "role_families": families or ["other"]}


def location_qualification(description: str, locations: list[str]) -> dict:
    """Berlin/remote basis and travel need independent positive evidence."""
    text = plain_text(description)
    structured = {"name": "; ".join(locations), "source": "source_observation"} if locations else None
    practical = practical_evidence(text, structured)
    workplace = workplace_evidence(text, structured)
    lower = text.casefold()
    explicit_berlin = bool(re.search(
        r"(?:based in|location\s*:|arbeitsort\s*:|standort\s*:)\s*berlin", lower))
    berlin = any(re.search(r"\bberlin\b", place, re.I) for place in locations) or explicit_berlin
    germany_remote = bool(re.search(
        r"\b(?:remote (?:in |from )?(?:germany|deutschland)|"
        r"(?:fully remote|remote[- ]first) (?:role|position|job) (?:in |from )?germany|"
        r"berlin[- ]based remote|deutschlandweit remote)\b", lower))
    quantified = [clause for clause in _clauses(lower) if _positive(clause) and re.search(
        r"\btravel internationally\s+(?:at least |approximately |around )?(?:[2-9]\d|100)\s*%",
        clause)]
    if quantified:
        practical["compatibility"] = "incompatible"
        practical["travel_status"] = "frequent_international"
        practical["travel_evidence"] = quantified
    foreign_remote = bool(re.search(r"remote.{0,12}(?:us[- ]only|united states only)", lower))
    mandatory_elsewhere = bool(re.search(
        r"(?:daily|weekly|\d+ days? (?:per|a) week).{0,35}(?:on[- ]site|presence|office).{0,15}"
        r"(?:munich|hamburg|stuttgart|paris|london)|"
        r"(?:on[- ]site|office|presence).{0,15}(?:munich|hamburg|stuttgart|paris|london)"
        r".{0,25}(?:daily|weekly|\d+ days? (?:per|a) week)", lower))
    if practical["compatibility"] == "incompatible" or mandatory_elsewhere or foreign_remote:
        status = "confirmed_incompatible"
    elif (berlin or germany_remote) and practical["travel_status"] in {
        "none_required", "occasional_domestic"
    }:
        status = "confirmed_compatible"
    else:
        status = "unknown_requires_clarification"
    missing = []
    if not (berlin or germany_remote):
        missing.append("Confirm Berlin-based employment without relocation.")
    if practical["travel_status"] == "unknown":
        missing.append("Confirm travel frequency, destinations and overnight stays.")
    if mandatory_elsewhere or foreign_remote:
        missing.append("Required work presence conflicts with Berlin-based working.")
    return {"status": status, "berlin_work_supported": berlin or germany_remote,
            "travel_status": practical["travel_status"],
            "travel_evidence": practical["travel_evidence"],
            "relocation_evidence": practical["relocation_evidence"],
            "workplace": workplace, "missing": missing}


def classify_china_europe_requirements(sections: dict, config: dict) -> dict:
    """Classify only the job description; candidate evidence cannot affect this result."""
    policy = config["china_europe"]
    evidence = []
    relevance = "Not relevant"
    rank = {"Not relevant": 0, "Additional advantage": 1, "Strong advantage": 2,
            "Core requirement": 3}
    for section in ("duties", "required", "preferred", "unstructured"):
        for clause in _clauses(sections[section]):
            if not _positive(clause) or re.search(r"headquarters|our offices|hauptsitz", clause, re.I):
                continue
            china = bool(re.search(policy["china_pattern"], clause, re.I))
            professional = bool(re.search(policy["professional_pattern"], clause, re.I))
            international = bool(re.search(policy["international_pattern"], clause, re.I))
            china_professional_scope = bool(re.search(
                r"\bChina\b|\bChinese\b.{0,40}\b(?:engineering|teams?|market|suppliers?|partners?)\b|"
                r"chinesisch\w*.{0,35}(?:markt|team|lieferant|projekt|programm)", clause, re.I))
            value = "Not relevant"
            if china_professional_scope and professional:
                value = ("Strong advantage" if section == "preferred" or _optional(clause, config)
                         else "Core requirement")
            elif china or (international and professional):
                value = "Additional advantage"
            if rank[value] > 0:
                evidence.append({"section": section, "text": clause[:700],
                                 "basis": "china_professional_scope" if china_professional_scope and professional
                                          else "language_signal" if china
                                          else "international_transfer_not_china_requirement"})
                if rank[value] > rank[relevance]:
                    relevance = value
    return {"relevance": relevance, "job_evidence": evidence}


def china_europe_dimension(sections: dict, candidate: dict, config: dict) -> dict:
    """Match separately classified role requirements to CV-backed professional evidence."""
    role = classify_china_europe_requirements(sections, config)
    relevance, evidence = role["relevance"], role["job_evidence"]
    policy = config["china_europe"]
    tags = set(policy["professional_fact_tags"])
    # Language, nationality and background are not evidence of delivered work.
    # Facts reaching here have already passed the approved professional-fact loader.
    action = r"\b(?:led|owned|founded|performed|supported|managed|delivered|coordinated|negotiated|launched|implemented|" \
             r"geleitet|koordiniert|verantwortet|umgesetzt)\b"
    china_scope = r"\bChina\b|Chinese (?:market|teams?|suppliers?|partners?|joint.venture)|" \
                  r"chinesisch\w* (?:Markt|Teams?|Lieferanten|Partner)"
    def supported_facts(facts):
        return [fact for fact in facts
                 if tags.intersection(fact["capability_tags"])
                 and any(p.get("source_type") == "canonical_cv"
                         for p in fact.get("provenance", []))
                 and re.search(china_scope, fact["statement"], re.I)
                 and re.search(r"Europe|European|Germany|Deutschland|Europa",
                               fact["statement"], re.I)
                 and re.search(action, fact["statement"], re.I)
                 and re.search(policy["professional_pattern"], fact["statement"], re.I)]
    supported = supported_facts(candidate.get("verified_professional_facts", []))
    reviewed = supported_facts(candidate.get("review_professional_facts", []))
    dimension_patterns = {
        "cross_cultural_stakeholders": r"stakeholder|cross.cultural|interkulturell",
        "international_program_delivery": r"program|project|delivery|programm|projekt",
        "engineering_supplier_coordination": r"engineering|supplier|lieferant|entwicklung",
        "cross_regional_collaboration": r"collaborat|coordinat|zusammenarbeit|koordination",
        "china_market_knowledge": r"china.market|chinese.market|chinamarkt|marktkenntnis",
    }
    dimensions = {key: [fact["fact_key"] for fact in supported
                        if re.search(pattern, fact["statement"], re.I)]
                  for key, pattern in dimension_patterns.items()}
    dimensions["mandarin_german_english_communication"] = [
        fact["fact_key"] for fact in supported if all(
            re.search(pattern, fact["statement"], re.I) for pattern in
            (r"mandarin|chinesisch", r"german|deutsch", r"english|englisch"))]
    requested_dimensions = [key for key, pattern in dimension_patterns.items()
                            if any(re.search(pattern, hit["text"], re.I) for hit in evidence)]
    if any(re.search(r"mandarin|chinesisch|german|deutsch|english|englisch", hit["text"], re.I)
           for hit in evidence):
        requested_dimensions.append("mandarin_german_english_communication")
    pending = [key for key in requested_dimensions if not dimensions[key]]
    candidate_status = ("not_applicable" if relevance == "Not relevant" else
                        "pending_cv_verification" if pending or not supported else
                        "verified_for_identified_dimensions")
    reviewed_dimensions = {key: [f["fact_key"] for f in reviewed
                                 if re.search(pattern, f["statement"], re.I)]
                           for key, pattern in dimension_patterns.items()}
    if reviewed and not supported and relevance != "Not relevant":
        candidate_status = "cv_supported_pending_profile_approval"
    return {"relevance": relevance, "job_evidence": evidence,
            "reviewed_dimensions_pending_approval": reviewed_dimensions,
            "reviewed_professional_evidence": reviewed,
            "candidate_evidence_status": candidate_status,
            "requested_dimensions": requested_dimensions, "pending_dimensions": pending,
            "candidate_support": "cv_verified_professional" if supported else "not_verified",
            "candidate_evidence": [{"fact_key": fact["fact_key"], "statement": fact["statement"],
                                    "provenance": fact["provenance"]} for fact in supported],
            "verified_dimensions": dimensions,
            "missing": [] if candidate_status != "pending_cv_verification" else [
                "Master CV professional evidence is extracted; competency mapping awaits candidate approval."
                if reviewed else "China–Europe professional competence requires CV-backed approved evidence."],
            "score_contribution": 0,
            "no_china_component_penalty": False}


def qualify_vacancy(row: Mapping[str, Any], *, config: dict | None = None,
                    candidate: dict | None = None) -> dict:
    config = config or load_strategy()
    candidate = candidate or load_candidate_evidence(config)
    description = str(row.get("description") or "")
    sections = _sections(description)
    body = "\n".join(sections[key] for key in ("duties", "required", "unstructured"))
    clauses = [(section, clause) for section in ("duties", "required", "unstructured")
               for clause in _clauses(sections[section])]
    matches = []
    for key, rule in config["competencies"].items():
        capability = candidate["capabilities"].get(key, {})
        if capability.get("category") not in {"core", "domain", "transferable", "differentiator"}:
            continue
        evidence = capability.get("evidence", [])
        hits = [{"section": section, "text": clause[:700]} for section, clause in clauses
                if _positive(clause) and _hit(rule["patterns"], clause)]
        verified = [fact for fact in candidate.get("verified_professional_facts", [])
                    if key in fact["capability_tags"]]
        review = [fact for fact in candidate.get("review_professional_facts", [])
                  if key in fact["capability_tags"]]
        if verified or review:
            evidence = [fact["statement"] for fact in verified or review]
        if hits and evidence:
            matches.append({"competency": key, "job_evidence": hits[:3],
                            "candidate_evidence": evidence,
                            "candidate_source": "CV-backed approved facts" if verified else
                                                "Master CV extraction awaiting approval" if review else
                                                candidate["source"],
                            "candidate_fact_keys": [fact["fact_key"] for fact in verified or review],
                            "evidence_status": "cv_verified_professional" if verified
                                               else "cv_supported_pending_profile_approval" if review else
                                               "documented_profile_provisional",
                            "transferable": True})
    # Qualification requirements only: another team's production AI is not a personal requirement.
    required = [(s, c) for s, c in clauses if not _optional(c, config) and _positive(c)
                and (s == "required" or re.search(
                    r"\b(?:required|mandatory|must have|erforderlich|voraussetzung)\b", c, re.I))]
    gaps = [{"requirement": key, "reason": rule["reason"],
             "evidence_status": "not_documented_in_provisional_profile",
             "job_evidence": [{"section": s, "text": c[:700]} for s, c in required
                              if _hit(rule["patterns"], c)]}
            for key, rule in config["specialist_requirements"].items()]
    gaps = [gap for gap in gaps if gap["job_evidence"]]
    domain = [{"section": s, "text": c[:700]} for s, c in required
              if _hit(config["domain_requirements"], c)]
    policy = config["qualification"]
    execution = _hit(policy["execution_patterns"], body)
    matched_keys = {match["competency"] for match in matches}
    execution = execution and (
        "technical_program_leadership" in matched_keys or
        ("product_delivery" in matched_keys and bool(
            {"technical_business_translation", "transformation_execution"} & matched_keys)))
    ownership = _hit(policy["seniority_patterns"], body)
    evidence_sufficient = len(plain_text(body)) >= policy["minimum_description_chars"]
    mismatch = [c[:700] for _, c in clauses if _positive(c)
                and not _optional(c, config) and _hit(policy["mismatch_duty_patterns"], c)]
    for key, rule in policy.get("out_of_scope_roles", {}).items():
        if re.search(rule["titles"], str(row.get("title") or ""), re.I):
            mismatch.extend(f"{key}: {clause[:650]}" for _, clause in clauses
                            if _positive(clause) and re.search(rule["duties"], clause, re.I))
    # Titles remain a separate lens; only description duties/requirements qualify the role.
    if not evidence_sufficient:
        role_status = "INSUFFICIENT_EVIDENCE"
    elif mismatch:
        role_status = "CONFIRMED_MISMATCH"
    elif gaps:
        # The provisional profile is incomplete: absence is uncertainty, not disproof.
        role_status = "POSSIBLE_FIT" if len(matches) >= 2 and execution else "INSUFFICIENT_EVIDENCE"
    elif (len(matches) >= policy["minimum_core_competencies"]
          and execution and ownership and not domain):
        role_status = "STRONG_TRANSFERABLE_FIT"
    elif len(matches) >= 2 and execution:
        role_status = "POSSIBLE_FIT"
    else:
        role_status = "INSUFFICIENT_EVIDENCE"
    locations = row.get("locations") or ([row["location_text"]] if row.get("location_text") else
                                       [row["location"]] if row.get("location") else [])
    location = location_qualification(description, locations)
    status = role_status
    if evidence_sufficient and location["status"] == "confirmed_incompatible":
        status = "CONFIRMED_MISMATCH"
    elif role_status == "STRONG_TRANSFERABLE_FIT" and location["status"] != "confirmed_compatible":
        status = "POSSIBLE_FIT"
    china_europe = china_europe_dimension(sections, candidate, config)
    china_required_unknown = (china_europe["relevance"] == "Core requirement"
                              and china_europe["candidate_evidence_status"] != "verified_for_identified_dimensions")
    if status == "STRONG_TRANSFERABLE_FIT" and china_required_unknown:
        status = "POSSIBLE_FIT"
    missing = [item["reason"] for item in gaps] + location["missing"]
    if domain:
        missing.append("Confirm the specific industry knowledge requirement; industry alone is not a veto.")
    if not evidence_sufficient:
        missing.append("A substantive source job description is required; title alone cannot qualify.")
    if china_required_unknown:
        missing.extend(china_europe["missing"])
    verified_tags = {tag for fact in candidate.get("verified_professional_facts", [])
                     for tag in fact["capability_tags"]}
    verified_matches = [m["competency"] for m in matches if m["competency"] in verified_tags]
    eligible = (status == "STRONG_TRANSFERABLE_FIT"
                and len(verified_matches) >= policy["minimum_core_competencies"])
    if not eligible:
        assessment_reason = ("Qualification/location is not strong and confirmed." if
                             status != "STRONG_TRANSFERABLE_FIT" else
                             "Matched core competencies require CV-backed approved evidence.")
    else:
        assessment_reason = "Qualified preview candidate; existing full assessment may be run explicitly."
    classification = industry_and_family(row, config)
    condition_text = str(row.get("title") or "") + "\n" + plain_text(description)
    conditions = [{"type": key, "text": clause[:700]}
                  for key, pattern in (
                      ("contract_term", r"fixed[- ]term|\bbefristet\b|\bunbefristet\b|\bpermanent\b"),
                      ("working_hours", r"full[- ]time|part[- ]time|vollzeit|teilzeit"),
                      ("shift_or_on_call", r"on[- ]call|shift work|schichtarbeit|wochenendarbeit"),
                  ) for clause in _clauses(condition_text) if re.search(pattern, clause, re.I)]
    plausible = (status in {"STRONG_TRANSFERABLE_FIT", "POSSIBLE_FIT"}
                 and len(matches) >= policy["minimum_core_competencies"]
                 and execution and not gaps and not mismatch
                 and classification["industry"] in {
                     "energy_infrastructure", "industrial_technology", "enterprise_software"})
    supplementary_matches = match_supplementary_competencies(sections, candidate, config)
    result = {**classification, "strategy_version": config["strategy_version"],
            "strategy_sha256": config["config_sha256"],
            "candidate_evidence_sha256": candidate["evidence_sha256"],
            "candidate_verification_status": candidate["verification_status"],
            "candidate_context_matches": match_candidate_context(
                sections, candidate.get("candidate_context", {})),
            "input_sha256": digest({"title": row.get("title"), "description": description,
                                    "locations": locations, "company": row.get("company_name"),
                                    "candidate": candidate["evidence_sha256"],
                                    "strategy": config["config_sha256"]}),
            "description_sha256": digest(description),
            "description_source": row.get("description_source") or row.get("source_url"),
            "source_observation_id": row.get("source_observation_id"),
            "status": status, "competency_status": role_status,
            "title_gate": RoleRelevanceGate().decide(row.get("title")).as_dict(),
            "competency_evidence": matches,
            "supplementary_competency_evidence": supplementary_matches,
            "hybrid_support": {"supplementary_match_count": len(supplementary_matches),
                               "professional_match_count": len(matches),
                               "professional_gaps_unchanged": True,
                               "status": "supplementary_support_pending_final_approval" if
                               supplementary_matches else "no_supplementary_match_evidence"},
            "missing_requirements": missing,
            "specialist_gaps": gaps, "domain_requirements": domain,
            "mismatch_evidence": mismatch, "seniority_ownership_evidenced": ownership,
            "employment_conditions": {"evidence": conditions,
                                      "status": "source_terms_captured" if conditions else "unknown",
                                      "missing": "Confirm contract, hours and attendance with employer."},
            "location": location, "china_europe": china_europe,
            "assessment_eligible": eligible, "assessment_reason": assessment_reason,
            "plausible_cross_industry": plausible,
            "career_compatibility": "not_assessed"}
    result["opportunity_review"] = opportunity_review(row, result, config, row.get("employer_review"))
    if not result["opportunity_review"]["discovery_eligible"]:
        result["assessment_eligible"] = False
        result["assessment_reason"] = "Internal employer excluded by external-transition strategy."
    return result


def assess_qualified_vacancy(row: Mapping[str, Any], *, config: dict | None = None,
                             candidate: dict | None = None) -> dict:
    """An explicit call only; no historical file writes or engine substitutions."""
    qualification = qualify_vacancy(row, config=config, candidate=candidate)
    if not qualification["assessment_eligible"]:
        raise ValueError(qualification["assessment_reason"])
    from src.career_intelligence.assessor import assess_opportunity
    return {"strategy_version": "v3.4", "qualification": qualification,
            "assessment_engine": "unchanged_v3.3",
            "assessment": assess_opportunity(str(row.get("company_name") or ""),
                                             str(row.get("title") or ""),
                                             str(row.get("description") or ""))}

def opportunity_review(row: Mapping[str, Any], qualification: dict, config: dict,
                       employer_evidence: dict | None = None) -> dict:
    """Independent preview judgments; never substitutes legacy scores or operator states."""
    sections = _sections(str(row.get("description") or ""))
    clauses = [c for section in ("duties", "required", "preferred", "unstructured")
               for c in _clauses(sections[section]) if _positive(c)]
    duties = _clauses(sections["duties"] or sections["unstructured"])
    duties = [c for c in duties if _positive(c)]
    text = " ".join(clauses)
    title = str(row.get("title") or "")
    company = str(row.get("company_name") or row.get("company") or "")
    internal = any(re.fullmatch(rf"{re.escape(name)}(?:\s+SE|\s+GmbH)?", company.strip(), re.I)
                   for name in config.get("excluded_internal_employers", []))
    categories = config.get("search_categories", {})
    category = next((key for key in ("B", "C", "A")
                     if key in categories and _hit(categories[key]["patterns"], title)), None)
    if category is None:
        category = next((key for key in ("B", "C", "A")
                         if key in categories and _hit(categories[key]["patterns"], text)), "UNKNOWN")

    def hits(pattern, source=clauses):
        return [c[:700] for c in source if re.search(pattern, c, re.I)]

    implementation = hits(r"implement|deliver|deploy|build|launch|integrat|umsetz|realisier|"
                          r"einführ|abwick|abnahme|übergabe|entwickel", duties)
    ownership = hits(r"own|accountab|end.to.end|responsib|verantwort|gestalt|leit|steuer", duties)
    autonomy = hits(r"independen|autonom|eigenverantwort|selbstständig|selbständig|"
                    r"decision.making authority|entscheidungsspielraum")
    meeting_risk = hits(r"(?:primarily|mainly|predominantly|hauptsächlich|schwerpunkt).{0,80}"
                        r"(?:workshop|presentation|reporting|meeting|stakeholder alignment)|"
                        r"(?:maintenance.only|reine bestandsverwaltung)", duties)
    collaboration = hits(r"stakeholder|collaborat|coordinat|workshop|meeting|zusammenarbeit|abstimm")
    development = hits(r"learn|develop.{0,25}skills|training|mentoring|weiterbildung|"
                       r"lernen|praktisch.{0,30}anwenden")
    professional = qualification["competency_evidence"]
    verified = [m for m in professional if m["evidence_status"] == "cv_verified_professional"]
    cv_review = [m for m in professional
                 if m["evidence_status"] == "cv_supported_pending_profile_approval"]
    company_evidence = employer_evidence or {}
    # Research must be dated and attributable, and applies only to the reviewed employer/unit.
    credible = [item for item in company_evidence.get("evidence", [])
                if item.get("url") and item.get("published_at") and item.get("scope")
                and item.get("finding")]
    outlook_status = company_evidence.get("status", "UNKNOWN") if credible else "UNKNOWN"
    location = qualification["location"]
    life_status = {"confirmed_compatible": "CONFIRMED_COMPATIBLE",
                   "confirmed_incompatible": "INCOMPATIBLE"}.get(location["status"], "UNKNOWN")
    advertised_locations = " ".join(row.get("locations") or [row.get("location_text") or ""])
    foreign_only = bool(re.search(
        r"united states|\bUSA?\b|california|mountain view|san francisco|tokyo|japan|"
        r"united kingdom|london|singapore|taiwan|warsaw", advertised_locations, re.I))
    if foreign_only and not location["berlin_work_supported"] and not re.search(
            r"germany|deutschland|berlin", advertised_locations, re.I):
        life_status = "INCOMPATIBLE"
    if (life_status == "UNKNOWN" and location["berlin_work_supported"]):
        life_status = "POTENTIALLY_COMPATIBLE"
    if row.get("review_life_incompatibility"):
        life_status = "INCOMPATIBLE"
    active_status = row.get("review_active_status", "UNKNOWN")
    dimensions = {
        "professional_fit": {"status": "CV_VERIFIED_MATCHES" if verified else
                             "CV_SUPPORTED_PENDING_APPROVAL" if cv_review else "PROVISIONAL",
                             "evidence": professional,
                             "supplementary_evidence": qualification.get("supplementary_competency_evidence", []),
                             "gaps": qualification["specialist_gaps"] +
                                     qualification["domain_requirements"]},
        "company_outlook": {"status": outlook_status, "evidence": credible,
                            "uncertainties": company_evidence.get("uncertainties", [
                                "Financial stability, business-unit outlook and investment unverified."])},
        "work_content": {"status": "RISK" if meeting_risk and not implementation else
                         "IMPLEMENTATION_EVIDENCED" if implementation else "UNKNOWN",
                         "evidence": implementation, "ownership_evidence": ownership,
                         "risks": meeting_risk},
        "working_style": {"status": "RISK" if meeting_risk else
                          "AUTONOMY_SIGNAL" if autonomy else "UNKNOWN",
                          "evidence": autonomy, "collaboration_evidence": collaboration,
                          "risks": meeting_risk, "independent_work_percent": None,
                          "uncertainties": ["Confirm independent work, meeting load and decision authority."]},
        "development_potential": {"status": "LEARNING_SIGNAL" if development else "UNKNOWN",
                                  "evidence": development},
        "life_compatibility": {"status": life_status, "evidence": location,
                               "advertised_locations": advertised_locations,
                               "basis": "Advertised base; no Berlin alternative established" if foreign_only
                                        else "Location, attendance and travel evidence",
                               "uncertainties": location["missing"]},
    }
    reasons = []
    if active_status == "EXPIRED":
        judgment = "NOT SUITABLE"
        reasons.append("Employer vacancy page explicitly marks this posting expired; historical record retained.")
    elif row.get("review_confirmed_requirement_gap"):
        judgment = "NOT SUITABLE"
        reasons.append(row["review_confirmed_requirement_gap"])
    elif internal:
        judgment = "NOT SUITABLE"
        reasons.append("Internal CARIAD vacancy excluded by external-transition strategy.")
    elif life_status == "INCOMPATIBLE":
        judgment = "NOT SUITABLE"
        reasons.append("Advertised work base or explicit attendance/travel conflicts with Berlin compatibility.")
    elif qualification["status"] == "CONFIRMED_MISMATCH":
        judgment = "NOT SUITABLE"
        reasons.extend(qualification["mismatch_evidence"] or location["missing"] or
                       ["Confirmed description or location mismatch."])
    elif not text or len(plain_text(text)) < config["qualification"]["minimum_description_chars"]:
        judgment = "INSUFFICIENT EVIDENCE"
        reasons.append("Insufficient job-description evidence.")
    elif meeting_risk and not implementation:
        judgment = "NOT SUITABLE"
        reasons.append("Description explicitly prioritizes coordination/maintenance without implementation.")
    elif qualification["status"] in {"POSSIBLE_FIT", "STRONG_TRANSFERABLE_FIT"}:
        judgment = "CLARIFY"
        reasons.append("Potential delivery fit; unresolved candidate, employer or life-compatibility evidence.")
        if (qualification["status"] == "STRONG_TRANSFERABLE_FIT" and len(verified) >= 3
                and implementation and ownership and not meeting_risk
                and life_status == "CONFIRMED_COMPATIBLE" and outlook_status == "SUPPORTED"
                and row.get("review_description_scope", "captured_source") == "captured_source"
                and not qualification["specialist_gaps"] and not qualification["domain_requirements"]):
            judgment = "PURSUE"
            reasons = ["Verified professional fit and implementation ownership; no known major incompatibility."]
    else:
        judgment = "INSUFFICIENT EVIDENCE"
        reasons.append("Description does not establish sufficiently credible transferable execution fit.")
    return {"strategy_revision": config.get("revision"), "search_category": category,
            "posting_activity": active_status,
            "description_evidence_scope": row.get("review_description_scope", "captured_source"),
            "dimensions": dimensions, "judgment": judgment, "reasons": reasons,
            "discovery_eligible": not internal, "candidate_profile_approval_required": bool(cv_review),
            "legacy_assessment_unchanged": True, "historical_operator_state_unchanged": True,
            "judgment_categories": ["PURSUE", "CLARIFY", "WATCH", "NOT SUITABLE", "INSUFFICIENT EVIDENCE"],
            "watch_scope": "Employer or role-family watch judgment, separate from vacancy qualification."}

def load_supplementary_evidence(config: dict, approved_path: Path | None = None) -> list[dict]:
    """Read candidate-declared preview evidence without relaxing native fact provenance."""
    policy = config["candidate_evidence"]
    if not policy.get("preview_review_enabled"):
        return []
    result = []
    review_path = ROOT / policy.get("supplementary_review_file", "__no_review__")
    if review_path.is_file():
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if review.get("schema_version") != "career_intelligence.cv_reconciliation_review.v1":
            raise ValueError("Unsupported supplementary CV review schema")
        source = review["source"]
        cv_path = Path(source["path"])
        if cv_path.is_file() and sha256(cv_path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError("Supplementary evidence master CV hash mismatch")
        same_candidate_source = True
        if approved_path:
            approved = load_candidate_fact_profile_json(approved_path.read_text(encoding="utf-8"))
            same_candidate_source = any(
                p.source_type == "canonical_cv" and cv_path.name in p.reference
                for fact in approved.facts for p in fact.provenance)
        for item in review["facts"] if same_candidate_source else []:
            if item.get("evidence_class") != "candidate_declared_portfolio":
                continue
            if not item.get("paragraphs") or not item.get("source_text"):
                raise ValueError("Declared portfolio evidence needs CV section provenance")
            result.append({
                "fact_key": item["fact_key"], "capability_tags": item["competencies"],
                "statement": " ".join(item["source_text"]),
                "evidence_class": "candidate_declared_portfolio",
                "evidence_status": "cv_supported_candidate_declared_not_repository_verified",
                "maturity": item["maturity"], "limitations": item["limits"],
                "repository_verification": "not_verified",
                "provenance": [{"source_type": "canonical_cv", "reference":
                                source["path"] + " | " + ", ".join(item["paragraphs"])}],
                "additional_verification_needed": item["additional_verification_needed"],
                "candidate_approval": review.get("approval", {}),
            })
    native_path = approved_path or ROOT / policy.get("preview_review_file", "__no_profile__")
    if native_path.is_file():
        profile = load_candidate_fact_profile_json(native_path.read_text(encoding="utf-8"))
        for fact in profile.facts:
            if (fact.evidence_class != "training_certification"
                    or fact.approval_status not in {"proposed", "approved"}):
                continue
            expired = bool(fact.valid_until and date.fromisoformat(fact.valid_until) < date.today())
            result.append({**fact.canonical_payload(),
                           "evidence_status": "cv_supported_training_not_professional_delivery",
                           "maturity": "historical_training_expired_credential" if expired else "training",
                           "credential_status": "expired" if expired else "current_status_not_independently_verified",
                           "repository_verification": "not_applicable"})
    return result


def match_supplementary_competencies(sections: dict, candidate: dict, config: dict) -> list[dict]:
    """Expose supplementary support separately; never count it as professional delivery."""
    matches = []
    for key, rule in config.get("supplementary_competencies", {}).items():
        facts = [f for f in candidate.get("supplementary_evidence", [])
                 if key in f["capability_tags"]]
        hits = [{"section": section, "text": clause[:700]}
                for section in ("duties", "required", "preferred", "unstructured")
                for clause in _clauses(sections[section])
                if _positive(clause) and _hit(rule["patterns"], clause)]
        if facts and hits:
            matches.append({"competency": key, "label": rule["label"],
                            "job_evidence": hits[:3], "candidate_evidence": facts,
                            "professional_requirement_established": False,
                            "scope": "supplementary_only",
                            "limitations": ["Candidate-declared projects and training do not establish "
                                            "professional production experience or formal PO tenure.",
                                            "Candidate approved; repository verification remains optional and absent."
                                            if candidate.get("candidate_context", {}).get("approval") else
                                            "Final candidate profile approval remains pending."]})
    return matches

def load_candidate_context(config: dict) -> dict:
    """Expose existing CV context without converting dates or knowledge into specialist tenure."""
    path = ROOT / config["candidate_evidence"].get("supplementary_review_file", "__no_review__")
    if not config["candidate_evidence"].get("preview_review_enabled") or not path.is_file():
        return {"languages": {}, "technology_working_knowledge": {}, "employment_history": []}
    review = json.loads(path.read_text(encoding="utf-8"))
    history = {}
    today = date.today()
    for fact in review.get("facts", []):
        if fact.get("evidence_class") != "professional_employment":
            continue
        key = (fact["employer_or_context"], fact["role_or_activity"], fact["period"])
        if key in history:
            history[key]["cv_fact_keys"].append(fact["fact_key"])
            continue
        period = str(fact["period"])
        match = re.fullmatch(r"(\d{2})/(\d{4})\s*[–—-]\s*(?:(\d{2})/(\d{4})|(Present))",
                             period, re.I)
        months = None
        if match:
            end_year, end_month = ((today.year, today.month) if match[5] else
                                   (int(match[4]), int(match[3])))
            months = (end_year - int(match[2])) * 12 + end_month - int(match[1])
        history[key] = {"employer": key[0], "role": key[1], "documented_period": period,
                        "documented_month_interval": months,
                        "date_precision": "month; not a measure of specialist tenure",
                        "current_according_to_cv": bool(match and match[5]),
                        "as_of": today.isoformat(), "cv_fact_keys": [fact["fact_key"]],
                        "source_paragraphs": fact["paragraphs"],
                        "older_competence_expired": False}
    return {"languages": review.get("languages", {}),
            "technology_working_knowledge": review.get("technology_working_knowledge", {}),
            "employment_history": list(history.values()),
            "approval": review.get("approval", {}),
            "limits": ["Language proficiency does not establish CEFR certification or achievements.",
                       "Technology working knowledge is not professional production tenure.",
                       "Employment dates do not establish years of a particular specialist skill.",
                       "Older documented professional competence does not automatically expire."]}


def match_candidate_context(sections: dict, context: dict) -> dict:
    body = sections["role"]
    languages = []
    declared = context.get("languages", {}).get("text", "")
    for name, pattern in (("Mandarin", r"mandarin|chinese|chinesisch"),
                          ("German", r"german|deutsch"), ("English", r"english|englisch")):
        if re.search(pattern, body, re.I):
            evidence = [part.strip() for part in declared.split("|")
                        if re.search(pattern, part, re.I)]
            if evidence:
                languages.append({"language": name, "cv_declared_proficiency": evidence,
                                  "source": context["languages"].get("source"),
                                  "cefr_or_professional_achievement_inferred": False})
    knowledge = context.get("technology_working_knowledge", {}).get("text", "")
    technologies = [term.strip() for term in knowledge.split(":", 1)[-1].split(",")]
    return {"languages": languages,
            "technology_working_knowledge": [term for term in technologies if term and re.search(
                r"(?<!\w)" + re.escape(term) + r"(?!\w)", body, re.I)],
            "technology_scope": "CV working knowledge; professional tenure not established",
            "employment_history": context.get("employment_history", [])}
