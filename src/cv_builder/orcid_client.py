"""ORCID API client for the Academic CV Builder."""

from __future__ import annotations

import re
import time
from urllib.parse import quote, unquote, urlsplit

import requests

from .config import CvBuilderConfig


_ORCID_PATTERN = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_TOKEN_EXPIRY_SKEW_SECONDS = 60


def _normalize_orcid(orcid: str) -> str:
    value = str(orcid).strip()
    parsed = urlsplit(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value
    normalized_orcid = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    if not _ORCID_PATTERN.match(normalized_orcid):
        return ""
    return normalized_orcid


def _normalize_doi(value: str) -> str:
    normalized_doi = str(value).strip()
    if not normalized_doi:
        return ""

    if normalized_doi.lower().startswith("doi:"):
        return unquote(normalized_doi[4:]).strip()

    parsed = urlsplit(normalized_doi)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"doi.org", "dx.doi.org"}:
        return unquote(parsed.path.lstrip("/")).strip()

    return unquote(normalized_doi).strip()


def _is_safe_search_term(value: str) -> bool:
    return '"' not in value and "\\" not in value


class OrcidClient:
    def __init__(self, config: CvBuilderConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self._token = ""
        self._token_expires_at: float | None = None

    def get_token(self) -> str:
        if self._token and self._token_is_fresh():
            return self._token
        if not self.config.orcid_client_id or not self.config.orcid_client_secret:
            return ""

        response = self.session.post(
            self.config.orcid_token_url,
            data={
                "client_id": self.config.orcid_client_id,
                "client_secret": self.config.orcid_client_secret,
                "grant_type": "client_credentials",
                "scope": "/read-public",
            },
            headers={"Accept": "application/json"},
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()
        token_response = response.json()
        self._token = token_response.get("access_token", "")
        self._token_expires_at = self._get_token_expires_at(token_response)
        return self._token

    def _token_is_fresh(self) -> bool:
        if self._token_expires_at is None:
            return True
        return time.time() < self._token_expires_at - _TOKEN_EXPIRY_SKEW_SECONDS

    def _get_token_expires_at(self, token_response: dict) -> float | None:
        expires_in = token_response.get("expires_in")
        if expires_in is None:
            return None
        try:
            return time.time() + float(expires_in)
        except (TypeError, ValueError):
            return None

    def _clear_token(self) -> None:
        self._token = ""
        self._token_expires_at = None

    def get_record(self, orcid: str) -> dict:
        normalized_orcid = _normalize_orcid(orcid)
        if not normalized_orcid:
            return {}

        token = self.get_token()
        if not token:
            return {}

        encoded_orcid = quote(normalized_orcid, safe="")
        response = self._get_record_response(encoded_orcid, token)
        if response.status_code == 401:
            self._clear_token()
            token = self.get_token()
            if not token:
                return {}
            response = self._get_record_response(encoded_orcid, token)

        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def search_by_doi(self, doi: str) -> list[str]:
        normalized_doi = _normalize_doi(doi)
        if not normalized_doi or not _DOI_PATTERN.match(normalized_doi) or not _is_safe_search_term(normalized_doi):
            return []
        return self._expanded_search(f'doi-self:"{normalized_doi}"')

    def search_by_title(self, title: str) -> list[str]:
        normalized_title = " ".join(str(title).strip().split())
        if not normalized_title or not _is_safe_search_term(normalized_title):
            return []
        return self._expanded_search(f'work-titles:"{normalized_title}"')

    def _expanded_search(self, query: str) -> list[str]:
        token = self.get_token()
        if not token:
            return []

        response = self.session.get(
            f"{self.config.orcid_base_url.rstrip('/')}/expanded-search/",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            params={"q": query},
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        results = response.json().get("result", [])

        orcids = []
        seen = set()
        for result in results:
            if not isinstance(result, dict):
                continue
            normalized_orcid = _normalize_orcid(((result.get("orcid-identifier") or {}).get("path") or ""))
            if not normalized_orcid or normalized_orcid in seen:
                continue
            seen.add(normalized_orcid)
            orcids.append(normalized_orcid)
        return orcids

    def _get_record_response(self, encoded_orcid: str, token: str) -> requests.Response:
        return self.session.get(
            f"{self.config.orcid_base_url.rstrip('/')}/{encoded_orcid}/record",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=self.config.request_timeout,
        )
