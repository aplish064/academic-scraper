"""Resolve Semantic Scholar authors from OpenAlex work-backed evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from .builders import clean_text
from .matching import names_are_similar, normalize_title, titles_are_similar, years_are_compatible


@dataclass(frozen=True)
class SemanticScholarResolution:
    confirmed_author: dict
    supplemental_papers: list[dict]


class SemanticScholarResolver:
    def __init__(self, semantic_client) -> None:
        self.semantic_client = semantic_client

    def resolve(
        self,
        openalex_author: dict,
        openalex_works: list[dict],
        existing_work_ids: set[str],
    ) -> SemanticScholarResolution:
        works = [work for work in openalex_works or [] if isinstance(work, dict)]
        if not works:
            return _empty_resolution()

        aliases = _target_aliases(openalex_author, works)
        counts, doi_exact_counts = self._count_author_evidence(works, aliases)
        author_id = _confirmed_author_id(counts, doi_exact_counts)
        if not author_id:
            return _empty_resolution()

        confirmed_author = self.semantic_client.get_author(author_id)
        if not confirmed_author:
            return _empty_resolution()

        supplemental_papers = _supplemental_papers(
            confirmed_author,
            author_id,
            aliases,
            works,
            existing_work_ids,
        )
        return SemanticScholarResolution(confirmed_author, supplemental_papers)

    def _count_author_evidence(self, works: list[dict], aliases: list[str]) -> tuple[Counter, Counter]:
        counts: Counter = Counter()
        doi_exact_counts: Counter = Counter()

        for work in works:
            paper, doi_exact = self._semantic_paper_for_work(work)
            if not paper:
                continue
            for author in _paper_authors(paper):
                author_id = clean_text(author.get("authorId"))
                author_name = clean_text(author.get("name"))
                if not author_id or not names_are_similar(author_name, aliases):
                    continue
                counts[author_id] += 1
                if doi_exact:
                    doi_exact_counts[author_id] += 1

        return counts, doi_exact_counts

    def _semantic_paper_for_work(self, work: dict) -> tuple[dict, bool]:
        doi = _normalize_doi(work.get("doi"))
        if doi:
            paper = self.semantic_client.get_paper_by_doi(doi)
            if not isinstance(paper, dict) or not paper:
                return {}, False
            return (paper, True) if _doi_exact_match(doi, paper) else ({}, False)

        title = _work_title(work)
        if not title:
            return {}, False
        for candidate in self.semantic_client.search_papers_by_title(title) or []:
            if _title_year_match(work, candidate):
                return candidate, False
        return {}, False


def _empty_resolution() -> SemanticScholarResolution:
    return SemanticScholarResolution({}, [])


def _confirmed_author_id(counts: Counter, doi_exact_counts: Counter) -> str:
    for author_id, count in counts.most_common():
        if count >= 2 or doi_exact_counts[author_id] >= 1:
            return author_id
    return ""


def _target_aliases(openalex_author: dict, works: list[dict]) -> list[str]:
    aliases = []
    author = openalex_author or {}
    target_author_id = _normalize_openalex_author_id(author.get("id") or author.get("openalex_id"))
    author_name = clean_text(author.get("display_name"))
    if author_name:
        aliases.append(author_name)

    for work in works:
        for authorship in _ensure_list(work.get("authorships")):
            if not isinstance(authorship, dict):
                continue
            authorship_author = authorship.get("author") or {}
            authorship_author_id = _normalize_openalex_author_id(
                authorship_author.get("id") or authorship_author.get("openalex_id")
            )
            if not target_author_id or authorship_author_id != target_author_id:
                continue
            authorship_name = clean_text(authorship_author.get("display_name"))
            if authorship_name:
                aliases.append(authorship_name)

    return _dedupe(aliases)


def _supplemental_papers(
    confirmed_author: dict,
    author_id: str,
    aliases: list[str],
    openalex_works: list[dict],
    existing_work_ids: set[str],
) -> list[dict]:
    openalex_dois = {_normalize_doi(work.get("doi")) for work in openalex_works}
    openalex_dois.discard("")
    existing_keys = {clean_text(value).lower() for value in existing_work_ids or set() if clean_text(value)}
    seen_keys = set()
    papers = []

    for paper in _ensure_list((confirmed_author or {}).get("papers")):
        if not isinstance(paper, dict):
            continue
        if not _paper_has_confirmed_author(paper, author_id, aliases):
            continue

        paper_doi = _paper_doi(paper)
        if paper_doi and paper_doi in openalex_dois:
            continue

        key = _paper_key(paper)
        paper_id_key = f"s2:{clean_text(paper.get('paperId'))}".lower()
        if key in seen_keys or key in existing_keys or paper_id_key in existing_keys:
            continue

        seen_keys.add(key)
        if paper_id_key:
            seen_keys.add(paper_id_key)
        papers.append(paper)

    return papers


def _paper_has_confirmed_author(paper: dict, author_id: str, aliases: list[str]) -> bool:
    for author in _paper_authors(paper):
        if clean_text(author.get("authorId")) != author_id:
            continue
        if names_are_similar(clean_text(author.get("name")), aliases):
            return True
    return False


def _doi_exact_match(work_doi: str, paper: dict) -> bool:
    return bool(work_doi and work_doi == _paper_doi(paper))


def _title_year_match(work: dict, paper: dict) -> bool:
    return titles_are_similar(_work_title(work), paper.get("title")) and years_are_compatible(
        _work_year(work), paper.get("year")
    )


def _work_title(work: dict) -> str:
    return clean_text(work.get("title") or work.get("display_name"))


def _work_year(work: dict):
    return work.get("publication_year") or work.get("year")


def _paper_doi(paper: dict) -> str:
    external_ids = (paper or {}).get("externalIds") or {}
    return _normalize_doi(external_ids.get("DOI") or external_ids.get("doi") or paper.get("doi"))


def _paper_authors(paper: dict) -> list[dict]:
    return [author for author in _ensure_list((paper or {}).get("authors")) if isinstance(author, dict)]


def _paper_key(paper) -> str:
    paper = paper or {}
    doi = _paper_doi(paper)
    if doi:
        return f"doi:{doi}"

    paper_id = clean_text(paper.get("paperId"))
    if paper_id:
        return f"s2:{paper_id}"

    title = normalize_title(paper.get("title"))
    year = clean_text(paper.get("year"))
    return f"title:{title}:{year}"


def _normalize_openalex_author_id(value) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    candidate = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    return candidate if candidate.startswith("A") else ""


def _normalize_doi(value) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if text.lower().startswith("doi:"):
        text = text[4:]

    parsed = urlsplit(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"doi.org", "dx.doi.org"}:
        text = parsed.path.lstrip("/")

    return unquote(text).strip().lower()


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
