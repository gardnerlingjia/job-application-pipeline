"""Bounded detail enrichment for weak discovery-source Career Intelligence rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
import json
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlparse

import psycopg
import requests
from psycopg.rows import dict_row

from src.career_intelligence.silver_adapter import (
    SilverJobReadRepository,
    extract_description,
    normalize_source_patterns,
)
from src.config import get_database_config
from src.connectors.registry import SourceRole, source_role


REQUEST_TIMEOUT_SECONDS = 20
MIN_STRONG_DETAIL_CHARS = 400
MAX_DETAIL_TEXT_CHARS = 12000
MAX_EMPLOYER_ORIGIN_CANDIDATES = 1
USER_AGENT = (
    "job-application-pipeline-discovery-detail-enrichment/0.1 "
    "(bounded stored-detail-url enrichment; no pagination; no crawling)"
)


@dataclass(frozen=True)
class DetailFetchResult:
    requested_url: str
    final_url: str
    status_code: int
    text: str


@dataclass(frozen=True)
class EnrichmentResult:
    silver_job_id: int
    raw_job_id: int
    source_name: str
    status: str
    detail_source_url: str | None = None
    evidence_kind: str | None = None
    error: str | None = None


class TextAndLinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
            return
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if text:
            self.text_parts.append(text)


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_html_text_and_links(html: str, base_url: str) -> tuple[str, list[str]]:
    parser = TextAndLinkExtractor()
    parser.feed(html)
    text = normalize_text(" ".join(parser.text_parts))
    links = []
    for href in parser.links:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            links.append(absolute)
    return text[:MAX_DETAIL_TEXT_CHARS], list(dict.fromkeys(links))


def is_strong_detail_text(text: str, *, title: str | None, company: str | None) -> bool:
    normalized = normalize_text(text)
    if len(normalized) < MIN_STRONG_DETAIL_CHARS:
        return False
    haystack = normalized.casefold()
    title_tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9ÄÖÜäöüß]{4,}", (title or "").casefold())
    }
    company_tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9ÄÖÜäöüß]{4,}", (company or "").casefold())
    }
    title_match = not title_tokens or bool(title_tokens & set(re.findall(r"\w+", haystack)))
    company_match = not company_tokens or bool(company_tokens & set(re.findall(r"\w+", haystack)))
    return title_match and company_match


def is_probable_employer_origin_detail_url(url: str, *, discovery_url: str) -> bool:
    parsed = urlparse(url)
    discovery = urlparse(discovery_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.netloc.casefold().endswith(discovery.netloc.casefold()):
        return False
    path = parsed.path.casefold()
    return any(
        token in path
        for token in (
            "job",
            "jobs",
            "stellenangebot",
            "stellenangebote",
            "stellenanzeigen",
            "vacancy",
            "position",
            "requisition",
        )
    )


def is_concrete_employer_origin_detail_url(
    url: str,
    *,
    discovery_url: str,
    title: str | None,
) -> bool:
    if not is_probable_employer_origin_detail_url(url, discovery_url=discovery_url):
        return False
    path = urlparse(url).path.casefold()
    title_tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9ÄÖÜäöüß]{5,}", (title or "").casefold())
        if token not in {"senior", "manager", "engineer"}
    }
    if not title_tokens:
        return True
    return bool(title_tokens & set(re.findall(r"[a-zA-Z0-9ÄÖÜäöüß]+", path)))


def default_fetcher(url: str) -> DetailFetchResult:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    return DetailFetchResult(
        requested_url=url,
        final_url=response.url,
        status_code=response.status_code,
        text=response.text,
    )


def stored_detail_url(row: Mapping[str, Any]) -> str | None:
    source_url = row.get("source_url")
    if isinstance(source_url, str) and source_url.startswith(("http://", "https://")):
        return source_url
    raw_data = row.get("raw_data")
    if not isinstance(raw_data, Mapping):
        return None
    result_card = raw_data.get("result_card")
    if not isinstance(result_card, Mapping):
        return None
    detail_url = result_card.get("detail_url")
    if isinstance(detail_url, str) and detail_url.startswith(("http://", "https://")):
        return detail_url
    return None


def is_discovery_row(row: Mapping[str, Any]) -> bool:
    source_name = row.get("source_name")
    if not isinstance(source_name, str) or not source_name.strip():
        return False
    try:
        return source_role(source_name) == SourceRole.SENSOR
    except ValueError:
        return False


def is_weak_discovery_row(row: Mapping[str, Any]) -> bool:
    if not is_discovery_row(row):
        return False
    _description, _source, quality = extract_description(row.get("raw_data"))
    return quality == "weak"


def build_detail_evidence(
    row: Mapping[str, Any],
    *,
    fetcher: Callable[[str], DetailFetchResult] = default_fetcher,
) -> dict[str, Any] | None:
    url = stored_detail_url(row)
    if not url:
        return None

    detail = fetcher(url)
    if detail.status_code >= 400:
        return None
    text, links = parse_html_text_and_links(detail.text, detail.final_url)
    title = str(row.get("title") or "")
    company = str(row.get("company_name") or "")

    employer_candidate = None
    for candidate in links:
        if is_concrete_employer_origin_detail_url(
            candidate,
            discovery_url=detail.final_url,
            title=title,
        ):
            employer_candidate = candidate
            break

    if employer_candidate:
        employer_detail = fetcher(employer_candidate)
        if employer_detail.status_code < 400:
            employer_text, _links = parse_html_text_and_links(
                employer_detail.text,
                employer_detail.final_url,
            )
            if is_strong_detail_text(employer_text, title=title, company=company):
                return {
                    "text": employer_text,
                    "source_url": employer_detail.final_url,
                    "source_kind": "employer_origin_detail_page",
                    "description_quality": "strong",
                    "preferred_over": "aggregator_detail_page",
                    "original_discovery_source": row.get("source_name"),
                    "original_discovery_url": detail.final_url,
                    "enriched_at_utc": utc_timestamp(),
                    "raw_html_persisted": False,
                    "request_count": 2,
                }

    if not is_strong_detail_text(text, title=title, company=company):
        return None
    return {
        "text": text,
        "source_url": detail.final_url,
        "source_kind": "aggregator_detail_page",
        "description_quality": "strong",
        "original_discovery_source": row.get("source_name"),
        "original_discovery_url": url,
        "enriched_at_utc": utc_timestamp(),
        "raw_html_persisted": False,
        "request_count": 1,
        "employer_origin_candidate_urls": [
            link
            for link in links
            if is_concrete_employer_origin_detail_url(
                link,
                discovery_url=detail.final_url,
                title=title,
            )
        ][:MAX_EMPLOYER_ORIGIN_CANDIDATES],
    }


class DiscoveryDetailEnrichmentRepository:
    def __init__(self) -> None:
        self.connection_config = get_database_config()

    def get_connection(self):
        return psycopg.connect(**self.connection_config, row_factory=dict_row)

    def load_candidate_rows(self, *, source: str | None, limit: int) -> list[dict[str, Any]]:
        return SilverJobReadRepository().load_silver_jobs(
            limit=limit,
            source_patterns=normalize_source_patterns(source),
        )

    def update_detail_evidence(self, *, raw_job_id: int, evidence: Mapping[str, Any]) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE raw_jobs
                    SET raw_data = jsonb_set(
                        raw_data,
                        '{detail_evidence}',
                        %s::jsonb,
                        true
                    )
                    WHERE id = %s;
                    """,
                    (json.dumps(dict(evidence), ensure_ascii=False), raw_job_id),
                )
            conn.commit()

    def update_enrichment_state(
        self,
        *,
        raw_job_id: int,
        state: str,
        detail_url: str | None = None,
        error: str | None = None,
    ) -> None:
        payload = {
            "state": state,
            "detail_url": detail_url,
            "error": error,
            "updated_at_utc": utc_timestamp(),
            "raw_html_persisted": False,
        }
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE raw_jobs
                    SET raw_data = jsonb_set(
                        raw_data,
                        '{career_intelligence_detail_enrichment}',
                        %s::jsonb,
                        true
                    )
                    WHERE id = %s;
                    """,
                    (json.dumps(payload, ensure_ascii=False), raw_job_id),
                )
            conn.commit()


def enrich_weak_discovery_rows(
    *,
    repository: DiscoveryDetailEnrichmentRepository | None = None,
    source: str | None = None,
    limit: int = 100,
    fetcher: Callable[[str], DetailFetchResult] = default_fetcher,
) -> list[EnrichmentResult]:
    repository = repository or DiscoveryDetailEnrichmentRepository()
    results: list[EnrichmentResult] = []
    for row in repository.load_candidate_rows(source=source, limit=limit):
        if not is_weak_discovery_row(row):
            continue
        silver_job_id = int(row["silver_job_id"])
        raw_job_id = int(row["raw_job_id"])
        source_name = str(row["source_name"])
        url = stored_detail_url(row)
        if not url:
            repository.update_enrichment_state(
                raw_job_id=raw_job_id,
                state="DISCOVERED_NEEDS_DETAIL",
                detail_url=None,
                error="missing stored detail URL",
            )
            results.append(
                EnrichmentResult(silver_job_id, raw_job_id, source_name, "needs_detail")
            )
            continue
        try:
            evidence = build_detail_evidence(row, fetcher=fetcher)
            if evidence is None:
                repository.update_enrichment_state(
                    raw_job_id=raw_job_id,
                    state="DISCOVERED_NEEDS_DETAIL",
                    detail_url=url,
                    error="no strong detail evidence found",
                )
                results.append(
                    EnrichmentResult(
                        silver_job_id,
                        raw_job_id,
                        source_name,
                        "needs_detail",
                        detail_source_url=url,
                    )
                )
                continue
            repository.update_detail_evidence(raw_job_id=raw_job_id, evidence=evidence)
            repository.update_enrichment_state(
                raw_job_id=raw_job_id,
                state="DETAIL_ENRICHED",
                detail_url=str(evidence.get("source_url") or url),
            )
            results.append(
                EnrichmentResult(
                    silver_job_id,
                    raw_job_id,
                    source_name,
                    "enriched",
                    detail_source_url=str(evidence.get("source_url") or url),
                    evidence_kind=str(evidence.get("source_kind") or ""),
                )
            )
        except Exception as exc:
            repository.update_enrichment_state(
                raw_job_id=raw_job_id,
                state="DETAIL_ENRICHMENT_FAILED",
                detail_url=url,
                error=f"{type(exc).__name__}: {exc}",
            )
            results.append(
                EnrichmentResult(
                    silver_job_id,
                    raw_job_id,
                    source_name,
                    "failed",
                    detail_source_url=url,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


def summarize_enrichment(results: Iterable[EnrichmentResult]) -> dict[str, int]:
    summary = {"enriched": 0, "needs_detail": 0, "failed": 0}
    for result in results:
        if result.status in summary:
            summary[result.status] += 1
    return summary
