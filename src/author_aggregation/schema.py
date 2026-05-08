from datetime import datetime
from typing import Dict, List


AUTHORS_DB = "authors_db"


def create_database_sql() -> str:
    return f"CREATE DATABASE IF NOT EXISTS {AUTHORS_DB}"


def create_author_observations_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {AUTHORS_DB}.author_observations
(
    observation_id UInt64 COMMENT 'Stable hash ID for this normalized source author appearance',
    source LowCardinality(String) COMMENT 'Source table: openalex, semantic, arxiv, or dblp',
    source_row_key String COMMENT 'Stable source-level row key for idempotent imports',
    source_paper_id String COMMENT 'Paper identifier in the source table',
    source_author_id String COMMENT 'Author ID from the source table; only reliable inside that source',
    author_name String COMMENT 'Author display name from the source',
    normalized_author_name String COMMENT 'Normalized author name used for conservative matching',
    author_rank UInt16 COMMENT 'Author rank on the paper',
    author_role LowCardinality(String) COMMENT 'Author role: first, last, other, or unknown',
    doi String COMMENT 'DOI when available',
    arxiv_id String COMMENT 'arXiv ID when available',
    dblp_key String COMMENT 'DBLP paper key when available',
    semantic_id String COMMENT 'Semantic Scholar paper ID when available',
    openalex_id String COMMENT 'OpenAlex work ID when available',
    title String COMMENT 'Paper title from the source',
    normalized_title String COMMENT 'Normalized title used for paper matching',
    publication_date Nullable(Date) COMMENT 'Publication date when available',
    publication_year UInt16 COMMENT 'Publication year when available',
    venue String COMMENT 'Journal, conference, or venue name',
    institution_id String COMMENT 'Institution ID when available from the source',
    institution_name String COMMENT 'Institution name when available from the source',
    institution_country LowCardinality(String) COMMENT 'Institution country code when available',
    raw_affiliation String COMMENT 'Raw affiliation text when available',
    citation_count UInt32 COMMENT 'Citation count from the source when available',
    fwci Float32 COMMENT 'Field-weighted citation impact from OpenAlex when available',
    primary_topic String COMMENT 'Primary topic or concept from the source when available',
    ccf_class LowCardinality(String) COMMENT 'CCF class from DBLP mapping when available',
    source_import_time DateTime COMMENT 'Ingestion timestamp in the source table',
    observed_at DateTime COMMENT 'Timestamp when this observation row was created',
    pipeline_run_id String COMMENT 'Author aggregation pipeline run ID'
)
ENGINE = ReplacingMergeTree(observed_at)
ORDER BY (source, source_paper_id, author_rank, normalized_author_name)
SETTINGS index_granularity = 8192
""".strip()


def create_paper_identity_edges_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {AUTHORS_DB}.paper_identity_edges
(
    edge_id UInt64 COMMENT 'Stable hash ID for the paper identity edge',
    left_source LowCardinality(String) COMMENT 'Left source name',
    left_source_paper_id String COMMENT 'Left source paper ID',
    right_source LowCardinality(String) COMMENT 'Right source name',
    right_source_paper_id String COMMENT 'Right source paper ID',
    match_type LowCardinality(String) COMMENT 'Match rule: doi_exact, arxiv_id_exact, or title_year_exact',
    confidence Float32 COMMENT 'Conservative confidence score for this edge',
    evidence String COMMENT 'Compact JSON evidence used to create this match',
    created_at DateTime COMMENT 'Edge creation timestamp',
    pipeline_run_id String COMMENT 'Author aggregation pipeline run ID'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (left_source, left_source_paper_id, right_source, right_source_paper_id, match_type)
SETTINGS index_granularity = 8192
""".strip()


