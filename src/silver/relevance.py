import re
from typing import Any

from src.connectors.registry import SourceRole, source_role


EMPLOYER_ORIGIN_CAREER_SITE_SOURCE_TYPE = "employer_origin_career_site"
MIN_STRONG_DESCRIPTION_CHARS = 40
ATS_BACKED_EMPLOYER_ORIGIN_FAMILIES = {"greenhouse", "successfactors"}

ROLE_PHRASES = (
    # Canonical ML / AI / Reliability profile.
    "machine learning engineer",
    "ml engineer",
    "mlops engineer",
    "ml ops engineer",
    "ml platform engineer",
    "machine learning platform engineer",
    "ai platform engineer",
    "ai engineer",
    "artificial intelligence engineer",
    "ai reliability engineer",
    "ml reliability engineer",
    "machine learning reliability engineer",
    "data reliability engineer",

    # Strong Data Engineering bridge.
    "data engineer",
    "analytics engineer",
    "data platform",
    "data analyst",
    "bi engineer",
    "business intelligence",
    "etl developer",
    "data scientist",
    "data science",
    "data & insights",
    "data insights",
    "analytics",

    # Existing adjacent engineering discovery surface.
    "backend engineer",
    "backend / api engineer",
    "backend/api engineer",
    "api engineer",
    "cloud engineer",
    "cloud security engineer",
    "platform engineer",
    "developer experience",
    "product platform",
    "infrastructure engineer",
    "ai security",
    "product owner",
    "business analyst",
    "software engineer",
    "software entwickler",
    "ui entwickler",
    "javascript entwickler",
)

SKILL_PHRASES = (
    # ML / AI / Reliability signals.
    "machine learning",
    "mlops",
    "ml ops",
    "model serving",
    "model monitoring",
    "model drift",
    "feature engineering",
    "pytorch",
    "tensorflow",
    "scikit learn",
    "scikit-learn",
    "kubernetes",
    "observability",
    "reliability",
    "data quality",

    # Data / platform signals.
    "sql",
    "python",
    "etl",
    "elt",
    "data pipeline",
    "data warehouse",
    "data lake",
    "data platform",
    "azure",
    "aws",
    "gcp",
    "microsoft fabric",
    "databricks",
    "snowflake",
    "dbt",
    "airflow",
    "dagster",
    "prefect",
    "postgresql",
    "mongodb",
    "redis",
    "power bi",
    "tableau",
    "dashboard",
    "reporting",
    "api",
    "docker",
    "ci/cd",
    "javascript",
    "java script",
    "typescript",
    "ui",
    "bi",
    "ki",
    "ai",
)

ACCESSIBILITY_PHRASES = (
    "remote",
    "germany",
    "deutschland",
    "hannover",
    "hanover",
    "berlin",
    "hamburg",
    "munich",
    "münchen",
    "cologne",
    "köln",
    "frankfurt",
    "dublin",
    "ireland",
    "london",
    "united kingdom",
    "uk",
    "europe",
    "emea",
)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).lower().strip()
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text


def flatten_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, dict):
        return " ".join(flatten_value(item) for item in value.values())

    if isinstance(value, list):
        return " ".join(flatten_value(item) for item in value)

    return normalize_text(value)


def phrase_matches(text: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)

    if not normalized_phrase:
        return False

    escaped_phrase = re.escape(normalized_phrase)
    pattern = rf"(?<![a-z0-9]){escaped_phrase}(?![a-z0-9])"

    return re.search(pattern, text) is not None


def matching_phrases(text: str, phrases: tuple[str, ...]) -> list[str]:
    return [phrase for phrase in phrases if phrase_matches(text, phrase)]


def is_generated_employer_origin_gate_evidence(raw_job: dict) -> bool:
    raw_data = raw_job.get("raw_data")
    if not isinstance(raw_data, dict):
        return False

    if raw_data.get("source_type") != EMPLOYER_ORIGIN_CAREER_SITE_SOURCE_TYPE:
        return False

    acquisition_boundary = raw_data.get("acquisition_boundary")
    if not isinstance(acquisition_boundary, dict):
        return False

    return acquisition_boundary.get("generated_from_gate_evidence") is True


