# Author Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a conservative `authors_db` author aggregation layer from `academic_db.OpenAlex`, `academic_db.semantic`, `academic_db.arxiv`, and `academic_db.dblp`.

**Architecture:** Add a focused `src/author_aggregation/` package with schema DDL, source row normalization, ClickHouse repository helpers, conservative paper/author matching, union-find entity generation, and a CLI job runner. The pipeline writes normalized observations and identity edges incrementally, then refreshes author entities from high-confidence author identity edges.

**Tech Stack:** Python 3, stdlib `unittest`, `clickhouse_connect`, ClickHouse `ReplacingMergeTree`, existing project layout under `/home/hkustgz/Us/academic-scraper`.

---

## Constraints

- Use the existing repository root: `/home/hkustgz/Us/academic-scraper`.
- Keep source tables in `academic_db` unchanged.
- Create derived tables only in `authors_db`.
- Use conservative matching only:
  - paper: DOI exact, arXiv ID exact, or normalized title + year exact with title length guard;
  - author: matched paper + exact rank + exact normalized author name.
- Do not add collaboration network or career-history tables in this implementation.
- Keep the current dirty worktree safe. Only stage files created or modified by this plan.
- Use `python3 -m unittest ...` for tests unless the executor verifies that the project venv must be used.
- Do not run a full historical aggregation during implementation. Use unit tests and a small-window or dry-run ClickHouse smoke test.

## File Structure

- Create: `src/author_aggregation/__init__.py`
  - Package marker and version string.
- Create: `src/author_aggregation/models.py`
  - Dataclasses for normalized observations, paper identity edges, author identity edges, author entities, source watermarks, and run metrics.
- Create: `src/author_aggregation/normalization.py`
  - Text normalization and stable hash helpers.
- Create: `src/author_aggregation/source_mappers.py`
  - Source-specific row-to-observation mapping for OpenAlex, Semantic Scholar, arXiv, and DBLP.
- Create: `src/author_aggregation/schema.py`
  - `authors_db` DDL, table creation SQL, and field dictionary rows.
- Create: `src/author_aggregation/repository.py`
  - ClickHouse client wrapper, idempotent insert helpers, state reads/writes, and source extraction SQL builders.
- Create: `src/author_aggregation/matching.py`
  - Conservative paper identity and author identity edge generation.
- Create: `src/author_aggregation/entities.py`
  - Union-find connected-component author entity generation.
- Create: `src/author_aggregation/job.py`
  - Pipeline orchestration and CLI entrypoint.
- Create: `tests/test_author_aggregation_schema.py`
  - Schema and field dictionary tests.
- Create: `tests/test_author_aggregation_normalization.py`
  - Normalization and stable ID tests.
- Create: `tests/test_author_aggregation_source_mappers.py`
  - Source mapping tests for all four source tables.
- Create: `tests/test_author_aggregation_repository.py`
  - SQL builder, idempotency, and watermark tests.
- Create: `tests/test_author_aggregation_matching.py`
  - Paper and author edge matching tests.
- Create: `tests/test_author_aggregation_entities.py`
  - Union-find entity tests.
- Create: `tests/test_author_aggregation_job.py`
  - Pipeline orchestration tests with fake repository.

## Task 1: Models, Normalization, and Stable IDs

**Files:**
- Create: `src/author_aggregation/__init__.py`
- Create: `src/author_aggregation/models.py`
- Create: `src/author_aggregation/normalization.py`
- Test: `tests/test_author_aggregation_normalization.py`

- [ ] **Step 1: Write failing normalization tests**

Create `tests/test_author_aggregation_normalization.py`:

```python
import unittest

from src.author_aggregation import normalization


class AuthorAggregationNormalizationTests(unittest.TestCase):
    def test_normalize_author_name_lowercases_and_removes_punctuation_noise(self):
        self.assertEqual(normalization.normalize_author_name("  Ada B. Lovelace,  "), "ada b lovelace")

    def test_normalize_author_name_preserves_unicode_letters(self):
        self.assertEqual(normalization.normalize_author_name(" 王 小明 "), "王 小明")

    def test_normalize_title_removes_markup_punctuation_and_collapses_space(self):
        raw = "A <b>Fast</b> Study of $E=mc^2$: Results!"
        self.assertEqual(normalization.normalize_title(raw), "a fast study of emc2 results")

    def test_normalize_doi_removes_url_prefix_and_lowercases(self):
        self.assertEqual(normalization.normalize_doi("https://doi.org/10.1145/ABC.DEF"), "10.1145/abc.def")

    def test_stable_u64_is_deterministic(self):
        first = normalization.stable_u64("openalex", "W1", "1", "alice")
        second = normalization.stable_u64("openalex", "W1", "1", "alice")
        self.assertEqual(first, second)
        self.assertIsInstance(first, int)
        self.assertGreaterEqual(first, 0)

    def test_source_row_key_prefers_author_id_when_present(self):
        key = normalization.build_source_row_key(
            source="openalex",
            source_paper_id="W1",
            author_rank=1,
            source_author_id="A1",
            normalized_author_name="alice"
        )
        self.assertEqual(key, "openalex:W1:1:A1")

    def test_source_row_key_hashes_name_when_author_id_missing(self):
        key = normalization.build_source_row_key(
            source="arxiv",
            source_paper_id="2401.00001",
            author_rank=2,
            source_author_id="",
            normalized_author_name="alice smith"
        )
        self.assertTrue(key.startswith("arxiv:2401.00001:2:name_"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_normalization -v
```

Expected: import error because `src.author_aggregation` does not exist.

- [ ] **Step 3: Create package marker**

Create `src/author_aggregation/__init__.py`:

```python
"""Author aggregation pipeline package."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Create dataclasses**

Create `src/author_aggregation/models.py`:

```python
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
```

- [ ] **Step 5: Implement normalization helpers**

Create `src/author_aggregation/normalization.py`:

```python
import hashlib
import html
import re
from typing import Optional


DOI_PREFIX_RE = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
PUNCT_TRANSLATION = str.maketrans({
    ".": " ",
    ",": " ",
    ";": " ",
    ":": " ",
    "-": " ",
    "_": " ",
    "(": " ",
    ")": " ",
    "[": " ",
    "]": " ",
    "{": " ",
    "}": " ",
    "/": " ",
    "\\": " ",
    "\"": " ",
    "'": " ",
    "`": " ",
    "$": " ",
    "^": " ",
    "*": " ",
    "!": " ",
    "?": " ",
})


