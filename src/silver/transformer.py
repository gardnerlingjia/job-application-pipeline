from datetime import date


EMPLOYER_ORIGIN_CAREER_SITE_SOURCE_TYPE = "employer_origin_career_site"


def parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def first_location(job_data: dict) -> dict:
    location = job_data.get("arbeitsort")

    if isinstance(location, dict):
        return location

    if isinstance(location, list) and location:
        first = location[0]
        if isinstance(first, dict):
            return first

    return {}


def normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = " ".join(value.strip().lower().split())

    return normalized or None


def build_normalized_location(
    city: object,
    postal_code: object,
    country: object,
) -> str | None:
    parts = [
        normalize_text(city),
        normalize_text(postal_code),
        normalize_text(country),
    ]

    normalized_parts = [part for part in parts if part]

    if not normalized_parts:
        return None

    return " | ".join(normalized_parts)


def build_canonical_key_candidate(
    normalized_company_name: str | None,
    normalized_title: str | None,
    normalized_location: str | None,
) -> str | None:
    parts = [
        normalized_company_name,
        normalized_title,
        normalized_location,
    ]

    key_parts = [part for part in parts if part]

    if not key_parts:
        return None

    return " :: ".join(key_parts)


def canonical_source_type(source_name: object) -> str:
    if isinstance(source_name, str) and (
        source_name.startswith("greenhouse:")
        or source_name.startswith("successfactors:")
    ):
        return "employer_origin_ats_backed_career_site"

    if isinstance(source_name, str) and (
        source_name.startswith("finanz_informatik:")
        or source_name.startswith("enercity:")
        or source_name.startswith("hdi:")
    ):
        return EMPLOYER_ORIGIN_CAREER_SITE_SOURCE_TYPE

    return "unknown"


def supported_bronze_source_type(raw_job: dict) -> str | None:
    raw_data = raw_job.get("raw_data")
    if not isinstance(raw_data, dict):
        return None

    source_type = raw_data.get("source_type")
    if source_type == EMPLOYER_ORIGIN_CAREER_SITE_SOURCE_TYPE:
        return source_type

    return None


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


def employer_origin_location(
    raw_job: dict,
    job_data: dict,
    result_card: dict,
) -> object:
    if is_generated_employer_origin_gate_evidence(raw_job):
        return None

    return job_data.get("location") or result_card.get("location")


def greenhouse_company_name(raw_job: dict, job_data: dict) -> str | None:
    company_name = job_data.get("company_name")
    if isinstance(company_name, str) and company_name.strip():
        return company_name

    source_name = raw_job.get("source_name")
    if source_name == "greenhouse:moia":
        return "MOIA"

    if isinstance(source_name, str) and source_name.startswith("greenhouse:"):
        token = source_name.split(":", 1)[1]
        fallback = token.replace("-", " ").replace("_", " ").strip()
        return fallback.title() if fallback else None

    return None


def add_canonicalization_fields(
    job: dict,
    *,
    canonical_source_type_override: str | None = None,
) -> dict:
    normalized_title = normalize_text(job.get("title"))
    normalized_company_name = normalize_text(job.get("company_name"))
    normalized_location = build_normalized_location(
        job.get("city"),
        job.get("postal_code"),
        job.get("country"),
    )

    job["normalized_title"] = normalized_title
    job["normalized_company_name"] = normalized_company_name
    job["normalized_location"] = normalized_location
    job["canonical_status"] = "discovery_only"
    job["canonical_source_type"] = (
        canonical_source_type_override
        if canonical_source_type_override is not None
        else canonical_source_type(job.get("source_name"))
    )
    job["canonical_key_candidate"] = build_canonical_key_candidate(
        normalized_company_name,
        normalized_title,
        normalized_location,
    )

    return job


def transform_bundesagentur_raw_job(raw_job: dict) -> dict:
    raw_data = raw_job["raw_data"]
    job_data = raw_data.get("job", {})
    location = first_location(job_data)

    publication_date = parse_date(
        job_data.get("aktuelleVeroeffentlichungsdatum")
        or job_data.get("veroeffentlichtAm")
        or job_data.get("datum")
    )

    return add_canonicalization_fields(
        {
            "raw_job_id": raw_job["id"],
            "source_name": raw_job["source_name"],
            "external_job_id": raw_job["external_job_id"],
            "source_url": raw_job["source_url"],
            "title": job_data.get("titel"),
            "company_name": job_data.get("arbeitgeber"),
            "city": location.get("ort"),
            "postal_code": location.get("plz"),
            "country": location.get("land"),
            "publication_date": publication_date,
        }
    )


def transform_greenhouse_raw_job(raw_job: dict) -> dict:
    raw_data = raw_job["raw_data"]
    job_data = raw_data.get("job", {})
    location = job_data.get("location") or {}

    publication_date = parse_date(
        job_data.get("first_published") or job_data.get("updated_at")
    )

    return add_canonicalization_fields(
        {
            "raw_job_id": raw_job["id"],
            "source_name": raw_job["source_name"],
            "external_job_id": raw_job["external_job_id"],
            "source_url": job_data.get("absolute_url") or raw_job["source_url"],
            "title": job_data.get("title"),
            "company_name": greenhouse_company_name(raw_job, job_data),
            "city": location.get("name"),
            "postal_code": None,
            "country": None,
            "publication_date": publication_date,
        }
    )