def build_generated_employer_origin_relevance_text(raw_job: dict) -> str:
    raw_data = raw_job.get("raw_data") or {}
    job_data = raw_data.get("job") or {}
    result_card = raw_data.get("result_card") or {}
    listing_evidence = raw_data.get("listing_evidence") or {}
    detail_evidence = raw_data.get("detail_evidence") or {}

    return " ".join(
        part
        for part in (
            flatten_value(raw_job.get("source_name")),
            flatten_value(job_data.get("title")),
            flatten_value(job_data.get("titel")),
            flatten_value(job_data.get("description")),
            flatten_value(job_data.get("beschreibung")),
            flatten_value(job_data.get("content")),
            flatten_value(job_data.get("company_name")),
            flatten_value(job_data.get("arbeitgeber")),
            flatten_value(result_card.get("title")),
            flatten_value(result_card.get("company_name")),
            flatten_value(listing_evidence.get("listing_text")),
            flatten_value(detail_evidence.get("page_title")),
        )
        if part
    )


def build_relevance_text(raw_job: dict) -> str:
    if is_generated_employer_origin_gate_evidence(raw_job):
        return build_generated_employer_origin_relevance_text(raw_job)

    raw_data = raw_job.get("raw_data") or {}
    job_data = raw_data.get("job", raw_data)

    return " ".join(
        part
        for part in (
            flatten_value(raw_job.get("source_name")),
            flatten_value(raw_job.get("source_url")),
            flatten_value(job_data.get("title")),
            flatten_value(job_data.get("titel")),
            flatten_value(job_data.get("description")),
            flatten_value(job_data.get("beschreibung")),
            flatten_value(job_data.get("content")),
            flatten_value(job_data.get("company_name")),
            flatten_value(job_data.get("arbeitgeber")),
            flatten_value(job_data.get("location")),
            flatten_value(job_data.get("arbeitsort")),
            flatten_value(job_data.get("profile_terms")),
            flatten_value(job_data.get("matched_terms")),
            flatten_value(job_data.get("skills")),
            flatten_value(job_data.get("metadata")),
            flatten_value(job_data.get("departments")),
            flatten_value(job_data.get("offices")),
            flatten_value(raw_data.get("result_card")),
            flatten_value(raw_data.get("listing_evidence")),
            flatten_value((raw_data.get("detail_evidence") or {}).get("page_title")),
        )
        if part
    )


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def is_employer_origin_source(raw_job: dict) -> bool:
    raw_data = _mapping(raw_job.get("raw_data"))
    if raw_data.get("source_type") == EMPLOYER_ORIGIN_CAREER_SITE_SOURCE_TYPE:
        return True

    source_name = raw_job.get("source_name")
    if not isinstance(source_name, str) or not source_name.strip():
        return False

    try:
        return source_role(source_name) == SourceRole.EMPLOYER_ORIGIN
    except ValueError:
        return False


def get_strong_employer_origin_description(raw_job: dict) -> str:
    raw_data = _mapping(raw_job.get("raw_data"))
    job_data = _mapping(raw_data.get("job")) or raw_data
    detail_evidence = _mapping(raw_data.get("detail_evidence"))

    description_fields = (
        job_data.get("description"),
        job_data.get("beschreibung"),
        job_data.get("content"),
        job_data.get("job_description"),
        job_data.get("body"),
        detail_evidence.get("description"),
        detail_evidence.get("content"),
        detail_evidence.get("job_description"),
        detail_evidence.get("body"),
        detail_evidence.get("text"),
        detail_evidence.get("plain_text"),
    )

    for value in description_fields:
        text = flatten_value(value)
        if len(text) >= MIN_STRONG_DESCRIPTION_CHARS:
            return text

    return ""


