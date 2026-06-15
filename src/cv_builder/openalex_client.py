"""OpenAlex API client for the Academic CV Builder."""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

import requests

from .config import CvBuilderConfig


_AUTHOR_ID_PATTERN = re.compile(r"^A\d+$")
_WORK_ID_PATTERN = re.compile(r"^W\d+$")


def _compact_openalex_id(openalex_id: str, pattern: re.Pattern[str]) -> str:
    value = str(openalex_id).strip()
    parsed = urlsplit(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value
    normalized_id = path.strip().rstrip("/").rsplit("/", 1)[-1]
    if not pattern.match(normalized_id):
        raise ValueError(f"Invalid OpenAlex ID: {openalex_id!r}")
    return normalized_id


def _normalize_openalex_id(openalex_id: str, pattern: re.Pattern[str]) -> str:
    normalized_id = _compact_openalex_id(openalex_id, pattern)
    return quote(normalized_id, safe="")


class OpenAlexClient:
    def __init__(self, config: CvBuilderConfig) -> None:
        self.config = config
        self.session = requests.Session()

    def get_author(self, openalex_author_id: str) -> dict:
        author_id = _normalize_openalex_id(openalex_author_id, _AUTHOR_ID_PATTERN)
        response = self.session.get(
            f"{self.config.openalex_base_url.rstrip('/')}/authors/{author_id}",
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def get_work(self, openalex_work_id: str) -> dict:
        work_id = _normalize_openalex_id(openalex_work_id, _WORK_ID_PATTERN)
        response = self.session.get(
            f"{self.config.openalex_base_url.rstrip('/')}/works/{work_id}",
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def get_author_work_ids(self, openalex_author_id: str, limit: int = 200) -> list[str]:
        if limit <= 0:
            return []

        author_id = _compact_openalex_id(openalex_author_id, _AUTHOR_ID_PATTERN)
        work_ids: list[str] = []
        seen: set[str] = set()
        cursor = "*"
        base_url = self.config.openalex_base_url.rstrip("/")

        while len(work_ids) < limit and cursor:
            remaining = limit - len(work_ids)
            response = self.session.get(
                f"{base_url}/works",
                params={
                    "filter": f"authorships.author.id:{author_id}",
                    "select": "id",
                    "per-page": min(200, remaining),
                    "cursor": cursor,
                },
                timeout=self.config.request_timeout,
            )
            if response.status_code == 404:
                return work_ids
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("results") or []:
                raw_work_id = item.get("id")
                if not raw_work_id:
                    continue
                try:
                    work_id = _compact_openalex_id(raw_work_id, _WORK_ID_PATTERN)
                except ValueError:
                    continue
                if work_id in seen:
                    continue
                seen.add(work_id)
                work_ids.append(work_id)
                if len(work_ids) >= limit:
                    break

            next_cursor = (payload.get("meta") or {}).get("next_cursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        return work_ids
