"""Semantic Scholar API client for the Academic CV Builder."""

from __future__ import annotations

from urllib.parse import quote

import requests

from .config import CvBuilderConfig


PAPER_FIELDS = ",".join(
    [
        "paperId",
        "externalIds",
        "url",
        "title",
        "abstract",
        "venue",
        "year",
        "publicationDate",
        "publicationTypes",
        "journal",
        "authors",
        "citationCount",
        "referenceCount",
        "influentialCitationCount",
        "fieldsOfStudy",
        "s2FieldsOfStudy",
        "openAccessPdf",
    ]
)

AUTHOR_FIELDS = ",".join(
    [
        "authorId",
        "name",
        "aliases",
        "url",
        "homepage",
        "paperCount",
        "citationCount",
        "hIndex",
        "papers.paperId",
        "papers.title",
        "papers.year",
        "papers.citationCount",
        "papers.externalIds",
        "papers.authors",
    ]
)


def _normalize_doi(doi: str) -> str:
    normalized_doi = str(doi).strip()
    if normalized_doi.lower().startswith("doi:"):
        return normalized_doi[4:].strip()
    return normalized_doi


class SemanticScholarClient:
    def __init__(self, config: CvBuilderConfig) -> None:
        self.config = config
        self.session = requests.Session()

    def get_paper_by_doi(self, doi: str) -> dict:
        normalized_doi = _normalize_doi(doi)
        if not normalized_doi:
            return {}

        encoded_doi = quote(normalized_doi, safe="")
        response = self.session.get(
            f"{self.config.semantic_base_url.rstrip('/')}/paper/DOI:{encoded_doi}",
            headers=self._headers(),
            params={"fields": PAPER_FIELDS},
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def search_papers_by_title(self, title: str, limit: int = 5) -> list[dict]:
        normalized_title = str(title).strip()
        if not normalized_title or limit <= 0:
            return []

        response = self.session.get(
            f"{self.config.semantic_base_url.rstrip('/')}/paper/search",
            headers=self._headers(),
            params={
                "query": normalized_title,
                "limit": limit,
                "fields": PAPER_FIELDS,
            },
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json().get("data", [])

    def get_author(self, author_id: str) -> dict:
        normalized_author_id = str(author_id).strip()
        if not normalized_author_id:
            return {}

        encoded_author_id = quote(normalized_author_id, safe="")
        response = self.session.get(
            f"{self.config.semantic_base_url.rstrip('/')}/author/{encoded_author_id}",
            headers=self._headers(),
            params={"fields": AUTHOR_FIELDS},
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict[str, str]:
        if not self.config.semantic_api_key:
            return {}
        return {"x-api-key": self.config.semantic_api_key}