def _company_from_employer_origin_source_name(raw_job: dict) -> str:
    source_name = raw_job.get("source_name")
    if not isinstance(source_name, str) or ":" not in source_name:
        return ""

    family, target = source_name.split(":", 1)
    if family in {"greenhouse", "personio", "successfactors"} and target.strip():
        return target.replace("-", " ").replace("_", " ").strip()

    return ""


def _source_family(raw_job: dict) -> str:
    source_name = raw_job.get("source_name")
    if not isinstance(source_name, str) or ":" not in source_name:
        return ""

    family, _ = source_name.split(":", 1)
    return family


def has_ats_backed_provider_identity(raw_job: dict) -> bool:
    if _source_family(raw_job) not in ATS_BACKED_EMPLOYER_ORIGIN_FAMILIES:
        return False

    raw_data = _mapping(raw_job.get("raw_data"))
    job_data = _mapping(raw_data.get("job"))

    provider_job_id = flatten_value(raw_job.get("external_job_id") or job_data.get("id"))
    provider_url = flatten_value(
        job_data.get("absolute_url")
        or job_data.get("source_url")
        or raw_job.get("source_url")
    )
    provider_context = flatten_value(
        job_data.get("location")
        or job_data.get("offices")
        or job_data.get("first_published")
        or job_data.get("updated_at")
    )

    return bool(provider_job_id and provider_url and provider_context)


def get_employer_origin_minimum_evidence_reason(raw_job: dict) -> str | None:
    if not is_employer_origin_source(raw_job):
        return None

    if is_generated_employer_origin_gate_evidence(raw_job):
        return None

    raw_data = _mapping(raw_job.get("raw_data"))
    job_data = _mapping(raw_data.get("job")) or raw_data
    result_card = _mapping(raw_data.get("result_card"))

    title = flatten_value(
        job_data.get("title") or job_data.get("titel") or result_card.get("title")
    )
    company = flatten_value(
        job_data.get("company_name")
        or job_data.get("arbeitgeber")
        or result_card.get("company_name")
        or _company_from_employer_origin_source_name(raw_job)
    )

    if not title or not company:
        return None

    if get_strong_employer_origin_description(raw_job):
        return "employer_origin_strong_canonical_evidence"

    if has_ats_backed_provider_identity(raw_job):
        return "employer_origin_ats_provider_identity_evidence"

    return None


def has_employer_origin_minimum_evidence(raw_job: dict) -> bool:
    return get_employer_origin_minimum_evidence_reason(raw_job) is not None


def get_role_matches(raw_job: dict) -> list[str]:
    return matching_phrases(build_relevance_text(raw_job), ROLE_PHRASES)


def get_skill_matches(raw_job: dict) -> list[str]:
    return matching_phrases(build_relevance_text(raw_job), SKILL_PHRASES)


def get_accessibility_matches(raw_job: dict) -> list[str]:
    return matching_phrases(build_relevance_text(raw_job), ACCESSIBILITY_PHRASES)


def is_relevant_for_silver(raw_job: dict) -> bool:
    role_matches = get_role_matches(raw_job)
    skill_matches = get_skill_matches(raw_job)
    accessibility_matches = get_accessibility_matches(raw_job)

    if role_matches and accessibility_matches:
        return True

    if len(skill_matches) >= 2 and accessibility_matches:
        return True

    if has_employer_origin_minimum_evidence(raw_job):
        return True

    return False


def get_silver_decision_reason(raw_job: dict) -> str:
    role_matches = get_role_matches(raw_job)
    skill_matches = get_skill_matches(raw_job)
    accessibility_matches = get_accessibility_matches(raw_job)

    if role_matches and accessibility_matches:
        return "relevant_role_and_accessibility"

    if len(skill_matches) >= 2 and accessibility_matches:
        return "relevant_skills_and_accessibility"

    employer_origin_reason = get_employer_origin_minimum_evidence_reason(raw_job)
    if employer_origin_reason:
        return employer_origin_reason

    if not role_matches and len(skill_matches) < 2:
        return "missing_role_or_skill_signal"

    if not accessibility_matches:
        return "missing_accessibility_signal"

    return "not_relevant_for_silver"
