"""Stable internal IDs for CV builder entities."""

from __future__ import annotations

import hashlib
import json
import re


_OPENALEX_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?openalex\.org/([^?#\s]+)",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    normalized = str(value).strip()
    match = _OPENALEX_URL_PATTERN.search(normalized)
    if match:
        normalized = match.group(1).rstrip("/").rsplit("/", 1)[-1]
    return normalized.lower()


def _hash_id(prefix: str, *parts: str) -> str:
    normalized_parts = [_normalize(part) for part in parts]
    payload = json.dumps(normalized_parts, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def make_person_id(openalex_author_id: str) -> str:
    normalized_author_id = _normalize(openalex_author_id)
    if not normalized_author_id:
        raise ValueError("openalex_author_id is required")
    return _hash_id("person", openalex_author_id)


def make_experience_id(
    person_id: str,
    source: str,
    role_title: str,
    institution_name: str,
    start_date: str,
    end_date: str,
    external_id: str = "",
    department_name: str = "",
) -> str:
    return _hash_id(
        "exp",
        person_id,
        source,
        role_title,
        institution_name,
        start_date,
        end_date,
        external_id,
        department_name,
    )


def make_research_output_id(person_id: str, work_external_id: str) -> str:
    return _hash_id("work", person_id, work_external_id)


def make_funding_id(
    person_id: str,
    source: str,
    funding_external_id: str,
    funder_name: str,
    award_title: str,
) -> str:
    return _hash_id(
        "fund",
        person_id,
        source,
        funding_external_id,
        funder_name,
        award_title,
    )
