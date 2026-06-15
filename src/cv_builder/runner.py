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
    build_semantic_research_output_row,
    clean_text,
    normalize_orcid,
)
from .ids import make_person_id


_LOG = logging.getLogger(__name__)
_OPENALEX_AUTHOR_ID_RE = re.compile(r"^A\d+$", re.IGNORECASE)


class CvBuildRunner:
    def __init__(
        self,
        repository,
        openalex_client,
        orcid_client,
        crossref_client,
        orcid_resolver=None,
        semantic_resolver=None,
    ) -> None:
        self.repository = repository
        self.openalex_client = openalex_client
        self.orcid_client = orcid_client
        self.crossref_client = crossref_client
        self.orcid_resolver = orcid_resolver
        self.semantic_resolver = semantic_resolver

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

            research_output_rows, openalex_works = self._build_openalex_research_outputs(
                author_id,
                person_id,
                work_limit,
            )

            orcid = normalize_orcid(openalex_author.get("orcid"))
            orcid_record = self.orcid_client.get_record(orcid) if orcid else {}
            if self.orcid_resolver and (not orcid or not orcid_record):
                resolved_orcid, resolved_record = self.orcid_resolver.resolve(openalex_author, openalex_works)
                resolved_orcid = normalize_orcid(resolved_orcid)
                if resolved_orcid and resolved_record:
                    openalex_author = {**openalex_author, "orcid": resolved_orcid}
                    orcid = resolved_orcid
                    orcid_record = resolved_record
            profile_row = build_profile_row(openalex_author, orcid_record)
            if not profile_row:
                self.repository.mark_author_status(author_id, person_id, "skipped", "invalid_profile")
                return ""

            experience_rows = build_experience_rows(person_id, orcid_record)
            funding_rows = build_funding_rows(person_id, orcid_record)
            if self.semantic_resolver:
                existing_work_ids = {row.get("id") for row in research_output_rows if row.get("id")}
                resolution = self.semantic_resolver.resolve(openalex_author, openalex_works, existing_work_ids)
                research_output_rows.extend(
                    self._build_semantic_supplemental_rows(person_id, resolution.supplemental_papers)
                )

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

    def _build_openalex_research_outputs(
        self,
        author_id: str,
        person_id: str,
        work_limit: int,
    ) -> tuple[list[dict], list[dict]]:
        rows = []
        openalex_works = []
        openalex_work_ids = self.openalex_client.get_author_work_ids(author_id, limit=work_limit)
        local_work_ids = self.repository.get_local_work_ids_for_author(author_id, work_limit)
        for work_id in _merge_work_ids(openalex_work_ids, local_work_ids, work_limit):
            openalex_work = self.openalex_client.get_work(work_id)
            if not openalex_work:
                continue

            openalex_works.append(openalex_work)
            doi = clean_text(openalex_work.get("doi"))
            crossref_work = self.crossref_client.get_work_by_doi(doi) if doi else {}
            row = build_research_output_row(person_id, openalex_work, crossref_work)
            if row:
                rows.append(row)
        return rows, openalex_works

    def _build_semantic_supplemental_rows(self, person_id: str, supplemental_papers: list[dict]) -> list[dict]:
        rows = []
        for paper in supplemental_papers or []:
            row = build_semantic_research_output_row(person_id, paper)
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
