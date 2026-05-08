from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from .models import AuthorObservation
from .normalization import (
    build_source_row_key,
    normalize_author_name,
    normalize_doi,
    normalize_title,
    stable_u64,
)


def parse_date(value: Any) -> Optional[date]:
    def normalize_supported_date(parsed_date: date) -> Optional[date]:
        # ClickHouse Date supports a limited range; keep out-of-range values as NULL
        # while preserving publication_year separately.
        if parsed_date.year < 1970 or parsed_date.year > 2149:
            return None
        return parsed_date

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return normalize_supported_date(value.date())
    if isinstance(value, date):
        return normalize_supported_date(value)
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return normalize_supported_date(parsed.date())
        except ValueError:
            continue
    return None


def parse_year(value: Any, fallback_date: Optional[date]) -> int:
    if value not in (None, ""):
        try:
            return int(str(value)[:4])
        except (TypeError, ValueError):
            pass
    return fallback_date.year if fallback_date else 0


def parse_datetime(value: Any, fallback: datetime) -> datetime:
    def to_naive_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    if isinstance(value, datetime):
        return to_naive_utc(value)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if value:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue
    return to_naive_utc(fallback)


def normalize_role(tag: Any, rank: int) -> str:
    text = str(tag or "").lower()
    if text in {"first", "第一作者"} or rank == 1:
        return "first"
    if text in {"last", "最后作者"}:
        return "last"
    if text in {"other", "其他"}:
        return "other"
    return "unknown"


def build_observation(
    source: str,
    source_paper_id: str,
    source_author_id: str,
    author_name: str,
    author_rank: int,
    author_role: str,
    doi: str,
    arxiv_id: str,
    dblp_key: str,
    semantic_id: str,
    openalex_id: str,
    title: str,
    publication_date: Optional[date],
    publication_year: int,
    venue: str,
    institution_id: str,
    institution_name: str,
    institution_country: str,
    raw_affiliation: str,
    citation_count: int,
    fwci: float,
    primary_topic: str,
    ccf_class: str,
    source_import_time: datetime,
    observed_at: datetime,
    pipeline_run_id: str,
) -> AuthorObservation:
    normalized_author_name = normalize_author_name(author_name)
    normalized_title = normalize_title(title)
    source_row_key = build_source_row_key(
        source=source,
        source_paper_id=source_paper_id,
        author_rank=author_rank,
        source_author_id=source_author_id,
        normalized_author_name=normalized_author_name,
    )
    observation_id = stable_u64(source_row_key)
    return AuthorObservation(
        observation_id=observation_id,
        source=source,
        source_row_key=source_row_key,
        source_paper_id=source_paper_id,
        source_author_id=source_author_id,
        author_name=author_name or "",
        normalized_author_name=normalized_author_name,
        author_rank=author_rank,
        author_role=author_role,
        doi=normalize_doi(doi),
        arxiv_id=arxiv_id or "",
        dblp_key=dblp_key or "",
        semantic_id=semantic_id or "",
        openalex_id=openalex_id or "",
        title=title or "",
        normalized_title=normalized_title,
        publication_date=publication_date,
        publication_year=publication_year,
        venue=venue or "",
        institution_id=institution_id or "",
        institution_name=institution_name or "",
        institution_country=institution_country or "",
        raw_affiliation=raw_affiliation or "",
        citation_count=max(0, int(citation_count or 0)),
        fwci=float(fwci or 0),
        primary_topic=primary_topic or "",
        ccf_class=ccf_class or "",
        source_import_time=source_import_time,
        observed_at=observed_at,
        pipeline_run_id=pipeline_run_id,
    )


def map_openalex_row(row: Dict[str, Any], pipeline_run_id: str, observed_at: datetime) -> AuthorObservation:
    pub_date = parse_date(row.get("publication_date"))
    rank = int(row.get("rank") or 0)
    return build_observation(
        source="openalex",
        source_paper_id=str(row.get("uid") or ""),
        source_author_id=str(row.get("author_id") or ""),
        author_name=str(row.get("author") or ""),
        author_rank=rank,
        author_role=normalize_role(row.get("tag"), rank),
        doi=str(row.get("doi") or ""),
        arxiv_id="",
        dblp_key="",
        semantic_id="",
        openalex_id=str(row.get("uid") or ""),
        title=str(row.get("title") or ""),
        publication_date=pub_date,
        publication_year=parse_year(row.get("publication_date"), pub_date),
        venue=str(row.get("journal") or ""),
        institution_id=str(row.get("institution_id") or ""),
        institution_name=str(row.get("institution_name") or ""),
        institution_country=str(row.get("institution_country") or ""),
        raw_affiliation=str(row.get("raw_affiliation") or ""),
        citation_count=int(row.get("citation_count") or 0),
        fwci=float(row.get("fwci") or 0),
        primary_topic=str(row.get("primary_topic") or ""),
        ccf_class="",
        source_import_time=parse_datetime(row.get("import_time"), observed_at),
        observed_at=observed_at,
        pipeline_run_id=pipeline_run_id,
    )