def collapse_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_author_name(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html.unescape(str(value)).lower()
    text = text.translate(PUNCT_TRANSLATION)
    return collapse_space(text)


def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html.unescape(str(value)).lower()
    text = HTML_TAG_RE.sub(" ", text)
    text = text.replace("\\", " ")
    text = text.translate(PUNCT_TRANSLATION)
    return collapse_space(text)


def normalize_doi(value: Optional[str]) -> str:
    if not value:
        return ""
    text = DOI_PREFIX_RE.sub("", str(value).strip()).lower()
    return text.rstrip("/")


def stable_u64(*parts: object) -> int:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.blake2b(value.encode("utf-8"), digest_size=16).hexdigest()[:length]


def build_source_row_key(
    source: str,
    source_paper_id: str,
    author_rank: int,
    source_author_id: str,
    normalized_author_name: str,
) -> str:
    author_component = source_author_id.strip() if source_author_id else f"name_{short_hash(normalized_author_name)}"
    return f"{source}:{source_paper_id}:{author_rank}:{author_component}"
```

- [ ] **Step 6: Run normalization tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_normalization -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add src/author_aggregation/__init__.py src/author_aggregation/models.py src/author_aggregation/normalization.py tests/test_author_aggregation_normalization.py
git commit -m "添加作者聚合规范化基础"
```

## Task 2: Schema DDL and Field Dictionary

**Files:**
- Create: `src/author_aggregation/schema.py`
- Test: `tests/test_author_aggregation_schema.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_author_aggregation_schema.py`:

```python
import unittest

from src.author_aggregation import schema


class AuthorAggregationSchemaTests(unittest.TestCase):
    def test_create_database_sql_targets_authors_db(self):
        self.assertEqual(schema.create_database_sql(), "CREATE DATABASE IF NOT EXISTS authors_db")

    def test_author_observations_ddl_has_source_and_comments(self):
        ddl = schema.create_author_observations_sql()
        self.assertIn("CREATE TABLE IF NOT EXISTS authors_db.author_observations", ddl)
        self.assertIn("source LowCardinality(String) COMMENT", ddl)
        self.assertIn("normalized_author_name String COMMENT", ddl)
        self.assertIn("ReplacingMergeTree(observed_at)", ddl)

    def test_all_required_table_ddls_are_returned(self):
        ddls = schema.all_schema_sql()
        expected_names = [
            "authors_db.author_observations",
            "authors_db.paper_identity_edges",
            "authors_db.author_identity_edges",
            "authors_db.author_entities",
            "authors_db.author_ingest_state",
            "authors_db.schema_field_dictionary",
        ]
        joined = "\n".join(ddls)
        for name in expected_names:
            self.assertIn(name, joined)

    def test_field_dictionary_contains_source_field(self):
        rows = schema.field_dictionary_rows()
        source_rows = [
            row for row in rows
            if row["table_name"] == "author_observations" and row["column_name"] == "source"
        ]
        self.assertEqual(len(source_rows), 1)
        self.assertTrue(source_rows[0]["used_for_matching"])
        self.assertIn("openalex", source_rows[0]["description"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing schema tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_schema -v
```

Expected: import error or missing `schema` functions.

- [ ] **Step 3: Implement schema DDL helpers**

Create `src/author_aggregation/schema.py` with the DDL functions. Include all six table DDL strings and a compact field dictionary seed:

```python
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
"""
```

Add the remaining DDL functions in the same file with the column definitions from `docs/superpowers/specs/2026-05-07-author-aggregation-design.md`:

```python
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
"""
```

```python
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
"""
```

```python
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
"""
```

```python
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
"""
```

```python
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
"""
```

Add aggregate helpers:

```python
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
```

- [ ] **Step 4: Run schema tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_schema -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/author_aggregation/schema.py tests/test_author_aggregation_schema.py
git commit -m "添加作者聚合表结构定义"
```

## Task 3: Source Row Mappers

**Files:**
- Create: `src/author_aggregation/source_mappers.py`
- Test: `tests/test_author_aggregation_source_mappers.py`

- [ ] **Step 1: Write failing source mapper tests**

Create `tests/test_author_aggregation_source_mappers.py`:

```python
import unittest
from datetime import date, datetime

from src.author_aggregation import source_mappers


RUN_ID = "run-test"
NOW = datetime(2026, 5, 7, 11, 0, 0)


class SourceMapperTests(unittest.TestCase):
    def test_map_openalex_row_preserves_source_and_ids(self):
        row = {
            "author_id": "A1",
            "author": "Ada Lovelace",
            "uid": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1000/XYZ",
            "title": "A Conservative Matching Paper",
            "rank": 1,
            "journal": "Journal",
            "publication_date": "2026-04-10",
            "citation_count": 12,
            "tag": "第一作者",
            "institution_id": "I1",
            "institution_name": "Example University",
            "institution_country": "US",
            "raw_affiliation": "Example University",
            "fwci": 1.5,
            "primary_topic": "Data Mining",
            "import_time": NOW,
        }

        obs = source_mappers.map_openalex_row(row, RUN_ID, NOW)

        self.assertEqual(obs.source, "openalex")
        self.assertEqual(obs.source_author_id, "A1")
        self.assertEqual(obs.source_paper_id, "https://openalex.org/W1")
        self.assertEqual(obs.doi, "10.1000/xyz")
        self.assertEqual(obs.openalex_id, "https://openalex.org/W1")
        self.assertEqual(obs.author_role, "first")
        self.assertEqual(obs.publication_date, date(2026, 4, 10))

    def test_map_semantic_row_preserves_arxiv_id_and_semantic_id(self):
        row = {
            "author_id": "S-A1",
            "author": "Ada Lovelace",
            "uid": "S-P1",
            "doi": "10.1000/xyz",
            "title": "A Conservative Matching Paper",
            "rank": 1,
            "journal": "Journal",
            "publication_date": "2026-04-10",
            "year": 2026,
            "venue": "Journal",
            "arxiv_id": "2401.00001",
            "citation_count": 3,
            "import_time": NOW,
        }

        obs = source_mappers.map_semantic_row(row, RUN_ID, NOW)

        self.assertEqual(obs.source, "semantic")
        self.assertEqual(obs.semantic_id, "S-P1")
        self.assertEqual(obs.arxiv_id, "2401.00001")
        self.assertEqual(obs.publication_year, 2026)

    def test_map_arxiv_row_handles_missing_author_id(self):
        row = {
            "arxiv_id": "2401.00001",
            "uid": "http://arxiv.org/abs/2401.00001v1",
            "title": "A Conservative Matching Paper",
            "published": date(2026, 4, 10),
            "author": "Ada Lovelace",
            "rank": 1,
            "tag": "第一作者",
            "affiliation": "Example University",
            "import_date": date(2026, 5, 7),
        }

        obs = source_mappers.map_arxiv_row(row, RUN_ID, NOW)

        self.assertEqual(obs.source, "arxiv")
        self.assertEqual(obs.source_author_id, "")
        self.assertEqual(obs.arxiv_id, "2401.00001")
        self.assertEqual(obs.publication_year, 2026)
        self.assertIn("arxiv:2401.00001:1:name_", obs.source_row_key)

    def test_map_dblp_row_preserves_pid_orcid_and_ccf_class(self):
        row = {
            "dblp_key": "conf/test/1",
            "title": "A Conservative Matching Paper",
            "year": "2026",
            "publication_date": "2026-04",
            "venue": "TestConf",
            "ccf_class": "A",
            "author_pid": "pid/1",
            "author_name": "Ada Lovelace",
            "author_rank": 1,
            "author_role": "第一作者",
            "doi": "10.1000/xyz",
            "institution": "Example University",
            "created_at": NOW,
        }

        obs = source_mappers.map_dblp_row(row, RUN_ID, NOW)

        self.assertEqual(obs.source, "dblp")
        self.assertEqual(obs.source_author_id, "pid/1")
        self.assertEqual(obs.dblp_key, "conf/test/1")
        self.assertEqual(obs.ccf_class, "A")
        self.assertEqual(obs.author_role, "first")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing mapper tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_source_mappers -v
```

Expected: import error or missing `source_mappers`.

- [ ] **Step 3: Implement source mappers**

Create `src/author_aggregation/source_mappers.py` with helper functions:

```python
from datetime import date, datetime
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
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
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
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if value:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue
    return fallback


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
```

Add one mapper per source using `build_observation()`:

```python
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
        publication_year=parse_year(None, pub_date),
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
```

Add the Semantic Scholar mapper:

```python
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
```

Add the arXiv mapper:

```python
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
        publication_year=parse_year(None, pub_date),
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
```

Add the DBLP mapper:

```python
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
```

- [ ] **Step 4: Run mapper tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_source_mappers -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/author_aggregation/source_mappers.py tests/test_author_aggregation_source_mappers.py
git commit -m "添加四源作者观察映射"
```

## Task 4: ClickHouse Repository and Watermarks

**Files:**
- Create: `src/author_aggregation/repository.py`
- Test: `tests/test_author_aggregation_repository.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/test_author_aggregation_repository.py`:

```python
import unittest
from datetime import datetime

from src.author_aggregation import repository


class RepositorySqlTests(unittest.TestCase):
    def test_source_query_for_arxiv_uses_overlap_days(self):
        start = datetime(2026, 5, 7, 12, 0, 0)
        sql = repository.build_source_extract_sql("arxiv", start, limit=100, overlap_days=2)
        self.assertIn("FROM academic_db.arxiv", sql)
        self.assertIn("toDateTime(import_date)", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertIn("2026-05-05", sql)

    def test_source_query_for_openalex_uses_import_time(self):
        start = datetime(2026, 5, 7, 12, 0, 0)
        sql = repository.build_source_extract_sql("openalex", start, limit=100, overlap_days=2)
        self.assertIn("FROM academic_db.OpenAlex", sql)
        self.assertIn("import_time >=", sql)
        self.assertIn("LIMIT 100", sql)

    def test_observation_insert_sql_anti_joins_source_row_key(self):
        sql = repository.build_observation_insert_sql("temp_author_observations")
        self.assertIn("LEFT ANTI JOIN authors_db.author_observations", sql)
        self.assertIn("tmp.source_row_key = tgt.source_row_key", sql)


class FakeClickHouseClient:
    def __init__(self):
        self.commands = []
        self.inserted = []

    def command(self, sql):
        self.commands.append(sql)

    def insert(self, table, rows, column_names=None):
        self.inserted.append((table, rows, column_names))


class RepositoryCommandTests(unittest.TestCase):
    def test_create_schema_executes_all_ddls(self):
        fake = FakeClickHouseClient()
        repo = repository.AuthorAggregationRepository(fake)
        repo.create_schema()
        self.assertGreaterEqual(len(fake.commands), 7)
        self.assertIn("CREATE DATABASE IF NOT EXISTS authors_db", fake.commands[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing repository tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_repository -v
```

Expected: import error or missing repository functions.

- [ ] **Step 3: Implement SQL builders and repository wrapper**

Create `src/author_aggregation/repository.py`:

```python
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

import clickhouse_connect

from . import schema
from .models import AuthorIdentityEdge, AuthorObservation, PaperIdentityEdge


SOURCE_CONFIG = {
    "openalex": ("academic_db.OpenAlex", "import_time"),
    "semantic": ("academic_db.semantic", "import_time"),
    "arxiv": ("academic_db.arxiv", "toDateTime(import_date)"),
    "dblp": ("academic_db.dblp", "created_at"),
}


OBSERVATION_COLUMNS = [
    "observation_id", "source", "source_row_key", "source_paper_id", "source_author_id",
    "author_name", "normalized_author_name", "author_rank", "author_role",
    "doi", "arxiv_id", "dblp_key", "semantic_id", "openalex_id",
    "title", "normalized_title", "publication_date", "publication_year", "venue",
    "institution_id", "institution_name", "institution_country", "raw_affiliation",
    "citation_count", "fwci", "primary_topic", "ccf_class",
    "source_import_time", "observed_at", "pipeline_run_id",
]


def create_clickhouse_client():
    return clickhouse_connect.get_client(
        host="localhost",
        port=8123,
        username="default",
        password="",
    )


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def build_source_extract_sql(source: str, last_watermark: datetime, limit: Optional[int], overlap_days: int) -> str:
    table, watermark_expr = SOURCE_CONFIG[source]
    effective_watermark = last_watermark - timedelta(days=overlap_days if source == "arxiv" else 0)
    limit_clause = f" LIMIT {int(limit)}" if limit else ""
    return (
        f"SELECT * FROM {table} "
        f"WHERE {watermark_expr} >= toDateTime('{format_datetime(effective_watermark)}') "
        f"ORDER BY {watermark_expr} ASC"
        f"{limit_clause}"
    )


def build_observation_insert_sql(temp_table: str) -> str:
    columns = ", ".join(OBSERVATION_COLUMNS)
    select_columns = ", ".join(f"tmp.{column}" for column in OBSERVATION_COLUMNS)
    return f"""
INSERT INTO authors_db.author_observations ({columns})
SELECT {select_columns}
FROM {temp_table} tmp
LEFT ANTI JOIN authors_db.author_observations tgt
ON tmp.source_row_key = tgt.source_row_key
"""


class AuthorAggregationRepository:
    def __init__(self, client):
        self.client = client

    def create_schema(self) -> None:
        for sql in schema.all_schema_sql():
            self.client.command(sql)

    def seed_field_dictionary(self) -> None:
        rows = schema.field_dictionary_rows()
        columns = [
            "table_name", "column_name", "data_type", "description", "source_mapping",
            "used_for_matching", "nullable_policy", "example_value", "updated_at",
        ]
        self.client.insert("authors_db.schema_field_dictionary", [[row[column] for column in columns] for row in rows], column_names=columns)

    def fetch_source_rows(self, source: str, last_watermark: datetime, limit: Optional[int], overlap_days: int) -> List[dict]:
        sql = build_source_extract_sql(source, last_watermark, limit=limit, overlap_days=overlap_days)
        return self.client.query(sql).result_rows

    def insert_observations(self, observations: Iterable[AuthorObservation]) -> None:
        rows = [[asdict(obs)[column] for column in OBSERVATION_COLUMNS] for obs in observations]
        if not rows:
            return
        temp_table = "authors_db.temp_author_observations"
        self.client.command(f"DROP TABLE IF EXISTS {temp_table}")
        self.client.command(f"CREATE TABLE {temp_table} AS authors_db.author_observations ENGINE = Memory")
        self.client.insert(temp_table, rows, column_names=OBSERVATION_COLUMNS)
        self.client.command(build_observation_insert_sql(temp_table))
        self.client.command(f"DROP TABLE IF EXISTS {temp_table}")
```

Add edge insert methods later in matching tasks when edge column constants are defined.

- [ ] **Step 4: Run repository tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_repository -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add src/author_aggregation/repository.py tests/test_author_aggregation_repository.py
git commit -m "添加作者聚合仓储和水位查询"
```

## Task 5: Conservative Paper and Author Matching

**Files:**
- Create: `src/author_aggregation/matching.py`
- Test: `tests/test_author_aggregation_matching.py`
- Modify: `src/author_aggregation/repository.py`

- [ ] **Step 1: Write failing matching tests**

Create `tests/test_author_aggregation_matching.py`:

```python
import unittest
from datetime import date, datetime

from src.author_aggregation.matching import build_author_identity_edges, build_paper_identity_edges
from src.author_aggregation.models import AuthorObservation


NOW = datetime(2026, 5, 7, 12, 0, 0)
RUN_ID = "run-test"


def obs(source, paper_id, observation_id, rank, name, doi="", arxiv_id="", title="A Conservative Matching Paper", year=2026):
    return AuthorObservation(
        observation_id=observation_id,
        source=source,
        source_row_key=f"{source}:{paper_id}:{rank}:{name}",
        source_paper_id=paper_id,
        source_author_id=f"{source}-author-{rank}",
        author_name=name,
        normalized_author_name=name.lower(),
        author_rank=rank,
        author_role="first" if rank == 1 else "other",
        doi=doi,
        arxiv_id=arxiv_id,
        dblp_key=paper_id if source == "dblp" else "",
        semantic_id=paper_id if source == "semantic" else "",
        openalex_id=paper_id if source == "openalex" else "",
        title=title,
        normalized_title=title.lower(),
        publication_date=date(year, 1, 1),
        publication_year=year,
        venue="Journal",
        institution_id="",
        institution_name="",
        institution_country="",
        raw_affiliation="",
        citation_count=0,
        fwci=0.0,
        primary_topic="",
        ccf_class="",
        source_import_time=NOW,
        observed_at=NOW,
        pipeline_run_id=RUN_ID,
    )


class MatchingTests(unittest.TestCase):
    def test_paper_edge_uses_doi_exact(self):
        observations = [
            obs("openalex", "W1", 1, 1, "alice", doi="10.1/test"),
            obs("semantic", "S1", 2, 1, "alice", doi="10.1/test"),
        ]
        edges = build_paper_identity_edges(observations, NOW, RUN_ID)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].match_type, "doi_exact")
        self.assertEqual(edges[0].confidence, 1.0)

    def test_paper_edge_uses_arxiv_id_exact(self):
        observations = [
            obs("arxiv", "2401.1", 1, 1, "alice", arxiv_id="2401.1", doi=""),
            obs("semantic", "S1", 2, 1, "alice", arxiv_id="2401.1", doi=""),
        ]
        edges = build_paper_identity_edges(observations, NOW, RUN_ID)
        self.assertEqual(edges[0].match_type, "arxiv_id_exact")

    def test_title_year_edge_requires_long_title(self):
        short = [
            obs("openalex", "W1", 1, 1, "alice", title="Short title", doi=""),
            obs("dblp", "D1", 2, 1, "alice", title="Short title", doi=""),
        ]
        self.assertEqual(build_paper_identity_edges(short, NOW, RUN_ID), [])

    def test_author_edge_requires_same_rank_and_name(self):
        left = obs("openalex", "W1", 1, 1, "alice", doi="10.1/test")
        right = obs("semantic", "S1", 2, 1, "alice", doi="10.1/test")
        paper_edges = build_paper_identity_edges([left, right], NOW, RUN_ID)
        author_edges = build_author_identity_edges([left, right], paper_edges, NOW, RUN_ID)
        self.assertEqual(len(author_edges), 1)
        self.assertEqual(author_edges[0].match_type, "paper_edge_rank_name_exact")

    def test_author_edge_rejects_rank_mismatch(self):
        left = obs("openalex", "W1", 1, 1, "alice", doi="10.1/test")
        right = obs("semantic", "S1", 2, 2, "alice", doi="10.1/test")
        paper_edges = build_paper_identity_edges([left, right], NOW, RUN_ID)
        author_edges = build_author_identity_edges([left, right], paper_edges, NOW, RUN_ID)
        self.assertEqual(author_edges, [])

    def test_author_edge_rejects_name_mismatch(self):
        left = obs("openalex", "W1", 1, 1, "alice", doi="10.1/test")
        right = obs("semantic", "S1", 2, 1, "bob", doi="10.1/test")
        paper_edges = build_paper_identity_edges([left, right], NOW, RUN_ID)
        author_edges = build_author_identity_edges([left, right], paper_edges, NOW, RUN_ID)
        self.assertEqual(author_edges, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing matching tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_matching -v
```

Expected: import error or missing matching functions.

- [ ] **Step 3: Implement matching functions**

Create `src/author_aggregation/matching.py`:

```python
import json
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from typing import Dict, Iterable, List, Tuple

from .models import AuthorIdentityEdge, AuthorObservation, PaperIdentityEdge
from .normalization import stable_u64


TITLE_YEAR_MIN_LENGTH = 30


def canonical_pair(left: AuthorObservation, right: AuthorObservation) -> Tuple[AuthorObservation, AuthorObservation]:
    left_key = (left.source, left.source_paper_id)
    right_key = (right.source, right.source_paper_id)
    return (left, right) if left_key <= right_key else (right, left)


def unique_papers(observations: Iterable[AuthorObservation]) -> Dict[Tuple[str, str], AuthorObservation]:
    papers = {}
    for observation in observations:
        key = (observation.source, observation.source_paper_id)
        papers.setdefault(key, observation)
    return papers


def build_paper_identity_edges(
    observations: Iterable[AuthorObservation],
    created_at: datetime,
    pipeline_run_id: str,
) -> List[PaperIdentityEdge]:
    papers = list(unique_papers(observations).values())
    grouped = defaultdict(list)

    for paper in papers:
        if paper.doi:
            grouped[("doi_exact", paper.doi)].append(paper)
        if paper.arxiv_id:
            grouped[("arxiv_id_exact", paper.arxiv_id)].append(paper)
        if not paper.doi and not paper.arxiv_id and len(paper.normalized_title) >= TITLE_YEAR_MIN_LENGTH and paper.publication_year:
            grouped[("title_year_exact", f"{paper.normalized_title}\x1f{paper.publication_year}")].append(paper)

    edges = {}
    priority = {"doi_exact": 1, "arxiv_id_exact": 2, "title_year_exact": 3}
    confidence = {"doi_exact": 1.0, "arxiv_id_exact": 1.0, "title_year_exact": 0.95}

    for (match_type, match_value), group in grouped.items():
        for raw_left, raw_right in combinations(group, 2):
            if raw_left.source == raw_right.source:
                continue
            left, right = canonical_pair(raw_left, raw_right)
            pair_key = (left.source, left.source_paper_id, right.source, right.source_paper_id)
            existing = edges.get(pair_key)
            if existing and priority[existing.match_type] <= priority[match_type]:
                continue
            evidence = json.dumps({"match_value": match_value}, ensure_ascii=False, sort_keys=True)
            edge_id = stable_u64("paper", left.source, left.source_paper_id, right.source, right.source_paper_id, match_type)
            edges[pair_key] = PaperIdentityEdge(
                edge_id=edge_id,
                left_source=left.source,
                left_source_paper_id=left.source_paper_id,
                right_source=right.source,
                right_source_paper_id=right.source_paper_id,
                match_type=match_type,
                confidence=confidence[match_type],
                evidence=evidence,
                created_at=created_at,
                pipeline_run_id=pipeline_run_id,
            )

    return list(edges.values())


def build_author_identity_edges(
    observations: Iterable[AuthorObservation],
    paper_edges: Iterable[PaperIdentityEdge],
    created_at: datetime,
    pipeline_run_id: str,
) -> List[AuthorIdentityEdge]:
    by_paper = defaultdict(list)
    for observation in observations:
        by_paper[(observation.source, observation.source_paper_id)].append(observation)

    edges = []
    seen = set()
    for paper_edge in paper_edges:
        left_authors = by_paper[(paper_edge.left_source, paper_edge.left_source_paper_id)]
        right_authors = by_paper[(paper_edge.right_source, paper_edge.right_source_paper_id)]
        for left in left_authors:
            for right in right_authors:
                if left.author_rank != right.author_rank:
                    continue
                if left.normalized_author_name == "" or left.normalized_author_name != right.normalized_author_name:
                    continue
                pair = tuple(sorted([left.observation_id, right.observation_id]))
                if pair in seen:
                    continue
                seen.add(pair)
                evidence = json.dumps(
                    {
                        "paper_edge_id": paper_edge.edge_id,
                        "author_rank": left.author_rank,
                        "normalized_author_name": left.normalized_author_name,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                edge_id = stable_u64("author", pair[0], pair[1], paper_edge.edge_id)
                edges.append(
                    AuthorIdentityEdge(
                        edge_id=edge_id,
                        left_observation_id=pair[0],
                        right_observation_id=pair[1],
                        left_source=left.source,
                        right_source=right.source,
                        match_type="paper_edge_rank_name_exact",
                        paper_edge_id=paper_edge.edge_id,
                        confidence=1.0,
                        evidence=evidence,
                        created_at=created_at,
                        pipeline_run_id=pipeline_run_id,
                    )
                )
    return edges
```

- [ ] **Step 4: Add repository edge insert methods**

Modify `src/author_aggregation/repository.py` to add constants and methods:

```python
PAPER_EDGE_COLUMNS = [
    "edge_id", "left_source", "left_source_paper_id", "right_source", "right_source_paper_id",
    "match_type", "confidence", "evidence", "created_at", "pipeline_run_id",
]

AUTHOR_EDGE_COLUMNS = [
    "edge_id", "left_observation_id", "right_observation_id", "left_source", "right_source",
    "match_type", "paper_edge_id", "confidence", "evidence", "created_at", "pipeline_run_id",
]
```

Inside `AuthorAggregationRepository` add:

```python
    def insert_paper_edges(self, edges: Iterable[PaperIdentityEdge]) -> None:
        rows = [[asdict(edge)[column] for column in PAPER_EDGE_COLUMNS] for edge in edges]
        if rows:
            self.client.insert("authors_db.paper_identity_edges", rows, column_names=PAPER_EDGE_COLUMNS)

    def insert_author_edges(self, edges: Iterable[AuthorIdentityEdge]) -> None:
        rows = [[asdict(edge)[column] for column in AUTHOR_EDGE_COLUMNS] for edge in edges]
        if rows:
            self.client.insert("authors_db.author_identity_edges", rows, column_names=AUTHOR_EDGE_COLUMNS)
```

- [ ] **Step 5: Run matching tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_matching -v
```

Expected: all tests pass.

- [ ] **Step 6: Run repository tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_repository -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add src/author_aggregation/matching.py src/author_aggregation/repository.py tests/test_author_aggregation_matching.py
git commit -m "添加保守论文和作者匹配"
```

## Task 6: Author Entity Generation

**Files:**
- Create: `src/author_aggregation/entities.py`
- Test: `tests/test_author_aggregation_entities.py`
- Modify: `src/author_aggregation/repository.py`

- [ ] **Step 1: Write failing entity tests**

Create `tests/test_author_aggregation_entities.py`:

```python
import unittest
from datetime import date, datetime

from src.author_aggregation.entities import build_author_entities
from src.author_aggregation.models import AuthorIdentityEdge, AuthorObservation


NOW = datetime(2026, 5, 7, 12, 0, 0)
RUN_ID = "run-test"


def obs(observation_id, source, paper_id, name, year, source_author_id=""):
    return AuthorObservation(
        observation_id=observation_id,
        source=source,
        source_row_key=f"{source}:{paper_id}:1:{name}",
        source_paper_id=paper_id,
        source_author_id=source_author_id,
        author_name=name,
        normalized_author_name=name.lower(),
        author_rank=1,
        author_role="first",
        doi="",
        arxiv_id="",
        dblp_key=paper_id if source == "dblp" else "",
        semantic_id=paper_id if source == "semantic" else "",
        openalex_id=paper_id if source == "openalex" else "",
        title="Paper",
        normalized_title="paper",
        publication_date=date(year, 1, 1),
        publication_year=year,
        venue="Journal",
        institution_id="",
        institution_name="Example University" if source == "openalex" else "",
        institution_country="US" if source == "openalex" else "",
        raw_affiliation="",
        citation_count=0,
        fwci=0,
        primary_topic="",
        ccf_class="",
        source_import_time=NOW,
        observed_at=NOW,
        pipeline_run_id=RUN_ID,
    )


def edge(left_id, right_id):
    return AuthorIdentityEdge(
        edge_id=left_id + right_id,
        left_observation_id=left_id,
        right_observation_id=right_id,
        left_source="openalex",
        right_source="semantic",
        match_type="paper_edge_rank_name_exact",
        paper_edge_id=1,
        confidence=1.0,
        evidence="{}",
        created_at=NOW,
        pipeline_run_id=RUN_ID,
    )


class EntityTests(unittest.TestCase):
    def test_unmatched_observation_gets_single_entity(self):
        entities = build_author_entities([obs(1, "arxiv", "A1", "Alice", 2020)], [], NOW, RUN_ID)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].observation_count, 1)
        self.assertEqual(entities[0].canonical_name, "Alice")

    def test_connected_observations_share_entity(self):
        observations = [
            obs(1, "openalex", "W1", "Alice", 2020, "A1"),
            obs(2, "semantic", "S1", "Alice", 2021, "S1"),
            obs(3, "dblp", "D1", "Bob", 2022, "pid/1"),
        ]
        entities = build_author_entities(observations, [edge(1, 2)], NOW, RUN_ID)
        sizes = sorted(entity.observation_count for entity in entities)
        self.assertEqual(sizes, [1, 2])
        alice = [entity for entity in entities if entity.observation_count == 2][0]
        self.assertEqual(alice.source_count, 2)
        self.assertEqual(alice.first_publication_year, 2020)
        self.assertEqual(alice.last_publication_year, 2021)
        self.assertIn("openalex:A1", alice.source_author_ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing entity tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_entities -v
```

Expected: import error or missing entity builder.

- [ ] **Step 3: Implement union-find entity builder**

Create `src/author_aggregation/entities.py`:

```python
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List

from .models import AuthorEntity, AuthorIdentityEdge, AuthorObservation
from .normalization import stable_u64


class UnionFind:
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left, right):
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def most_common_non_empty(values: Iterable[str]) -> str:
    counter = Counter(value for value in values if value)
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def build_author_entities(
    observations: Iterable[AuthorObservation],
    author_edges: Iterable[AuthorIdentityEdge],
    timestamp: datetime,
    pipeline_run_id: str,
) -> List[AuthorEntity]:
    observation_list = list(observations)
    by_id: Dict[int, AuthorObservation] = {obs.observation_id: obs for obs in observation_list}
    union_find = UnionFind(by_id.keys())

    for edge in author_edges:
        if edge.left_observation_id in by_id and edge.right_observation_id in by_id:
            union_find.union(edge.left_observation_id, edge.right_observation_id)

    groups = defaultdict(list)
    for observation in observation_list:
        groups[union_find.find(observation.observation_id)].append(observation)

    entities: List[AuthorEntity] = []
    for root_id, group in groups.items():
        canonical = sorted(group, key=lambda obs: (-len(obs.author_name), obs.author_name))[0]
        years = [obs.publication_year for obs in group if obs.publication_year]
        source_author_ids = sorted(
            f"{obs.source}:{obs.source_author_id}"
            for obs in group
            if obs.source_author_id
        )
        source_papers = {(obs.source, obs.source_paper_id) for obs in group}
        sources = sorted({obs.source for obs in group})
        entity_id = stable_u64("entity", min(obs.observation_id for obs in group))
        entities.append(
            AuthorEntity(
                author_entity_id=entity_id,
                canonical_name=canonical.author_name,
                normalized_canonical_name=canonical.normalized_author_name,
                source_count=len(sources),
                observation_count=len(group),
                paper_count=len(source_papers),
                source_author_ids=source_author_ids,
                sources=sources,
                first_publication_year=min(years) if years else 0,
                last_publication_year=max(years) if years else 0,
                primary_institution_name=most_common_non_empty(obs.institution_name for obs in group),
                primary_country=most_common_non_empty(obs.institution_country for obs in group),
                created_at=timestamp,
                updated_at=timestamp,
                pipeline_run_id=pipeline_run_id,
            )
        )
    return entities
```

- [ ] **Step 4: Add repository entity insert method**

Modify `src/author_aggregation/repository.py`:

```python
from .models import AuthorEntity, AuthorIdentityEdge, AuthorObservation, PaperIdentityEdge

ENTITY_COLUMNS = [
    "author_entity_id", "canonical_name", "normalized_canonical_name", "source_count",
    "observation_count", "paper_count", "source_author_ids", "sources",
    "first_publication_year", "last_publication_year", "primary_institution_name",
    "primary_country", "created_at", "updated_at", "pipeline_run_id",
]
```

Inside `AuthorAggregationRepository` add:

```python
    def insert_author_entities(self, entities: Iterable[AuthorEntity]) -> None:
        rows = [[asdict(entity)[column] for column in ENTITY_COLUMNS] for entity in entities]
        if rows:
            self.client.insert("authors_db.author_entities", rows, column_names=ENTITY_COLUMNS)
```

- [ ] **Step 5: Run entity tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_entities -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add src/author_aggregation/entities.py src/author_aggregation/repository.py tests/test_author_aggregation_entities.py
git commit -m "添加保守作者实体生成"
```

## Task 7: Job Orchestration and CLI

**Files:**
- Create: `src/author_aggregation/job.py`
- Test: `tests/test_author_aggregation_job.py`

- [ ] **Step 1: Write failing job tests**

Create `tests/test_author_aggregation_job.py`:

```python
import unittest
from datetime import datetime

from src.author_aggregation.job import AuthorAggregationJob, build_pipeline_run_id, parse_args


class FakeRepository:
    def __init__(self):
        self.created_schema = False
        self.seeded_dictionary = False
        self.inserted_observations = []
        self.inserted_paper_edges = []
        self.inserted_author_edges = []
        self.inserted_entities = []

    def create_schema(self):
        self.created_schema = True

    def seed_field_dictionary(self):
        self.seeded_dictionary = True

    def insert_observations(self, observations):
        self.inserted_observations.extend(observations)

    def insert_paper_edges(self, edges):
        self.inserted_paper_edges.extend(edges)

    def insert_author_edges(self, edges):
        self.inserted_author_edges.extend(edges)

    def insert_author_entities(self, entities):
        self.inserted_entities.extend(entities)


class JobTests(unittest.TestCase):
    def test_build_pipeline_run_id_contains_prefix(self):
        run_id = build_pipeline_run_id(datetime(2026, 5, 7, 12, 30, 0))
        self.assertEqual(run_id, "author_aggregation_20260507_123000")

    def test_parse_args_accepts_init_schema_and_limit(self):
        args = parse_args(["--init-schema", "--limit", "100", "--sources", "openalex,arxiv"])
        self.assertTrue(args.init_schema)
        self.assertEqual(args.limit, 100)
        self.assertEqual(args.sources, "openalex,arxiv")

    def test_init_schema_only_creates_schema_and_dictionary(self):
        repo = FakeRepository()
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.init_schema()
        self.assertTrue(repo.created_schema)
        self.assertTrue(repo.seeded_dictionary)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run failing job tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_job -v
```

Expected: import error or missing job module.

- [ ] **Step 3: Implement CLI and orchestration skeleton**

Create `src/author_aggregation/job.py`:

```python
import argparse
from datetime import datetime
from typing import Iterable, List

from .entities import build_author_entities
from .matching import build_author_identity_edges, build_paper_identity_edges
from .repository import AuthorAggregationRepository, create_clickhouse_client


DEFAULT_SOURCES = ["openalex", "semantic", "arxiv", "dblp"]


def build_pipeline_run_id(now: datetime) -> str:
    return f"author_aggregation_{now.strftime('%Y%m%d_%H%M%S')}"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build conservative author aggregation tables")
    parser.add_argument("--init-schema", action="store_true", help="Create authors_db schema and seed field dictionary")
    parser.add_argument("--dry-run", action="store_true", help="Run extraction and matching without writing derived rows")
    parser.add_argument("--limit", type=int, default=None, help="Maximum source rows per source for smoke tests")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES), help="Comma-separated source list")
    parser.add_argument("--overlap-days", type=int, default=2, help="Overlap days for date-granularity source watermarks")
    return parser.parse_args(argv)


class AuthorAggregationJob:
    def __init__(self, repository: AuthorAggregationRepository, pipeline_run_id: str):
        self.repository = repository
        self.pipeline_run_id = pipeline_run_id

    def init_schema(self) -> None:
        self.repository.create_schema()
        self.repository.seed_field_dictionary()

    def run_from_observations(self, observations, timestamp: datetime, dry_run: bool = False):
        paper_edges = build_paper_identity_edges(observations, timestamp, self.pipeline_run_id)
        author_edges = build_author_identity_edges(observations, paper_edges, timestamp, self.pipeline_run_id)
        entities = build_author_entities(observations, author_edges, timestamp, self.pipeline_run_id)
        if not dry_run:
            self.repository.insert_observations(observations)
            self.repository.insert_paper_edges(paper_edges)
            self.repository.insert_author_edges(author_edges)
            self.repository.insert_author_entities(entities)
        return {
            "observations": len(observations),
            "paper_edges": len(paper_edges),
            "author_edges": len(author_edges),
            "entities": len(entities),
            "dry_run": dry_run,
        }


def main(argv=None) -> int:
    args = parse_args(argv)
    now = datetime.now()
    repo = AuthorAggregationRepository(create_clickhouse_client())
    job = AuthorAggregationJob(repository=repo, pipeline_run_id=build_pipeline_run_id(now))

    if args.init_schema:
        job.init_schema()
        print("authors_db schema initialized")
        return 0

    print("Incremental source extraction is implemented in Task 8.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run job tests**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_job -v
```

Expected: all tests pass.

- [ ] **Step 5: Verify schema CLI imports**

Run:

```bash
python3 -m src.author_aggregation.job --help
```

Expected: command prints help text and exits with code 0.

- [ ] **Step 6: Commit Task 7**

Run:

```bash
git add src/author_aggregation/job.py tests/test_author_aggregation_job.py
git commit -m "添加作者聚合任务入口"
```

## Task 8: End-to-End Small-Window Pipeline and Verification

**Files:**
- Modify: `src/author_aggregation/job.py`
- Modify: `src/author_aggregation/repository.py`
- Test: `tests/test_author_aggregation_job.py`

- [ ] **Step 1: Add fake-repository end-to-end test**

Append to `tests/test_author_aggregation_job.py`:

```python
    def test_run_from_observations_builds_edges_and_entities(self):
        from datetime import date
        from src.author_aggregation.models import AuthorObservation

        now = datetime(2026, 5, 7, 12, 0, 0)

        def observation(source, paper_id, oid, doi):
            return AuthorObservation(
                observation_id=oid,
                source=source,
                source_row_key=f"{source}:{paper_id}:1:alice",
                source_paper_id=paper_id,
                source_author_id=f"{source}-alice",
                author_name="Alice",
                normalized_author_name="alice",
                author_rank=1,
                author_role="first",
                doi=doi,
                arxiv_id="",
                dblp_key="",
                semantic_id=paper_id if source == "semantic" else "",
                openalex_id=paper_id if source == "openalex" else "",
                title="A Conservative Matching Paper",
                normalized_title="a conservative matching paper",
                publication_date=date(2026, 1, 1),
                publication_year=2026,
                venue="Journal",
                institution_id="",
                institution_name="",
                institution_country="",
                raw_affiliation="",
                citation_count=0,
                fwci=0.0,
                primary_topic="",
                ccf_class="",
                source_import_time=now,
                observed_at=now,
                pipeline_run_id="run-test",
            )

        repo = FakeRepository()
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        metrics = job.run_from_observations(
            [
                observation("openalex", "W1", 1, "10.1/test"),
                observation("semantic", "S1", 2, "10.1/test"),
            ],
            timestamp=now,
            dry_run=False,
        )

        self.assertEqual(metrics["observations"], 2)
        self.assertEqual(metrics["paper_edges"], 1)
        self.assertEqual(metrics["author_edges"], 1)
        self.assertEqual(metrics["entities"], 1)
        self.assertEqual(len(repo.inserted_observations), 2)
        self.assertEqual(len(repo.inserted_paper_edges), 1)
        self.assertEqual(len(repo.inserted_author_edges), 1)
        self.assertEqual(len(repo.inserted_entities), 1)
```

- [ ] **Step 2: Run the failing end-to-end job test**

Run:

```bash
python3 -m unittest tests.test_author_aggregation_job -v
```

Expected: fail if `run_from_observations` does not yet write all derived outputs.

- [ ] **Step 3: Complete job execution path**

Modify `src/author_aggregation/job.py` to support source extraction after mappers are available:

```python
from . import source_mappers


SOURCE_MAPPERS = {
    "openalex": source_mappers.map_openalex_row,
    "semantic": source_mappers.map_semantic_row,
    "arxiv": source_mappers.map_arxiv_row,
    "dblp": source_mappers.map_dblp_row,
}
```

Add a method to `AuthorAggregationJob`:

```python
    def normalize_source_rows(self, source: str, rows, observed_at: datetime):
        mapper = SOURCE_MAPPERS[source]
        return [mapper(row, self.pipeline_run_id, observed_at) for row in rows]
```

If the live ClickHouse client returns tuples instead of dictionaries for `SELECT *`, add repository-level source-specific column lists in `repository.py` and convert query results to dictionaries:

```python
def rows_to_dicts(column_names, result_rows):
    return [dict(zip(column_names, row)) for row in result_rows]
```

Use `client.query(sql).column_names` and `client.query(sql).result_rows` in `fetch_source_rows()`.

- [ ] **Step 4: Run full author aggregation unit tests**

Run:

```bash
python3 -m unittest \
  tests.test_author_aggregation_normalization \
  tests.test_author_aggregation_schema \
  tests.test_author_aggregation_source_mappers \
  tests.test_author_aggregation_repository \
  tests.test_author_aggregation_matching \
  tests.test_author_aggregation_entities \
  tests.test_author_aggregation_job
```

Expected: all tests pass.

- [ ] **Step 5: Run existing fetcher regression tests**

Run:

```bash
python3 -m unittest tests.test_arxiv_fetcher tests.test_semantic_fetcher tests.test_openalex_fetcher
```

Expected: all tests pass. This verifies the author aggregation work did not break source fetchers.

- [ ] **Step 6: Initialize schema in real ClickHouse**

Run:

```bash
python3 -m src.author_aggregation.job --init-schema
```

Expected:

```text
authors_db schema initialized
```

Then verify:

```bash
clickhouse-client --query "SHOW TABLES FROM authors_db"
```

Expected output includes:

```text
author_entities
author_identity_edges
author_ingest_state
author_observations
paper_identity_edges
schema_field_dictionary
```

- [ ] **Step 7: Run small dry-run smoke check**

After full extraction support exists, run:

```bash
python3 -m src.author_aggregation.job --dry-run --limit 100 --sources openalex,semantic,arxiv,dblp
```

Expected: command exits 0 and prints counts for observations, paper edges, author edges, and entities. It must not write derived rows when `--dry-run` is set.

- [ ] **Step 8: Commit Task 8**

Run:

```bash
git add src/author_aggregation/job.py src/author_aggregation/repository.py tests/test_author_aggregation_job.py
git commit -m "完成作者聚合小窗口流水线"
```

## Final Verification

- [ ] **Step 1: Run all author aggregation tests**

Run:

```bash
python3 -m unittest discover tests -p 'test_author_aggregation*.py'
```

Expected: all author aggregation tests pass.

- [ ] **Step 2: Run targeted regression tests**

Run:

```bash
python3 -m unittest tests.test_arxiv_fetcher tests.test_semantic_fetcher tests.test_openalex_fetcher tests.test_dashboard_static
```

Expected: all tests pass.

- [ ] **Step 3: Verify ClickHouse schema**

Run:

```bash
clickhouse-client --query "SHOW TABLES FROM authors_db"
clickhouse-client --query "DESCRIBE TABLE authors_db.author_observations"
clickhouse-client --query "SELECT count() FROM authors_db.schema_field_dictionary"
```

Expected:

- six `authors_db` tables exist;
- `author_observations` includes `source`, `source_row_key`, `normalized_author_name`, and `normalized_title`;
- `schema_field_dictionary` has at least three seeded rows.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intended files are modified or untracked. Do not stage unrelated existing dashboard/docs/deleted-file changes.
