"""Bounded read-only adapters for public job search and ATS job boards."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests


class ProviderParseError(ValueError):
    """The provider responded, but its payload did not match the documented shape."""


def classify_vacancy_type(title: object) -> str:
    folded = str(title or "").casefold().strip()
    if folded.startswith("unsolicited application") or folded.startswith("open application"):
        return "unsolicited_application"
    if any(phrase in folded for phrase in ("talent community", "join our network", "general application")):
        return "other_employer_board_entry"
    return "actual_vacancy"


@dataclass(frozen=True)
class RetrievalLimits:
    page_size: int = 25
    max_pages: int = 3
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25
    min_interval_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.page_size < 1 or self.max_pages < 1 or self.max_retries < 0:
            raise ValueError("retrieval limits must be positive (retries may be zero)")


def _get_json(session: Any, url: str, *, params: dict | None = None,
              headers: dict | None = None, limits: RetrievalLimits) -> Any:
    error = None
    for attempt in range(limits.max_retries + 1):
        try:
            response = session.get(url, params=params, headers=headers, timeout=25)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderParseError("provider returned invalid JSON") from exc
            if not isinstance(payload, (dict, list)):
                raise ProviderParseError("provider response must be a JSON object or list")
            return payload
        except (requests.RequestException, ProviderParseError) as exc:
            error = exc
            if attempt == limits.max_retries:
                raise
            time.sleep(limits.retry_backoff_seconds * (2 ** attempt))
    raise RuntimeError("unreachable") from error


def _row(source: str, company: str, item: dict, *, title: str, url: str,
         external_id: object, location: str = "", published: object = None,
         updated: object = None, description: str = "") -> dict:
    title_text = str(title or "")
    vacancy_type = classify_vacancy_type(title_text)
    return {
        "source_name": source, "company_name": company, "title": title,
        "source_url": url, "external_job_id": str(external_id) if external_id else None,
        "location": location, "publication_date": published, "source_updated_at": updated,
        "description": description, "raw": item,
        "vacancy_type": vacancy_type,
    }


def fetch_ba(*, query: str, location: str, api_key: str, limits: RetrievalLimits,
             session: Any = requests) -> dict:
    """Fetch BA pages up to explicit cap; stop at an empty/short/total page."""
    url = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
    rows, pages = [], []
    total = None
    errors = []
    attempted = 0
    for page in range(1, limits.max_pages + 1):
        params = {"was": query, "wo": location, "page": page,
                  "size": limits.page_size, "angebotsart": 1}
        attempted += 1
        try:
            payload = _get_json(session, url, params=params,
                                headers={"X-API-Key": api_key}, limits=limits)
        except (requests.RequestException, ProviderParseError) as exc:
            if not pages:
                raise
            errors.append(f"Page {page}: {type(exc).__name__}: {exc}")
            break
        # The BA v6 response uses ergebnisliste; retain compatibility with older
        # connector fixtures that use stellenangebote.
        jobs = payload.get("ergebnisliste", payload.get("stellenangebote"))
        # BA omits the list field altogether for a successful zero-result query.
        if jobs is None and payload.get("maxErgebnisse") == 0:
            jobs = []
        if not isinstance(jobs, list):
            if pages:
                errors.append(f"Page {page}: ProviderParseError: BA response has invalid job list")
                break
            raise ProviderParseError("BA response has invalid job list")
        pages.append({"page": page, "raw_results": len(jobs), "request_url": url})
        if total is None:
            total = payload.get("maxErgebnisse")
        for job in jobs:
            ref = job.get("refnr") or job.get("referenznummer")
            job_url = (job.get("externeURL") or job.get("externeUrl") or job.get("url")
                       or f"ba://{ref}")
            locations = job.get("stellenlokationen") or []
            location_rows = []
            for location_row in locations:
                address_row = location_row.get("adresse") or {}
                place = ", ".join(filter(None, [address_row.get("ort"),
                    address_row.get("region"), address_row.get("land")]))
                if place and place not in location_rows:
                    location_rows.append(place)
            address = locations[0].get("adresse") or {} if locations else {}
            location_text = ", ".join(filter(None, [address.get("ort"), address.get("region"),
                                                       address.get("land")]))
            rows.append(_row("bundesagentur_fuer_arbeit", job.get("firma") or job.get("arbeitgeber"), job,
                             title=job.get("stellenangebotsTitel") or job.get("titel") or "",
                             url=job_url, external_id=ref,
                             location=location_text or job.get("arbeitsort", {}).get("ort") or "",
                             published=job.get("datumErsteVeroeffentlichung") or
                                       job.get("aktuelleVeroeffentlichungsdatum"),
                             updated=job.get("aenderungsdatum") or job.get("aktualisierungsdatum")))
            rows[-1]["locations"] = location_rows or ([location_text] if location_text else [])
        if not jobs or len(jobs) < limits.page_size or (total is not None and len(rows) >= int(total)):
            break
    return {"records": rows, "pages": pages, "total_found": total,
            "snapshot_complete": False,
            "pages_requested": attempted, "retrieval_errors": errors}


def fetch_greenhouse(*, board_id: str, employer: str, limits: RetrievalLimits,
                     session: Any = requests) -> dict:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs"
    payload = _get_json(session, url, params={"content": "true"}, limits=limits)
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ProviderParseError("Greenhouse response has invalid jobs list")
    rows = [_row(f"greenhouse:{board_id}", employer, job,
                 title=job.get("title", ""), url=job.get("absolute_url", ""),
                 external_id=job.get("id"), location=(job.get("location") or {}).get("name", ""),
                 updated=job.get("updated_at"), description=job.get("content", ""))
            for job in jobs]
    for row, job in zip(rows, jobs):
        row["locations"] = [str((job.get("location") or {}).get("name"))] if (job.get("location") or {}).get("name") else []
        if row["vacancy_type"] == "actual_vacancy" and str(row["title"]).casefold().startswith("open application"):
            row["vacancy_type"] = "unsolicited_application"
    return {"records": rows, "pages": [{"page": 1, "raw_results": len(rows), "request_url": url}],
            "snapshot_complete": True,
            "total_found": len(rows), "pages_requested": 1, "retrieval_errors": []}


def fetch_lever(*, board_id: str, employer: str, limits: RetrievalLimits,
                session: Any = requests, region: str = "global",
                location: str | None = None) -> dict:
    host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
    url = f"https://{host}/v0/postings/{board_id}"
    rows, pages = [], []
    skip = 0
    for page in range(1, limits.max_pages + 1):
        params = {"mode": "json", "skip": skip, "limit": limits.page_size}
        if location:
            params["location"] = location
        payload = _get_json(session, url, params=params, limits=limits)
        if not isinstance(payload, list):
            raise ProviderParseError("Lever response must be a JSON list")
        pages.append({"page": page, "raw_results": len(payload), "request_url": url})
        for job in payload:
            categories = job.get("categories") or {}
            rows.append(_row(f"lever:{board_id}", employer, job,
                title=job.get("text", ""), url=job.get("hostedUrl", ""),
                external_id=job.get("id"), location=categories.get("location", ""),
                published=job.get("createdAt"), updated=job.get("updatedAt"),
                description=job.get("description", "")))
        skip += len(payload)
        if not payload or len(payload) < limits.page_size:
            break
    complete = bool(pages and pages[-1]["raw_results"] < limits.page_size)
    return {"records": rows, "pages": pages, "total_found": None,
            "snapshot_complete": complete,
            "pages_requested": len(pages), "retrieval_errors": []}


def fetch_ashby(*, board_id: str, employer: str, limits: RetrievalLimits,
                session: Any = requests) -> dict:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_id}"
    payload = _get_json(session, url, params={"includeCompensation": "false"}, limits=limits)
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ProviderParseError("Ashby response has invalid jobs list")
    jobs = [job for job in jobs if job.get("isListed", True)]
    rows = [_row(f"ashby:{board_id}", employer, job, title=job.get("title", ""),
                 url=job.get("jobUrl", ""), external_id=job.get("jobUrl", ""),
                 location=job.get("location", ""),
                 published=job.get("publishedAt") or job.get("publishedDate"),
                 description=job.get("descriptionPlain") or job.get("descriptionHtml", ""))
            for job in jobs]
    return {"records": rows, "pages": [{"page": 1, "raw_results": len(rows), "request_url": url}],
            "snapshot_complete": True,
            "total_found": len(rows), "pages_requested": 1, "retrieval_errors": []}


def fetch_smartrecruiters(*, board_id: str, employer: str, limits: RetrievalLimits,
                          session: Any = requests, country: str | None = None,
                          max_details: int = 0, query: str | None = None) -> dict:
    # This provider requires lowercase ISO country codes, not display names.
    if country is not None:
        country = country.strip().lower()
        iso_countries = set((
            "ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn "
            "bo bq br bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz "
            "de dj dk dm do dz ec ee eg eh er es et fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl "
            "gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu id ie il im in io iq ir is it je jm "
            "jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me "
            "mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np "
            "nr nu nz om pa pe pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd "
            "se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz tc td tf tg th tj tk tl tm tn to "
            "tr tt tv tw tz ua ug um us uy uz va vc ve vg vi vn vu wf ws ye yt za zm zw"
        ).split())
        if country not in iso_countries:
            raise ProviderParseError("SmartRecruiters country must be an ISO alpha-2 code")
    url = f"https://api.smartrecruiters.com/v1/companies/{board_id}/postings"
    rows, pages = [], []
    offset = 0
    total = None
    details_requested = 0
    detail_errors = []
    retrieval_errors = []
    identities = set()
    pages_requested = 0
    for page in range(1, limits.max_pages + 1):
        params = {"limit": limits.page_size, "offset": offset}
        if country:
            # The public Posting API is case-sensitive: DE returns zero, de works.
            params["country"] = country.lower()
        if query:
            params["q"] = query
        pages_requested += 1
        try:
            payload = _get_json(session, url, params=params, limits=limits)
            if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
                raise ProviderParseError("SmartRecruiters response has invalid content")
            jobs = payload["content"]
            reported_total = payload.get("totalFound")
            if (not isinstance(reported_total, int) or isinstance(reported_total, bool)
                    or reported_total < 0):
                raise ProviderParseError("SmartRecruiters response has invalid totalFound")
            if total is not None and total != reported_total:
                retrieval_errors.append("Result total changed during pagination")
            total = reported_total
            if any(not isinstance(job, dict) or not job.get("id") for job in jobs):
                raise ProviderParseError("SmartRecruiters posting lacks source identity")
            if country and any(str((job.get("location") or {}).get("country", country))
                               .strip().lower() != country for job in jobs):
                raise ProviderParseError("SmartRecruiters returned postings outside country filter")
        except (requests.RequestException, ProviderParseError, RuntimeError) as exc:
            if not pages:
                raise
            retrieval_errors.append(f"{type(exc).__name__}: {exc}")
            break
        previous_count = len(identities)
        identities.update(str(job["id"]) for job in jobs)
        pages.append({"page": page, "raw_results": len(jobs), "request_url": url})
        for job in jobs:
            loc = job.get("location") or {}
            raw = dict(job)
            if details_requested < max_details:
                details_requested += 1
                detail_url = f"{url}/{job['id']}"
                try:
                    detail = _get_json(session, detail_url, limits=limits)
                    if not isinstance(detail, dict) or not isinstance(detail.get("jobAd"), dict):
                        raise ProviderParseError("SmartRecruiters detail has invalid jobAd")
                    raw["_v34_detail"] = detail
                    raw["_v34_detail_url"] = detail_url
                except (requests.RequestException, ProviderParseError, RuntimeError) as exc:
                    detail_errors.append({"source_job_id": job["id"],
                                          "error": f"{type(exc).__name__}: {exc}"})
            rows.append(_row(f"smartrecruiters:{board_id}", employer, raw,
                title=job.get("name", ""), url=job.get("ref", ""), external_id=job.get("id"),
                location=loc.get("fullLocation") or ", ".join(filter(None, [
                    loc.get("city"), loc.get("region"),
                    {"de": "Germany", "at": "Austria", "ch": "Switzerland",
                     "nl": "Netherlands", "gb": "United Kingdom", "us": "United States",
                     "fr": "France", "se": "Sweden", "be": "Belgium",
                     "dk": "Denmark"}.get(str(loc.get("country", "")).lower(), loc.get("country"))])),
                published=job.get("releasedDate"), updated=job.get("releasedDate")))
        offset += len(jobs)
        if not jobs or offset >= total:
            if len(identities) != total:
                retrieval_errors.append("Distinct posting count does not reconcile with totalFound")
            break
        if len(identities) == previous_count:
            retrieval_errors.append("Pagination made no progress in source identities")
            break
    complete = total is not None and len(identities) == total and not retrieval_errors
    if not complete and not retrieval_errors:
        retrieval_errors.append("Pagination limit reached before complete query coverage")
    return {"records": rows, "pages": pages, "total_found": total,
            "snapshot_complete": complete,
            "details_requested": details_requested, "detail_errors": detail_errors,
            "pages_requested": pages_requested, "retrieval_errors": retrieval_errors,
            "unique_source_vacancies": len(identities),
            "coverage_scope": "filtered_query" if country or query else "employer_board"}


def canonical_url(value: str) -> str:
    """Normalize only obvious URL tracking differences."""
    parts = urlsplit(value or "")
    query = [(k, v) for k, v in parse_qsl(parts.query)
             if not k.lower().startswith("utm_") and k.lower() not in {"ref", "tracking"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
                       urlencode(sorted(query)), ""))
