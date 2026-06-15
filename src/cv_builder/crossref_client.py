"""Crossref API client for the Academic CV Builder."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit

import requests

from .config import CvBuilderConfig


_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)


def _normalize_doi(doi: str) -> str:
    normalized_doi = str(doi).strip()
    if not normalized_doi:
        return ""

    if normalized_doi.lower().startswith("doi:"):
        return unquote(normalized_doi[4:]).strip()

    parsed = urlsplit(normalized_doi)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"doi.org", "dx.doi.org"}:
        return unquote(parsed.path.lstrip("/")).strip()

    return unquote(normalized_doi).strip()


class CrossrefClient:
    def __init__(self, config: CvBuilderConfig) -> None:
        self.config = config
        self.session = requests.Session()

    def get_work_by_doi(self, doi: str) -> dict:
        normalized_doi = _normalize_doi(doi)
        if not normalized_doi:
            return {}
        if not _DOI_PATTERN.match(normalized_doi):
            return {}
        encoded_doi = quote(normalized_doi, safe="/")

        params = {}
        if self.config.crossref_mailto:
            params["mailto"] = self.config.crossref_mailto

        user_agent = self.config.crossref_user_agent
        if self.config.crossref_mailto:
            user_agent = f"{user_agent} (mailto:{self.config.crossref_mailto})"

        response = self.session.get(
            f"{self.config.crossref_base_url.rstrip('/')}/works/{encoded_doi}",
            headers={"User-Agent": user_agent},
            params=params,
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json().get("message", {})
