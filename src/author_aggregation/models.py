from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class AuthorObservation:
    observation_id: int
    source: str
    source_row_key: str
    source_paper_id: str
    source_author_id: str
    author_name: str
    normalized_author_name: str
    author_rank: int
    author_role: str
    doi: str
    arxiv_id: str
    dblp_key: str
    semantic_id: str
    openalex_id: str
    title: str
    normalized_title: str
    publication_date: Optional[date]
    publication_year: int
    venue: str
    institution_id: str
    institution_name: str
    institution_country: str
    raw_affiliation: str
    citation_count: int
    fwci: float
    primary_topic: str
    ccf_class: str
    source_import_time: datetime
    observed_at: datetime
    pipeline_run_id: str


@dataclass(frozen=True)
class PaperIdentityEdge:
    edge_id: int
    left_source: str
    left_source_paper_id: str
    right_source: str
    right_source_paper_id: str
    match_type: str
    confidence: float
    evidence: str
    created_at: datetime
    pipeline_run_id: str


@dataclass(frozen=True)
class AuthorIdentityEdge:
    edge_id: int
    left_observation_id: int
    right_observation_id: int
    left_source: str
    right_source: str
    match_type: str
    paper_edge_id: int
    confidence: float
    evidence: str
    created_at: datetime
    pipeline_run_id: str


@dataclass(frozen=True)
class AuthorEntity:
    author_entity_id: int
    canonical_name: str
    normalized_canonical_name: str
    source_count: int
    observation_count: int
    paper_count: int
    source_author_ids: List[str]
    sources: List[str]
    first_publication_year: int
    last_publication_year: int
    primary_institution_name: str
    primary_country: str
    created_at: datetime
    updated_at: datetime
    pipeline_run_id: str


@dataclass
class IngestState:
    source: str
    source_table: str
    watermark_field: str
    last_watermark: datetime
    last_run_id: str
    last_status: str
    last_error: str
    updated_at: datetime


@dataclass
class RunMetrics:
    pipeline_run_id: str
    observations_by_source: Dict[str, int] = field(default_factory=dict)
    duplicate_source_row_keys: int = 0
    empty_author_name_ratio: float = 0.0
    empty_title_ratio: float = 0.0
    paper_edges_created: int = 0
    author_edges_created: int = 0
    entities_created: int = 0
