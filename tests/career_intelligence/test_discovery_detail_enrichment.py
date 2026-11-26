from src.career_intelligence.discovery_detail_enrichment import (
    DetailFetchResult,
    build_detail_evidence,
    enrich_weak_discovery_rows,
    is_weak_discovery_row,
    summarize_enrichment,
)
from src.career_intelligence.silver_adapter import adapt_silver_row, adapt_silver_rows


def stepstone_row(**overrides):
    row = {
        "silver_job_id": 3,
        "raw_job_id": 7,
        "source_name": "stepstone",
        "external_job_id": "14202824",
        "source_url": "https://www.stepstone.de/stellenangebote--AI--14202824-inline.html",
        "title": "AI Automation Manager / Product Owner (m/w/d)",
        "company_name": "Ajaska GmbH",
        "city": "München",
        "postal_code": None,
        "country": None,
        "publication_date": None,
        "first_seen_at": "2026-09-06T07:31:27+00:00",
        "last_seen_at": "2026-09-06T07:31:27+00:00",
        "canonical_source_type": "unknown",
        "canonical_key_candidate": (
            "ajaska gmbh :: ai automation manager / product owner (m/w/d) :: münchen"
        ),
        "raw_data": {
            "result_card": {
                "title": "AI Automation Manager / Product Owner (m/w/d)",
                "location": "München",
                "detail_url": "https://www.stepstone.de/stellenangebote--AI--14202824-inline.html",
                "company_name": "Ajaska GmbH",
                "publication_hint_text": "vor 1 Woche",
            },
            "source_specific": {
                "raw_card_text": (
                    "AI Automation Manager / Product Owner (m/w/d) Ajaska GmbH "
                    "München KI Automatisierung Produktmanager"
                ),
            },
        },
    }
    row.update(overrides)
    return row


def strong_html(*, link: str | None = None) -> str:
    employer_link = f'<a href="{link}">Apply on employer site</a>' if link else ""
    return (
        "<html><body><main>"
        "<h1>AI Automation Manager / Product Owner (m/w/d)</h1>"
        "<p>Ajaska GmbH builds automation products for analytics, reporting, "
        "data platforms and operational teams. This role leads AI automation "
        "delivery, product ownership, stakeholder alignment, roadmap execution, "
        "workflow design and cross-functional implementation in Germany.</p>"
        "<p>The position requires senior product leadership, analytics fluency, "
        "program coordination, automation strategy, experimentation, and careful "
        "delivery across engineering, operations and commercial teams.</p>"
        f"{employer_link}</main></body></html>"
    )


def test_weak_discovery_card_remains_unscored_without_detail():
    row = stepstone_row()

    assert is_weak_discovery_row(row) is True
    inputs, errors = adapt_silver_rows([row])

    assert inputs == []
    assert errors[0]["error"] == (
        "insufficient description evidence: weak listing/card text is not scored"
    )


def test_strong_detail_enrichment_enables_ci_conversion():
    row = stepstone_row()

    evidence = build_detail_evidence(
        row,
        fetcher=lambda url: DetailFetchResult(url, url, 200, strong_html()),
    )
    enriched = dict(row)
    enriched["raw_data"] = dict(row["raw_data"], detail_evidence=evidence)

    result = adapt_silver_row(enriched)

    assert evidence is not None
    assert evidence["source_kind"] == "aggregator_detail_page"
    assert evidence["original_discovery_source"] == "stepstone"
    assert result.description_quality == "strong"
    assert result.provenance["description_source"] == "detail_evidence.text"


def test_employer_origin_detail_is_preferred_over_aggregator_detail():
    row = stepstone_row()
    employer_url = "https://ajaska.example/careers/jobs/ai-automation-manager"

    def fetcher(url):
        if url == employer_url:
            return DetailFetchResult(url, url, 200, strong_html())
        return DetailFetchResult(url, url, 200, strong_html(link=employer_url))

    evidence = build_detail_evidence(row, fetcher=fetcher)

    assert evidence is not None
    assert evidence["source_kind"] == "employer_origin_detail_page"
    assert evidence["source_url"] == employer_url
    assert evidence["preferred_over"] == "aggregator_detail_page"
    assert evidence["original_discovery_source"] == "stepstone"


def test_generic_employer_career_page_does_not_outrank_aggregator_detail():
    row = stepstone_row()
    employer_url = "https://ajaska.example/careers/corporate-benefits"

    def fetcher(url):
        if url == employer_url:
            return DetailFetchResult(url, url, 200, strong_html())
        return DetailFetchResult(url, url, 200, strong_html(link=employer_url))

    evidence = build_detail_evidence(row, fetcher=fetcher)

    assert evidence is not None
    assert evidence["source_kind"] == "aggregator_detail_page"
    assert evidence["source_url"] == row["source_url"]


def test_failed_enrichment_does_not_break_other_records():
    calls = []

    class FakeRepository:
        def load_candidate_rows(self, *, source, limit):
            return [stepstone_row()]

        def update_detail_evidence(self, *, raw_job_id, evidence):
            calls.append(("detail", raw_job_id, evidence))

        def update_enrichment_state(self, *, raw_job_id, state, detail_url=None, error=None):
            calls.append(("state", raw_job_id, state, detail_url, error))

    def fetcher(url):
        raise TimeoutError("detail timeout")

    results = enrich_weak_discovery_rows(repository=FakeRepository(), fetcher=fetcher)

    assert summarize_enrichment(results) == {"enriched": 0, "needs_detail": 0, "failed": 1}
    assert results[0].status == "failed"
    assert calls[0][2] == "DETAIL_ENRICHMENT_FAILED"


def test_moia_employer_origin_row_is_not_discovery_enrichment_candidate():
    row = stepstone_row(
        source_name="greenhouse:moia",
        canonical_source_type="employer_origin_ats_backed_career_site",
    )

    assert is_weak_discovery_row(row) is False
