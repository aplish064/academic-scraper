"""ORCID API client for the Academic CV Builder."""

from __future__ import annotations

import re
import time
from urllib.parse import quote, urlsplit

import requests

from .config import CvBuilderConfig


_ORCID_PATTERN = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
_TOKEN_EXPIRY_SKEW_SECONDS = 60


def _normalize_orcid(orcid: str) -> str:
    value = str(orcid).strip()
    parsed = urlsplit(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value
    normalized_orcid = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    if not _ORCID_PATTERN.match(normalized_orcid):
        return ""
    return normalized_orcid


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

    def _get_record_response(self, encoded_orcid: str, token: str) -> requests.Response:
        return self.session.get(
            f"{self.config.orcid_base_url.rstrip('/')}/{encoded_orcid}/record",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            timeout=self.config.request_timeout,
        )
