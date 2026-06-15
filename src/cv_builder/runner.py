"""End-to-end runner for building one academic CV profile."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from .builders import (
    build_experience_rows,
    build_funding_rows,
    build_profile_row,
    build_research_output_row,
    clean_text,
    normalize_orcid,
)
from .ids import make_person_id


_LOG = logging.getLogger(__name__)
_OPENALEX_AUTHOR_ID_RE = re.compile(r"^A\d+$", re.IGNORECASE)


class CvBuildRunner:
    def __init__(self, repository, openalex_client, orcid_client, crossref_client) -> None:
        self.repository = repository
        self.openalex_client = openalex_client
        self.orcid_client = orcid_client
        self.crossref_client = crossref_client

    def process_author(
        self,
        openalex_author_id: str,
        work_limit: int = 200,
        already_processing: bool = False,
    ) -> str:
        author_id = _normalize_runner_author_id(openalex_author_id)
        if not author_id:
            return ""

        person_id = make_person_id(author_id)
        try:
            if not already_processing:
                self.repository.mark_author_status(author_id, person_id, "processing")

            openalex_author = self.openalex_client.get_author(author_id)
            if not openalex_author:
                self.repository.mark_author_status(
                    author_id,
                    person_id,
                    "skipped",
                    "openalex_author_not_found",
                )
                return person_id

            orcid = normalize_orcid(openalex_author.get("orcid"))
            orcid_record = self.orcid_client.get_record(orcid) if orcid else {}

            profile_row = build_profile_row(openalex_author, orcid_record)
            if not profile_row:
                self.repository.mark_author_status(author_id, person_id, "skipped", "invalid_profile")
                return ""

            experience_rows = build_experience_rows(person_id, orcid_record)
            funding_rows = build_funding_rows(person_id, orcid_record)
            research_output_rows = self._build_research_output_rows(author_id, person_id, work_limit)

            self.repository.upsert_profile(profile_row)
            self.repository.upsert_experiences(experience_rows)
            self.repository.upsert_funding(funding_rows)
            self.repository.upsert_research_outputs(research_output_rows)
            self.repository.mark_author_status(author_id, person_id, "done")
            return person_id
        except Exception as exc:
            try:
                self.repository.mark_author_status(author_id, person_id, "failed", f"{type(exc).__name__}: {exc}")
            except Exception:
                _LOG.exception("Failed to mark CV build failure for %s", author_id)
            raise

    def _build_research_output_rows(self, author_id: str, person_id: str, work_limit: int) -> list[dict]:
        rows = []
        openalex_work_ids = self.openalex_client.get_author_work_ids(author_id, limit=work_limit)
        local_work_ids = self.repository.get_local_work_ids_for_author(author_id, work_limit)
        for work_id in _merge_work_ids(openalex_work_ids, local_work_ids, work_limit):
            openalex_work = self.openalex_client.get_work(work_id)
            if not openalex_work:
                continue

            doi = clean_text(openalex_work.get("doi"))
            crossref_work = self.crossref_client.get_work_by_doi(doi) if doi else {}
            row = build_research_output_row(person_id, openalex_work, crossref_work)
            if row:
                rows.append(row)
        return rows


def _normalize_runner_author_id(value) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    candidate = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    if _OPENALEX_AUTHOR_ID_RE.fullmatch(candidate):
        return candidate
    return ""


def _merge_work_ids(api_work_ids, local_work_ids, limit: int) -> list[str]:
    if limit <= 0:
        return []

    merged = []
    seen = set()
    for work_id in list(api_work_ids or []) + list(local_work_ids or []):
        normalized = clean_text(work_id).upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
        if len(merged) >= limit:
            break
    return merged
