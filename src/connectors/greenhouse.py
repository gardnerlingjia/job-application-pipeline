import logging
from html import unescape
from html.parser import HTMLParser

import requests

from src.connectors.greenhouse_location import germany_location_decision

from src.connectors.base import JobSourceConnector, RawJobRecord
from src.connectors.capabilities import SourceCapabilities

class DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def description_text(content):
    if not isinstance(content, str):
        return ''
    parser = DescriptionText()
    parser.feed(unescape(content))
    return ' '.join(' '.join(parser.parts).split())


class GreenhouseConnector(JobSourceConnector):
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    capabilities = SourceCapabilities(
        supports_keyword=False,
        supports_location=False,
        supports_radius=False,
        supports_employment_type=False,
        supports_remote_filter=False,
        supports_pagination=False,
        supports_full_fetch=True,
    )

    def __init__(self, board_token: str) -> None:
        self.board_token = board_token
        self.source_name = f"greenhouse:{board_token}"

    def fetch_jobs(self, profile, search_term) -> tuple[list[RawJobRecord], str]:
        requested_url = f"{self.BASE_URL}/{self.board_token}/jobs?content=true"

        response = requests.get(
            requested_url,
            timeout=30,
        )

        response.raise_for_status()

        payload = response.json()
        jobs = payload.get("jobs", [])

        records = []
        self.last_location_filter_report = []
        germany_scope = (profile.search_location or '').strip().casefold() in {
            'germany', 'deutschland'}

        for job in jobs:
            location_evidence = germany_location_decision(job) if germany_scope else None
            if location_evidence:
                audit = {'external_job_id': str(job['id']), **location_evidence}
                self.last_location_filter_report.append(audit)
                logging.getLogger(__name__).info('Greenhouse Germany filter: %s', audit)
                if location_evidence['decision'] != 'retained':
                    continue
            captured_job = dict(job)
            # Preserve provider HTML verbatim and expose untruncated plain text to assessors.
            text = description_text(job.get('content'))
            if text:
                captured_job['description'] = text
            records.append(
                RawJobRecord(
                    source_name=self.source_name,
                    external_job_id=str(job["id"]),
                    source_url=job.get("absolute_url"),
                    raw_data={
                        "board_token": self.board_token,
                        "job": captured_job,
                        **({'location_filter': location_evidence,
                            'acquisition_scope': 'germany_metadata_only'} if germany_scope else {}),
                    },
                )
            )

        return records, requested_url