def map_semantic_row(row: Dict[str, Any], pipeline_run_id: str, observed_at: datetime) -> AuthorObservation:
    pub_date = parse_date(row.get("publication_date"))
    rank = int(row.get("rank") or 0)
    return build_observation(
        source="semantic",
        source_paper_id=str(row.get("uid") or ""),
        source_author_id=str(row.get("author_id") or ""),
        author_name=str(row.get("author") or ""),
        author_rank=rank,
        author_role=normalize_role(row.get("tag"), rank),
        doi=str(row.get("doi") or ""),
        arxiv_id=str(row.get("arxiv_id") or ""),
        dblp_key="",
        semantic_id=str(row.get("uid") or ""),
        openalex_id="",
        title=str(row.get("title") or ""),
        publication_date=pub_date,
        publication_year=parse_year(row.get("year"), pub_date),
        venue=str(row.get("venue") or row.get("journal") or row.get("journal_name") or ""),
        institution_id=str(row.get("institution_id") or ""),
        institution_name=str(row.get("institution_name") or ""),
        institution_country=str(row.get("institution_country") or ""),
        raw_affiliation=str(row.get("raw_affiliation") or ""),
        citation_count=int(row.get("citation_count") or 0),
        fwci=0.0,
        primary_topic="",
        ccf_class="",
        source_import_time=parse_datetime(row.get("import_time"), observed_at),
        observed_at=observed_at,
        pipeline_run_id=pipeline_run_id,
    )


def map_arxiv_row(row: Dict[str, Any], pipeline_run_id: str, observed_at: datetime) -> AuthorObservation:
    pub_date = parse_date(row.get("published"))
    rank = int(row.get("rank") or 0)
    arxiv_id = str(row.get("arxiv_id") or "")
    return build_observation(
        source="arxiv",
        source_paper_id=arxiv_id,
        source_author_id="",
        author_name=str(row.get("author") or ""),
        author_rank=rank,
        author_role=normalize_role(row.get("tag"), rank),
        doi="",
        arxiv_id=arxiv_id,
        dblp_key="",
        semantic_id="",
        openalex_id="",
        title=str(row.get("title") or ""),
        publication_date=pub_date,
        publication_year=parse_year(row.get("published"), pub_date),
        venue=str(row.get("journal_ref") or ""),
        institution_id="",
        institution_name=str(row.get("affiliation") or ""),
        institution_country="",
        raw_affiliation=str(row.get("affiliation") or ""),
        citation_count=0,
        fwci=0.0,
        primary_topic=str(row.get("primary_category") or ""),
        ccf_class="",
        source_import_time=parse_datetime(row.get("import_date"), observed_at),
        observed_at=observed_at,
        pipeline_run_id=pipeline_run_id,
    )


def map_dblp_row(row: Dict[str, Any], pipeline_run_id: str, observed_at: datetime) -> AuthorObservation:
    pub_date = parse_date(row.get("publication_date"))
    rank = int(row.get("author_rank") or 0)
    dblp_key = str(row.get("dblp_key") or "")
    return build_observation(
        source="dblp",
        source_paper_id=dblp_key,
        source_author_id=str(row.get("author_pid") or ""),
        author_name=str(row.get("author_name") or ""),
        author_rank=rank,
        author_role=normalize_role(row.get("author_role"), rank),
        doi=str(row.get("doi") or ""),
        arxiv_id="",
        dblp_key=dblp_key,
        semantic_id="",
        openalex_id="",
        title=str(row.get("title") or ""),
        publication_date=pub_date,
        publication_year=parse_year(row.get("year"), pub_date),
        venue=str(row.get("venue") or ""),
        institution_id="",
        institution_name=str(row.get("institution") or row.get("affiliation_csrankings") or ""),
        institution_country="",
        raw_affiliation=str(row.get("institution") or row.get("affiliation_csrankings") or ""),
        citation_count=0,
        fwci=0.0,
        primary_topic=str(row.get("type") or ""),
        ccf_class=str(row.get("ccf_class") or ""),
        source_import_time=parse_datetime(row.get("created_at"), observed_at),
        observed_at=observed_at,
        pipeline_run_id=pipeline_run_id,
    )