def transform_personio_raw_job(raw_job: dict) -> dict:
    raw_data = raw_job["raw_data"]
    job_data = raw_data.get("job", {})

    return add_canonicalization_fields(
        {
            "raw_job_id": raw_job["id"],
            "source_name": raw_job["source_name"],
            "external_job_id": raw_job["external_job_id"],
            "source_url": job_data.get("source_url") or raw_job["source_url"],
            "title": job_data.get("title"),
            "company_name": job_data.get("company_name"),
            "city": job_data.get("location"),
            "postal_code": None,
            "country": None,
            "publication_date": None,
        }
    )


def transform_finanz_informatik_raw_job(raw_job: dict) -> dict:
    raw_data = raw_job["raw_data"]
    job_data = raw_data.get("job", {})
    result_card = raw_data.get("result_card", {})

    return add_canonicalization_fields(
        {
            "raw_job_id": raw_job["id"],
            "source_name": raw_job["source_name"],
            "external_job_id": raw_job["external_job_id"],
            "source_url": (
                job_data.get("source_url")
                or result_card.get("detail_url")
                or raw_job["source_url"]
            ),
            "title": job_data.get("title") or result_card.get("title"),
            "company_name": (
                job_data.get("company_name")
                or result_card.get("company_name")
                or "Finanz Informatik GmbH & Co. KG"
            ),
            "city": employer_origin_location(raw_job, job_data, result_card),
            "postal_code": None,
            "country": "DE",
            "publication_date": None,
        }
    )


def transform_enercity_raw_job(raw_job: dict) -> dict:
    raw_data = raw_job["raw_data"]
    job_data = raw_data.get("job", {})
    result_card = raw_data.get("result_card", {})

    return add_canonicalization_fields(
        {
            "raw_job_id": raw_job["id"],
            "source_name": raw_job["source_name"],
            "external_job_id": raw_job["external_job_id"],
            "source_url": (
                job_data.get("source_url")
                or result_card.get("detail_url")
                or raw_job["source_url"]
            ),
            "title": job_data.get("title") or result_card.get("title"),
            "company_name": (
                job_data.get("company_name")
                or result_card.get("company_name")
                or "enercity AG"
            ),
            "city": employer_origin_location(raw_job, job_data, result_card),
            "postal_code": None,
            "country": "DE",
            "publication_date": None,
        }
    )


def transform_employer_origin_raw_job(
    raw_job: dict,
    *,
    default_company_name: str | None = None,
    default_country: str | None = "DE",
    canonical_source_type_override: str | None = None,
) -> dict:
    raw_data = raw_job["raw_data"]
    job_data = raw_data.get("job", {})
    result_card = raw_data.get("result_card", {})

    return add_canonicalization_fields(
        {
            "raw_job_id": raw_job["id"],
            "source_name": raw_job["source_name"],
            "external_job_id": raw_job["external_job_id"],
            "source_url": (
                job_data.get("source_url")
                or result_card.get("detail_url")
                or raw_job["source_url"]
            ),
            "title": job_data.get("title") or result_card.get("title"),
            "company_name": (
                job_data.get("company_name")
                or result_card.get("company_name")
                or default_company_name
            ),
            "city": employer_origin_location(raw_job, job_data, result_card),
            "postal_code": None,
            "country": (
                job_data.get("country")
                or result_card.get("country")
                or default_country
            ),
            "publication_date": None,
        },
        canonical_source_type_override=canonical_source_type_override,
    )


def transform_stepstone_raw_job(raw_job: dict) -> dict:
    raw_data = raw_job["raw_data"]
    result_card = raw_data.get("result_card", {})

    return add_canonicalization_fields(
        {
            "raw_job_id": raw_job["id"],
            "source_name": raw_job["source_name"],
            "external_job_id": raw_job["external_job_id"],
            "source_url": result_card.get("detail_url") or raw_job["source_url"],
            "title": result_card.get("title"),
            "company_name": result_card.get("company_name"),
            "city": result_card.get("location"),
            "postal_code": None,
            "country": None,
            "publication_date": None,
        }
    )


def transform_raw_job_to_silver(raw_job: dict) -> dict:
    source_name = raw_job["source_name"]

    if source_name == "bundesagentur_fuer_arbeit":
        return transform_bundesagentur_raw_job(raw_job)

    if source_name.startswith("greenhouse:"):
        return transform_greenhouse_raw_job(raw_job)

    if source_name.startswith("personio:"):
        return transform_personio_raw_job(raw_job)

    if source_name.startswith("finanz_informatik:"):
        return transform_finanz_informatik_raw_job(raw_job)

    if source_name.startswith("enercity:"):
        return transform_enercity_raw_job(raw_job)

    if source_name.startswith("hdi:"):
        return transform_employer_origin_raw_job(
            raw_job,
            default_company_name="HDI Group",
        )

    if source_name.startswith("successfactors:"):
        return transform_employer_origin_raw_job(raw_job)

    if source_name == "stepstone":
        return transform_stepstone_raw_job(raw_job)

    bronze_source_type = supported_bronze_source_type(raw_job)
    if bronze_source_type == EMPLOYER_ORIGIN_CAREER_SITE_SOURCE_TYPE:
        return transform_employer_origin_raw_job(
            raw_job,
            default_country=None,
            canonical_source_type_override=bronze_source_type,
        )

    raise ValueError(f"No Silver transformer implemented for source: {source_name}")


def get_supported_source_patterns() -> list[str]:
    return [
        "bundesagentur_fuer_arbeit",
        "greenhouse:%",
        "personio:%",
        "finanz_informatik:%",
        "enercity:%",
        "hdi:%",
        "successfactors:%",
        "stepstone",
    ]