def create_author_identity_edges_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {AUTHORS_DB}.author_identity_edges
(
    edge_id UInt64 COMMENT 'Stable hash ID for this author identity edge',
    left_observation_id UInt64 COMMENT 'Left author observation ID',
    right_observation_id UInt64 COMMENT 'Right author observation ID',
    left_source LowCardinality(String) COMMENT 'Left source name',
    right_source LowCardinality(String) COMMENT 'Right source name',
    match_type LowCardinality(String) COMMENT 'Match rule, initially paper_edge_rank_name_exact',
    paper_edge_id UInt64 COMMENT 'Paper identity edge supporting this author match',
    confidence Float32 COMMENT 'High-confidence score; first version uses 1.0',
    evidence String COMMENT 'Compact JSON evidence, including rank and normalized name',
    created_at DateTime COMMENT 'Edge creation timestamp',
    pipeline_run_id String COMMENT 'Author aggregation pipeline run ID'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (left_observation_id, right_observation_id, match_type)
SETTINGS index_granularity = 8192
""".strip()


def create_author_entities_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {AUTHORS_DB}.author_entities
(
    author_entity_id UInt64 COMMENT 'Stable author entity ID generated from connected observations',
    canonical_name String COMMENT 'Display name selected for the entity',
    normalized_canonical_name String COMMENT 'Normalized canonical name',
    source_count UInt8 COMMENT 'Number of distinct sources represented by this entity',
    observation_count UInt32 COMMENT 'Number of author observation rows in this entity',
    paper_count UInt32 COMMENT 'Number of distinct paper records represented by this entity',
    source_author_ids Array(String) COMMENT 'Source-prefixed author IDs such as openalex:A123 or dblp:pid',
    sources Array(String) COMMENT 'Sources represented by this entity',
    first_publication_year UInt16 COMMENT 'Earliest publication year among observations',
    last_publication_year UInt16 COMMENT 'Latest publication year among observations',
    primary_institution_name String COMMENT 'Most common non-empty institution name among observations',
    primary_country LowCardinality(String) COMMENT 'Most common non-empty institution country among observations',
    created_at DateTime COMMENT 'Entity creation timestamp',
    updated_at DateTime COMMENT 'Entity update timestamp',
    pipeline_run_id String COMMENT 'Author aggregation pipeline run ID'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY author_entity_id
SETTINGS index_granularity = 8192
""".strip()


def create_author_ingest_state_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {AUTHORS_DB}.author_ingest_state
(
    source LowCardinality(String) COMMENT 'Source name',
    source_table String COMMENT 'Fully qualified source table name',
    watermark_field String COMMENT 'Source watermark field used for incremental extraction',
    last_watermark DateTime COMMENT 'Last successfully processed watermark',
    last_run_id String COMMENT 'Most recent pipeline run ID',
    last_status LowCardinality(String) COMMENT 'success, failed, or running',
    last_error String COMMENT 'Last error message if the run failed',
    updated_at DateTime COMMENT 'State update timestamp'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY source
SETTINGS index_granularity = 8192
""".strip()


def create_schema_field_dictionary_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {AUTHORS_DB}.schema_field_dictionary
(
    table_name String COMMENT 'authors_db table name',
    column_name String COMMENT 'Column name',
    data_type String COMMENT 'ClickHouse data type',
    description String COMMENT 'Human-readable field description',
    source_mapping String COMMENT 'Mapping from source fields when applicable',
    used_for_matching Bool COMMENT 'Whether this field participates in matching or identity generation',
    nullable_policy String COMMENT 'How empty or unavailable values are represented',
    example_value String COMMENT 'Example value',
    updated_at DateTime COMMENT 'Dictionary row update timestamp'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (table_name, column_name)
SETTINGS index_granularity = 8192
""".strip()


def all_schema_sql() -> List[str]:
    return [
        create_database_sql(),
        create_author_observations_sql(),
        create_paper_identity_edges_sql(),
        create_author_identity_edges_sql(),
        create_author_entities_sql(),
        create_author_ingest_state_sql(),
        create_schema_field_dictionary_sql(),
    ]


def field_dictionary_rows() -> List[Dict[str, object]]:
    now = datetime.now()
    return [
        {
            "table_name": "author_observations",
            "column_name": "source",
            "data_type": "LowCardinality(String)",
            "description": "Data source: openalex, semantic, arxiv, or dblp",
            "source_mapping": "constant per source mapper",
            "used_for_matching": True,
            "nullable_policy": "required",
            "example_value": "openalex",
            "updated_at": now,
        },
        {
            "table_name": "author_observations",
            "column_name": "normalized_author_name",
            "data_type": "String",
            "description": "Normalized author name used for conservative cross-source author matching",
            "source_mapping": "derived from source author display name",
            "used_for_matching": True,
            "nullable_policy": "empty string when source author name is missing",
            "example_value": "ada lovelace",
            "updated_at": now,
        },
        {
            "table_name": "author_identity_edges",
            "column_name": "paper_edge_id",
            "data_type": "UInt64",
            "description": "Paper identity edge that supports this author identity edge",
            "source_mapping": "derived from authors_db.paper_identity_edges.edge_id",
            "used_for_matching": True,
            "nullable_policy": "required",
            "example_value": "123456",
            "updated_at": now,
        },
    ]
