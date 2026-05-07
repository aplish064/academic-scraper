# Author Aggregation Design

Date: 2026-05-07

## Goal

Create a conservative author aggregation layer for the four paper sources in
`academic_db`: `OpenAlex`, `semantic`, `arxiv`, and `dblp`.

The first version must support reliable downstream data mining without
polluting the data with aggressive author merges. It should provide a stable
base for later collaboration network analysis and author career enumeration.

## Scope

This design adds a new ClickHouse database, `authors_db`.

`academic_db` remains the source-data database. The existing fetchers and source
tables are not changed by this feature.

First-version scope:

- Normalize author appearances from all four source tables.
- Preserve the source of every author appearance.
- Match papers across sources using conservative evidence.
- Match authors across sources only when paper match, author rank, and
  normalized author name all agree.
- Generate stable author entities from high-confidence author identity edges.
- Support scheduled incremental updates.
- Store field documentation in a design doc, DDL comments, and a machine-readable
  field dictionary table.

Out of scope for the first version:

- Collaboration network edge table.
- Author career or institution-history table.
- Fuzzy name matching.
- Embedding-based or LLM-based matching.
- Manual review UI.
- Low-confidence candidate merging.

## Source Tables

Current source tables:

- `academic_db.OpenAlex`
- `academic_db.semantic`
- `academic_db.arxiv`
- `academic_db.dblp`

The source tables are all author-row tables, but their author identifiers have
different meanings and coverage.

`OpenAlex` has `author_id`, institution fields, citations, FWCI, and topics.

`semantic` has `author_id`, `arxiv_id`, `pubmed_id`, URL, and abstract. Its
institution fields are mostly empty.

`arxiv` has no stable author ID. It primarily has `arxiv_id`, author name, rank,
and optional affiliation.

`dblp` has `author_pid`, ORCID-related fields, venue metadata, CCF class, and
some institution fields.

## Database Boundary

Use a separate database:

```sql
CREATE DATABASE IF NOT EXISTS authors_db;
```

Reasoning:

- `academic_db` contains source and semi-source paper data.
- `authors_db` contains a derived author data product.
- The author layer can be rebuilt, dropped, permissioned, and evolved without
  touching source ingestion.
- Later graph tables can be added to `authors_db` without mixing them into the
  source database.

## Tables

### `authors_db.author_observations`

One row represents one author appearing on one paper in one source.

This is the base fact table. It does not perform cross-source author merging.

Suggested columns:

```sql
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
```

Recommended engine:

```sql
ENGINE = ReplacingMergeTree(observed_at)
ORDER BY (source, source_paper_id, author_rank, normalized_author_name)
```

Recommended idempotency key:

```text
source + source_paper_id + author_rank + normalized_author_name
```

The implementation should also keep `source_row_key` stable:

```text
openalex: openalex:{uid}:{rank}:{author_id_or_name_hash}
semantic: semantic:{uid}:{rank}:{author_id_or_name_hash}
arxiv:    arxiv:{arxiv_id}:{rank}:{author_name_hash}
dblp:     dblp:{dblp_key}:{author_rank}:{author_pid_or_name_hash}
```

### `authors_db.paper_identity_edges`

Stores cross-source paper matching evidence.

This table does not merge authors. It says that two source paper records likely
represent the same paper.

Suggested columns:

```sql
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
```

Recommended engine:

```sql
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (left_source, left_source_paper_id, right_source, right_source_paper_id, match_type)
```

First-version paper match priority:

```text
doi_exact > arxiv_id_exact > normalized_title + publication_year exact
```

`title_year_exact` is allowed only when `normalized_title` length is at least 30
characters.

### `authors_db.author_identity_edges`

Stores conservative cross-source author identity evidence.

First-version author identity edges are created only when all conditions are
true:

- There is a paper identity edge between the two source papers.
- `left.author_rank = right.author_rank`.
- `left.normalized_author_name = right.normalized_author_name`.
- `left.source != right.source`.

Suggested columns:

```sql
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
```

Recommended engine:

```sql
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (left_observation_id, right_observation_id, match_type)
```

### `authors_db.author_entities`

Stores conservative author entities generated from high-confidence identity
edges.

This table is not the absolute truth about real-world authors. It is the current
conservative identity graph result.

Suggested columns:

```sql
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
```

Recommended engine:

```sql
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY author_entity_id
```

Entity generation rule:

- Every observation gets an entity.
- Observations connected by high-confidence `author_identity_edges` share one
  entity.
- Observations without high-confidence edges remain single-observation entities.

The first implementation should generate entities with Python union-find. It is
acceptable for `author_entities` to be rebuilt in batch while observations and
edges are updated incrementally.

### `authors_db.author_ingest_state`

Stores pipeline watermarks and status.

Suggested columns:

```sql
source LowCardinality(String) COMMENT 'Source name',
source_table String COMMENT 'Fully qualified source table name',
watermark_field String COMMENT 'Source watermark field used for incremental extraction',
last_watermark DateTime COMMENT 'Last successfully processed watermark',
last_run_id String COMMENT 'Most recent pipeline run ID',
last_status LowCardinality(String) COMMENT 'success, failed, or running',
last_error String COMMENT 'Last error message if the run failed',
updated_at DateTime COMMENT 'State update timestamp'
```

Recommended engine:

```sql
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY source
```

