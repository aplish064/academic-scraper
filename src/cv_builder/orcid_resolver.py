"""Resolve ORCID records from work-backed evidence."""

from __future__ import annotations

from collections import Counter

from .builders import clean_text, normalize_openalex_id, normalize_orcid
from .matching import names_are_similar
from .orcid_client import _normalize_doi


class OrcidResolver:
    def __init__(self, orcid_client) -> None:
        self.orcid_client = orcid_client

    def resolve(self, openalex_author: dict, openalex_works: list[dict]) -> tuple[str, dict]:
        works = [work for work in openalex_works or [] if isinstance(work, dict)]
        if not works:
            return "", {}

        aliases = _author_aliases(openalex_author, works)

        doi_counts = self._count_doi_matches(works)
        doi_result = self._resolve_from_doi_counts(doi_counts, aliases)
        if doi_result != ("", {}):
            return doi_result

        title_counts = self._count_title_matches(works)
        return self._resolve_from_title_counts(title_counts, aliases)

    def _count_doi_matches(self, works: list[dict]) -> Counter:
        counts: Counter = Counter()
        for work in works:
            doi = _normalize_doi(clean_text(work.get("doi")))
            if not doi:
                continue
            counts.update(_normalized_orcids(self.orcid_client.search_by_doi(doi)))
        return counts

    def _resolve_from_doi_counts(self, counts: Counter, aliases: list[str]) -> tuple[str, dict]:
        for orcid, count in counts.most_common():
            if count < 2:
                continue
            record = self.orcid_client.get_record(orcid)
            if record:
                return orcid, record

        for orcid, count in counts.most_common():
            if count != 1:
                continue
            record = self.orcid_client.get_record(orcid)
            if record and _record_name_matches(record, aliases):
                return orcid, record

        return "", {}

    def _count_title_matches(self, works: list[dict]) -> Counter:
        counts: Counter = Counter()
        for work in works:
            title = clean_text(work.get("title") or work.get("display_name"))
            if not title:
                continue
            counts.update(_normalized_orcids(self.orcid_client.search_by_title(title)))
        return counts

    def _resolve_from_title_counts(self, counts: Counter, aliases: list[str]) -> tuple[str, dict]:
        for orcid, count in counts.most_common():
            if count < 2:
                continue
            record = self.orcid_client.get_record(orcid)
            if record and _record_name_matches(record, aliases):
                return orcid, record
        return "", {}


def _author_aliases(openalex_author: dict, works: list[dict]) -> list[str]:
    aliases = []
    author = openalex_author or {}
    target_author_id = normalize_openalex_id(author.get("id") or author.get("openalex_id"))
    author_name = clean_text(author.get("display_name"))
    if author_name:
        aliases.append(author_name)

    for work in works:
        for authorship in _ensure_list(work.get("authorships")):
            if not isinstance(authorship, dict):
                continue
            authorship_author = authorship.get("author") or {}
            authorship_author_id = normalize_openalex_id(
                authorship_author.get("id") or authorship_author.get("openalex_id")
            )
            if not target_author_id or authorship_author_id != target_author_id:
                continue
            authorship_name = clean_text(authorship_author.get("display_name"))
            if authorship_name:
                aliases.append(authorship_name)
    return _dedupe(aliases)


def _record_name_matches(record: dict, aliases: list[str]) -> bool:
    return any(names_are_similar(name, aliases) for name in _record_name_candidates(record))


def _record_name_candidates(record: dict) -> list[str]:
    name = (((record or {}).get("person") or {}).get("name") or {})
    credit_name = _orcid_name_value(name.get("credit-name"))
    given_names = _orcid_name_value(name.get("given-names"))
    family_name = _orcid_name_value(name.get("family-name"))

    candidates = [
        credit_name,
        " ".join(part for part in [given_names, family_name] if part),
        given_names,
        family_name,
    ]
    return _dedupe(candidate for candidate in candidates if candidate)


def _orcid_name_value(value) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("value"))
    return clean_text(value)


def _normalized_orcids(values) -> list[str]:
    return _dedupe(orcid for orcid in (normalize_orcid(value) for value in values or []) if orcid)


def _dedupe(values) -> list[str]:
    deduped = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _ensure_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