### `authors_db.schema_field_dictionary`

Stores machine-readable field documentation.

Suggested columns:

```sql
table_name String COMMENT 'authors_db table name',
column_name String COMMENT 'Column name',
data_type String COMMENT 'ClickHouse data type',
description String COMMENT 'Human-readable field description',
source_mapping String COMMENT 'Mapping from source fields when applicable',
used_for_matching Bool COMMENT 'Whether this field participates in matching or identity generation',
nullable_policy String COMMENT 'How empty or unavailable values are represented',
example_value String COMMENT 'Example value',
updated_at DateTime COMMENT 'Dictionary row update timestamp'
```

Recommended engine:

```sql
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (table_name, column_name)
```

## Incremental Update Flow

Use a scheduled job, for example `src/author_aggregation_job.py`.

Recommended first-version cadence: every 15 minutes.

Each run gets a `pipeline_run_id` and performs these stages:

1. Read watermarks from `authors_db.author_ingest_state`.
2. Extract new rows from the four source tables.
3. Normalize and insert rows into `authors_db.author_observations`.
4. Generate new `paper_identity_edges`.
5. Generate new `author_identity_edges`.
6. Refresh `author_entities`.
7. Update watermarks only after successful completion.

Watermark fields:

```text
OpenAlex: academic_db.OpenAlex.import_time
semantic: academic_db.semantic.import_time
arxiv:    academic_db.arxiv.import_date converted to DateTime
dblp:     academic_db.dblp.created_at
```

Because arXiv has date-level ingestion time, the job should apply a small
overlap, such as rescanning the last two days, and rely on idempotent keys.

If a run fails:

- Mark the relevant source status as `failed`.
- Save `last_error`.
- Do not advance the corresponding watermark.
- Let the next run retry from the previous successful watermark.

## Normalization Rules

`normalized_author_name`:

- Lowercase.
- Trim and collapse whitespace.
- Remove common punctuation noise such as periods and commas.
- Preserve Unicode letters.
- Do not do pinyin conversion.
- Do not do broad author-name inversion in the first version.

`normalized_title`:

- Lowercase.
- Remove simple HTML and LaTeX markup where practical.
- Remove punctuation.
- Trim and collapse whitespace.

The first version must not use fuzzy title matching or embedding matching.

## Matching Rules

Paper identity:

1. `doi_exact`: non-empty DOI is equal across sources. Confidence: `1.0`.
2. `arxiv_id_exact`: non-empty arXiv ID is equal across sources. Confidence:
   `1.0`.
3. `title_year_exact`: normalized title and publication year are equal.
   Confidence: `0.95`. Only allowed when normalized title length is at least 30.

Author identity:

Create an edge only when:

```text
paper_identity_edge exists
left.author_rank = right.author_rank
left.normalized_author_name = right.normalized_author_name
left.source != right.source
```

The first version must not create author identity edges using name-only matches.

## Data Quality Checks

Each run should log these metrics:

- New observation rows per source.
- Duplicate `source_row_key` count.
- Empty `author_name` ratio.
- Empty `title` ratio.
- Empty external identifier ratio by source.
- New `paper_identity_edges` count.
- New `author_identity_edges` count.
- `author_entities` count change.
- Runtime.
- Whether watermarks advanced.

First-version warning thresholds:

- Empty `author_name` ratio above 5%.
- Empty `title` ratio above 5%.
- Source watermark changed but new observations are zero.
- New paper identity edges are zero for a non-empty run.

Warnings should not block the first version. They should be logged for review.

## Field Documentation Strategy

Field descriptions are stored in three places:

1. This design document is the primary human-readable reference.
2. ClickHouse DDL uses column `COMMENT` for important fields.
3. `authors_db.schema_field_dictionary` stores machine-readable field metadata
   for scripts and future dashboards.

## Acceptance Criteria

The first implementation is complete when:

1. `authors_db` and the six tables can be created idempotently.
2. All four source tables can be normalized into `author_observations`.
3. Every observation row preserves `source`.
4. Re-running the same time window does not create duplicate observations.
5. DOI, arXiv ID, and title-year paper identity edges can be generated.
6. Author identity edges are generated only for matched paper, exact rank, and
   exact normalized author name.
7. Unmatched observations still receive one-author entities.
8. `author_ingest_state` records watermark, status, run ID, and errors.
9. Field descriptions are present in this design, DDL comments, and
   `schema_field_dictionary`.
10. Tests cover at least:
    - OpenAlex and Semantic same DOI, same rank, same normalized name merge.
    - Same name but different paper does not merge.
    - Same paper but different rank does not merge.
    - arXiv rows without author IDs still enter observations.
    - Re-running an import window is idempotent.
11. A real ClickHouse dry run or small-window run reports row counts and quality
    metrics.

## Implementation Notes

Prefer a Python job over ClickHouse materialized views for the first version.

Reasoning:

- The four sources have different ingestion timestamp semantics.
- arXiv only has date-level import time.
- Entity generation requires graph connected components, which ClickHouse is not
  ideal for maintaining incrementally.
- A Python job can maintain explicit watermarks, retries, run IDs, and audit
  logging.

`author_observations`, `paper_identity_edges`, and `author_identity_edges` should
be incrementally written. `author_entities` may be rebuilt by batch in the first
version if incremental graph maintenance becomes too complex.
