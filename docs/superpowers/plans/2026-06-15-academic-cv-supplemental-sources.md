# Academic CV Supplemental Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reliable h-index, citation-count, ORCID fallback, and Semantic Scholar work supplementation to the Academic CV Builder, then generate a 20-author CSV sample and stop for user review.

**Architecture:** Keep OpenAlex as the primary author/work backbone. Add isolated resolver modules for ORCID fallback and Semantic Scholar confirmation so candidate matching stays internal and final tables remain clean. Phase 1 ends after producing refreshed four-table CSV output for 20 authors under `output/academic_cv_sample_20/`; do not continue to broader batch processing until the user approves the sample.

**Tech Stack:** Python 3 in `venv`, ClickHouse via `clickhouse_connect` and `clickhouse-client`, `requests`, pytest tests under `temp/`, current `src/cv_builder` package.

---

## Source Spec

Implement against:

```text
docs/superpowers/specs/2026-06-15-academic-cv-supplemental-sources-design.md
```

Hard requirements:

- Do not add `semantic_author_id`.
- Do not add `dblp_pid`.
- Do not write candidates, scores, evidence JSON, resolver status, or failure reasons to final CV tables.
- Do not rename the existing venue field in this plan.
- Add `personal_profile.h_index Nullable(UInt32)`.
- Add `research_outputs.citation_count Nullable(UInt32)`.
- Generate and validate `output/academic_cv_sample_20/*.csv` for 20 authors, then stop for user review.

## File Map

- Modify `src/cv_builder/schema.py`: add nullable fields to schema and preserve column order.
- Modify `src/cv_builder/repository.py`: support inserting nullable numeric defaults.
- Modify `src/cv_builder/builders.py`: extract `h_index` and `citation_count`.
- Modify `src/cv_builder/config.py`: add optional Semantic Scholar API base/key settings if not already present in project env.
- Create `src/cv_builder/semantic_scholar_client.py`: minimal Graph API client for paper lookup, paper search, and author lookup.
- Modify `src/cv_builder/orcid_client.py`: add conservative search helpers for DOI/title candidate recall.
- Create `src/cv_builder/matching.py`: normalized title/name/year/rank matching utilities shared by both resolvers.
- Create `src/cv_builder/orcid_resolver.py`: confirm ORCID by work-level evidence.
- Create `src/cv_builder/semantic_scholar_resolver.py`: confirm S2 author and produce confirmed supplemental works.
- Modify `src/cv_builder/runner.py`: orchestrate OpenAlex, ORCID fallback, S2 supplementation, Crossref enrichment, and final row building.
- Modify `src/cv_builder/cli.py`: wire new client/resolver dependencies into runner construction.
- Modify `README.md`: document source priority and sample generation command.
- Test `temp/test_cv_builder_repository_sql.py`: schema and nullable insert behavior.
- Test `temp/test_cv_builder_builders.py`: h-index and citation-count extraction.
- Test `temp/test_cv_builder_api_clients.py`: Semantic Scholar and ORCID helper HTTP behavior.
- Create `temp/test_cv_builder_matching.py`: name/title/year/rank matching behavior.
- Create `temp/test_cv_builder_orcid_resolver.py`: ORCID confirmation and rejection rules.
- Create `temp/test_cv_builder_semantic_scholar_resolver.py`: S2 confirmation, rejection, dedupe.
- Modify `temp/test_cv_builder_runner.py`: end-to-end orchestration with fallback ORCID and S2 supplemental works.

## Stop Gate

After Task 8, stop. The only permitted next action is reporting the CSV output
and waiting for the user to review it.

Do not run the full author queue, do not start long-running production jobs,
and do not merge or deploy this work until the user confirms the 20-author CSV
sample.

---

### Task 1: Schema and Nullable Numeric Fields

**Files:**
- Modify: `src/cv_builder/schema.py`
- Modify: `src/cv_builder/repository.py`
- Test: `temp/test_cv_builder_repository_sql.py`

- [ ] **Step 1: Write failing schema tests**

Add tests to `temp/test_cv_builder_repository_sql.py`:

```python
def test_personal_profile_schema_contains_nullable_h_index():
    sql = build_create_table_sql("academic_cv", "personal_profile")
    assert "h_index Nullable(UInt32)" in sql
    assert sql.index("email String") < sql.index("h_index Nullable(UInt32)")
    assert sql.index("h_index Nullable(UInt32)") < sql.index("source String")


def test_research_outputs_schema_contains_nullable_citation_count():
    sql = build_create_table_sql("academic_cv", "research_outputs")
    assert "citation_count Nullable(UInt32)" in sql
    assert sql.index("publication_date String") < sql.index("citation_count Nullable(UInt32)")
    assert sql.index("citation_count Nullable(UInt32)") < sql.index("authors String")
```

Extend `test_insert_rows_uses_schema_column_order_and_fills_missing_values()` expected values so the missing `h_index` defaults to `None`:

```python
assert insert["values"] == [
    [
        "person_1",
        "A123",
        "",
        "Ada Lovelace",
        "",
        "",
        "",
        None,
        "",
        "",
        import_time,
    ]
]
```

- [ ] **Step 2: Run schema tests and verify failure**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_repository_sql.py -q
```

Expected: fails because `h_index`, `citation_count`, and nullable default handling are not implemented.

- [ ] **Step 3: Add schema columns**

In `src/cv_builder/schema.py`, update `personal_profile` columns:

```python
("email", "String"),
("h_index", "Nullable(UInt32)"),
("source", "String"),
```

Update `research_outputs` columns:

```python
("publication_date", "String"),
("citation_count", "Nullable(UInt32)"),
("authors", "String"),
```

- [ ] **Step 4: Add nullable default handling**

In `src/cv_builder/repository.py`, update `_default_for_clickhouse_type()`:

```python
def _default_for_clickhouse_type(column_type: str):
    if column_type.startswith("Nullable("):
        return None
    if column_type.startswith("DateTime"):
        return datetime.now()
    if column_type.startswith("UInt"):
        return 0
    return ""
```

- [ ] **Step 5: Run schema tests and verify pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_repository_sql.py -q
```

Expected: all repository SQL tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/cv_builder/schema.py src/cv_builder/repository.py temp/test_cv_builder_repository_sql.py
git commit -m "feat: add cv metric fields to schema"
```

---

### Task 2: Builder Extraction for h-index and Citation Count

**Files:**
- Modify: `src/cv_builder/builders.py`
- Test: `temp/test_cv_builder_builders.py`

- [ ] **Step 1: Write failing builder tests**

Add to `temp/test_cv_builder_builders.py`:

```python
def test_build_profile_row_extracts_openalex_h_index():
    row = build_profile_row(
        {
            "id": "https://openalex.org/A123",
            "display_name": "Ada Lovelace",
            "summary_stats": {"h_index": 42},
        },
        {},
    )

    assert row["h_index"] == 42


def test_build_profile_row_leaves_h_index_none_when_missing():
    row = build_profile_row(
        {"id": "https://openalex.org/A123", "display_name": "Ada Lovelace"},
        {},
    )

    assert row["h_index"] is None


def test_build_research_output_row_extracts_openalex_citation_count():
    row = build_research_output_row(
        make_person_id("A123"),
        {
            "id": "https://openalex.org/W456",
            "title": "OpenAlex title",
            "cited_by_count": 17,
        },
        {},
    )

    assert row["citation_count"] == 17


def test_build_research_output_row_leaves_citation_count_none_when_missing():
    row = build_research_output_row(
        make_person_id("A123"),
        {"id": "https://openalex.org/W456", "title": "OpenAlex title"},
        {},
    )

    assert row["citation_count"] is None
```

- [ ] **Step 2: Run builder tests and verify failure**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_builders.py -q
```

Expected: fails because `h_index` and `citation_count` are not emitted.

- [ ] **Step 3: Add integer helper**

In `src/cv_builder/builders.py`, add:

```python
def _non_negative_int_or_none(value):
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed
```

- [ ] **Step 4: Add h-index to profile row**

In `build_profile_row()`, add after `email`:

```python
"h_index": _non_negative_int_or_none((author.get("summary_stats") or {}).get("h_index")),
```

- [ ] **Step 5: Add citation count to research row**

In `build_research_output_row()`, add after `publication_date`:

```python
"citation_count": _non_negative_int_or_none(work.get("cited_by_count")),
```

- [ ] **Step 6: Run builder tests and verify pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_builders.py -q
```

Expected: all builder tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/cv_builder/builders.py temp/test_cv_builder_builders.py
git commit -m "feat: extract cv metrics from openalex"
```

---

### Task 3: Matching Utilities

**Files:**
- Create: `src/cv_builder/matching.py`
- Create: `temp/test_cv_builder_matching.py`

- [ ] **Step 1: Write failing matching tests**

Create `temp/test_cv_builder_matching.py`:

```python
from src.cv_builder.matching import (
    author_rank_matches,
    names_are_similar,
    normalize_name,
    normalize_title,
    titles_are_similar,
    years_are_compatible,
)


def test_normalize_title_removes_punctuation_and_collapses_spaces():
    assert normalize_title("  A Study: of AI, Systems! ") == "a study of ai systems"


def test_titles_are_similar_accepts_equal_normalized_titles():
    assert titles_are_similar("A Study of AI Systems", "a study: of ai systems")


def test_titles_are_similar_rejects_short_or_different_titles():
    assert not titles_are_similar("AI", "AI")
    assert not titles_are_similar("A Study of AI Systems", "A Different Biology Paper")


def test_normalize_name_removes_punctuation_and_lowercases():
    assert normalize_name("Junyou Zhang") == "junyou zhang"
    assert normalize_name("Zhang, Junyou") == "zhang junyou"


def test_names_are_similar_accepts_token_overlap_and_initial_variant():
    assert names_are_similar("Junyou Zhang", ["Juny Zhang", "J. Zhang"])


def test_names_are_similar_rejects_unrelated_names():
    assert not names_are_similar("Junyou Zhang", ["Michael Smith"])


def test_years_are_compatible_accepts_same_or_missing_year():
    assert years_are_compatible(2020, 2020)
    assert years_are_compatible(2020, None)
    assert not years_are_compatible(2020, 2022)


def test_author_rank_matches_accepts_same_or_nearby_rank():
    assert author_rank_matches(3, 3)
    assert author_rank_matches(3, 4)
    assert not author_rank_matches(3, 7)
```

- [ ] **Step 2: Run matching tests and verify failure**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_matching.py -q
```

Expected: fails because `src.cv_builder.matching` does not exist.

- [ ] **Step 3: Implement matching utilities**

Create `src/cv_builder/matching.py`:

```python
"""Conservative matching helpers for Academic CV supplemental sources."""

from __future__ import annotations

from difflib import SequenceMatcher
import re


_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def normalize_title(value) -> str:
    text = "" if value is None else str(value).lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def normalize_name(value) -> str:
    text = "" if value is None else str(value).lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def titles_are_similar(left, right) -> bool:
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if len(left_norm) < 20 or len(right_norm) < 20:
        return False
    if left_norm == right_norm:
        return True
    return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.94


def names_are_similar(name, aliases) -> bool:
    name_norm = normalize_name(name)
    if not name_norm:
        return False
    name_tokens = set(name_norm.split())
    for alias in aliases or []:
        alias_norm = normalize_name(alias)
        if not alias_norm:
            continue
        if name_norm == alias_norm:
            return True
        alias_tokens = set(alias_norm.split())
        if len(name_tokens & alias_tokens) >= 2:
            return True
        if _initial_last_name_match(name_tokens, alias_tokens):
            return True
        if SequenceMatcher(None, name_norm, alias_norm).ratio() >= 0.88:
            return True
    return False


def years_are_compatible(left_year, right_year) -> bool:
    left = _to_int_or_none(left_year)
    right = _to_int_or_none(right_year)
    if left is None or right is None:
        return True
    return left == right


def author_rank_matches(left_rank, right_rank) -> bool:
    left = _to_int_or_none(left_rank)
    right = _to_int_or_none(right_rank)
    if left is None or right is None:
        return False
    return abs(left - right) <= 1


def _to_int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _initial_last_name_match(left_tokens: set[str], right_tokens: set[str]) -> bool:
    if not left_tokens or not right_tokens:
        return False
    shared = left_tokens & right_tokens
    if not shared:
        return False
    left_initials = {token[0] for token in left_tokens if token}
    right_initials = {token[0] for token in right_tokens if token}
    return bool(left_initials & right_initials)
```

- [ ] **Step 4: Run matching tests and verify pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_matching.py -q
```

Expected: all matching tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/cv_builder/matching.py temp/test_cv_builder_matching.py
git commit -m "feat: add cv identity matching helpers"
```

---

### Task 4: Semantic Scholar Client

**Files:**
- Modify: `src/cv_builder/config.py`
- Create: `src/cv_builder/semantic_scholar_client.py`
- Modify: `temp/test_cv_builder_api_clients.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing Semantic Scholar client tests**

Add to `temp/test_cv_builder_api_clients.py`:

```python
from src.cv_builder.semantic_scholar_client import SemanticScholarClient
```

Add tests:

```python
def test_semantic_scholar_client_gets_paper_by_doi_with_api_key():
    client = SemanticScholarClient(make_config(semantic_api_key="key-123"))
    session = FakeSession(get_responses=[FakeResponse(payload={"paperId": "S2P1"})])
    client.session = session

    assert client.get_paper_by_doi("10.1234/example") == {"paperId": "S2P1"}

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234%2Fexample"
    assert kwargs["headers"]["x-api-key"] == "key-123"
    assert "authors" in kwargs["params"]["fields"]


def test_semantic_scholar_client_searches_papers_by_title():
    client = SemanticScholarClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(payload={"data": [{"paperId": "S2P1"}]})])
    client.session = session

    assert client.search_papers_by_title("Reliable Paper") == [{"paperId": "S2P1"}]

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert kwargs["params"]["query"] == "Reliable Paper"
    assert kwargs["params"]["limit"] == 5


def test_semantic_scholar_client_gets_author_with_papers():
    client = SemanticScholarClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(payload={"authorId": "S2A1", "papers": []})])
    client.session = session

    assert client.get_author("S2A1") == {"authorId": "S2A1", "papers": []}

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.semanticscholar.org/graph/v1/author/S2A1"
    assert "hIndex" in kwargs["params"]["fields"]
```

Update `make_config()` defaults to include:

```python
"semantic_base_url": "https://api.semanticscholar.org/graph/v1",
"semantic_api_key": "",
```

- [ ] **Step 2: Run API client tests and verify failure**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_api_clients.py -q
```

Expected: fails because config fields and `SemanticScholarClient` are missing.

- [ ] **Step 3: Extend config**

In `src/cv_builder/config.py`, add to `CvBuilderConfig`:

```python
semantic_base_url: str
semantic_api_key: str
```

Add to `get_config()`:

```python
semantic_base_url=os.environ.get("SEMANTIC_BASE_URL", "https://api.semanticscholar.org/graph/v1"),
semantic_api_key=os.environ.get("SEMANTIC_API_KEY", ""),
```

- [ ] **Step 4: Implement Semantic Scholar client**

Create `src/cv_builder/semantic_scholar_client.py`:

```python
"""Semantic Scholar Graph API client for Academic CV supplementation."""

from __future__ import annotations

from urllib.parse import quote

import requests

from .config import CvBuilderConfig


PAPER_FIELDS = "paperId,externalIds,title,year,venue,publicationTypes,citationCount,authors.authorId,authors.name"
AUTHOR_FIELDS = "authorId,externalIds,url,name,affiliations,homepage,paperCount,citationCount,hIndex,papers.paperId,papers.externalIds,papers.title,papers.year,papers.venue,papers.publicationTypes,papers.citationCount,papers.authors.authorId,papers.authors.name"


class SemanticScholarClient:
    def __init__(self, config: CvBuilderConfig) -> None:
        self.config = config
        self.session = requests.Session()

    def get_paper_by_doi(self, doi: str) -> dict:
        normalized = _normalize_doi(doi)
        if not normalized:
            return {}
        return self._get_json(
            f"{self._base_url()}/paper/DOI:{quote(normalized, safe='')}",
            params={"fields": PAPER_FIELDS},
        )

    def search_papers_by_title(self, title: str, limit: int = 5) -> list[dict]:
        query = " ".join(str(title or "").split())
        if not query:
            return []
        payload = self._get_json(
            f"{self._base_url()}/paper/search",
            params={"query": query, "limit": limit, "fields": PAPER_FIELDS},
        )
        return payload.get("data") or []

    def get_author(self, author_id: str) -> dict:
        clean_id = " ".join(str(author_id or "").split())
        if not clean_id:
            return {}
        return self._get_json(
            f"{self._base_url()}/author/{quote(clean_id, safe='')}",
            params={"fields": AUTHOR_FIELDS},
        )

    def _get_json(self, url: str, params: dict) -> dict:
        response = self.session.get(
            url,
            params=params,
            headers=self._headers(),
            timeout=self.config.request_timeout,
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict:
        headers = {}
        if self.config.semantic_api_key:
            headers["x-api-key"] = self.config.semantic_api_key
        return headers

    def _base_url(self) -> str:
        return self.config.semantic_base_url.rstrip("/")


def _normalize_doi(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    for prefix in ("https://doi.org/", "https://dx.doi.org/", "http://doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            return text[len(prefix) :]
    return text
```

- [ ] **Step 5: Update `.env.example`**

Add:

```bash
SEMANTIC_BASE_URL=https://api.semanticscholar.org/graph/v1
SEMANTIC_API_KEY=semantic_scholar_key
```

- [ ] **Step 6: Run API client tests and verify pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_api_clients.py -q
```

Expected: all API client tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/cv_builder/config.py src/cv_builder/semantic_scholar_client.py temp/test_cv_builder_api_clients.py .env.example
git commit -m "feat: add semantic scholar cv client"
```

---

### Task 5: ORCID Search Helpers and Resolver

**Files:**
- Modify: `src/cv_builder/orcid_client.py`
- Create: `src/cv_builder/orcid_resolver.py`
- Modify: `temp/test_cv_builder_api_clients.py`
- Create: `temp/test_cv_builder_orcid_resolver.py`

- [ ] **Step 1: Write failing ORCID client helper tests**

Add to `temp/test_cv_builder_api_clients.py`:

```python
def test_orcid_client_searches_by_doi_after_token():
    client = OrcidClient(make_config())
    session = FakeSession(
        post_responses=[FakeResponse(payload={"access_token": "token", "expires_in": 3600})],
        get_responses=[FakeResponse(payload={"result": [{"orcid-identifier": {"path": "0000-0001-0000-0000"}}]})],
    )
    client.session = session

    assert client.search_by_doi("10.1234/example") == ["0000-0001-0000-0000"]

    args, kwargs = session.get_calls[0]
    assert args[0].endswith("/expanded-search/")
    assert kwargs["params"]["q"] == 'doi-self:"10.1234/example"'


def test_orcid_client_searches_by_title_after_token():
    client = OrcidClient(make_config())
    session = FakeSession(
        post_responses=[FakeResponse(payload={"access_token": "token", "expires_in": 3600})],
        get_responses=[FakeResponse(payload={"result": [{"orcid-identifier": {"path": "0000-0002-0000-0000"}}]})],
    )
    client.session = session

    assert client.search_by_title("Reliable Paper") == ["0000-0002-0000-0000"]
    assert session.get_calls[0][1]["params"]["q"] == 'work-titles:"Reliable Paper"'
```

- [ ] **Step 2: Implement ORCID search helpers**

In `src/cv_builder/orcid_client.py`, add:

```python
def search_by_doi(self, doi: str) -> list[str]:
    clean = _normalize_doi(doi)
    if not clean:
        return []
    return self._expanded_search(f'doi-self:"{clean}"')


def search_by_title(self, title: str) -> list[str]:
    clean = " ".join(str(title or "").split())
    if not clean:
        return []
    return self._expanded_search(f'work-titles:"{clean}"')


def _expanded_search(self, query: str) -> list[str]:
    token = self._get_access_token()
    response = self.session.get(
        f"{self.config.orcid_base_url.rstrip('/')}/expanded-search/",
        params={"q": query},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=self.config.request_timeout,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    results = []
    for item in response.json().get("result") or []:
        path = ((item or {}).get("orcid-identifier") or {}).get("path")
        normalized = _normalize_orcid(path)
        if normalized:
            results.append(normalized)
    return results
```

Add this DOI helper to `src/cv_builder/orcid_client.py`; reuse the existing `_normalize_orcid()` helper already present in that file:

```python
def _normalize_doi(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    for prefix in ("https://doi.org/", "https://dx.doi.org/", "http://doi.org/", "doi:"):
        if text.lower().startswith(prefix):
            return text[len(prefix) :]
    return text
```

- [ ] **Step 3: Write failing ORCID resolver tests**

Create `temp/test_cv_builder_orcid_resolver.py`:

```python
from src.cv_builder.orcid_resolver import OrcidResolver


class FakeOrcidClient:
    def __init__(self, doi_results=None, title_results=None, records=None):
        self.doi_results = doi_results or {}
        self.title_results = title_results or {}
        self.records = records or {}

    def search_by_doi(self, doi):
        return self.doi_results.get(doi, [])

    def search_by_title(self, title):
        return self.title_results.get(title, [])

    def get_record(self, orcid):
        return self.records.get(orcid, {})


def test_orcid_resolver_rejects_name_only_match_without_work_evidence():
    client = FakeOrcidClient(records={"0000-0001-0000-0000": {"orcid-identifier": {"path": "0000-0001-0000-0000"}}})
    resolver = OrcidResolver(client)

    result = resolver.resolve(
        openalex_author={"display_name": "Junyou Zhang"},
        openalex_works=[],
    )

    assert result == ("", {})


def test_orcid_resolver_accepts_two_exact_doi_matches():
    record = {
        "orcid-identifier": {"path": "0000-0001-0000-0000"},
        "person": {"name": {"credit-name": {"value": "Junyou Zhang"}}},
    }
    client = FakeOrcidClient(
        doi_results={"10.1/a": ["0000-0001-0000-0000"], "10.1/b": ["0000-0001-0000-0000"]},
        records={"0000-0001-0000-0000": record},
    )
    resolver = OrcidResolver(client)

    result = resolver.resolve(
        openalex_author={"display_name": "Junyou Zhang"},
        openalex_works=[
            {"doi": "10.1/a", "title": "Paper A", "authorships": [{"author_position": "first", "author": {"display_name": "Junyou Zhang"}}]},
            {"doi": "10.1/b", "title": "Paper B", "authorships": [{"author_position": "first", "author": {"display_name": "Junyou Zhang"}}]},
        ],
    )

    assert result == ("0000-0001-0000-0000", record)
```

- [ ] **Step 4: Implement ORCID resolver**

Create `src/cv_builder/orcid_resolver.py`:

```python
"""Work-evidence-based ORCID fallback resolver."""

from __future__ import annotations

from collections import Counter

from .builders import clean_text, normalize_orcid
from .matching import names_are_similar


class OrcidResolver:
    def __init__(self, orcid_client) -> None:
        self.orcid_client = orcid_client

    def resolve(self, openalex_author: dict, openalex_works: list[dict]) -> tuple[str, dict]:
        works = list(openalex_works or [])
        if not works:
            return "", {}

        doi_counts = Counter()
        for work in works:
            doi = clean_text(work.get("doi"))
            if not doi:
                continue
            for orcid in self.orcid_client.search_by_doi(doi):
                normalized = normalize_orcid(orcid)
                if normalized:
                    doi_counts[normalized] += 1

        for orcid, count in doi_counts.most_common():
            record = self.orcid_client.get_record(orcid)
            if count >= 2:
                return orcid, record
            if count == 1 and _record_name_matches(record, _author_aliases(openalex_author, works)):
                return orcid, record

        title_counts = Counter()
        for work in works:
            title = clean_text(work.get("title") or work.get("display_name"))
            if not title:
                continue
            for orcid in self.orcid_client.search_by_title(title):
                normalized = normalize_orcid(orcid)
                if normalized:
                    title_counts[normalized] += 1

        for orcid, count in title_counts.most_common():
            record = self.orcid_client.get_record(orcid)
            if count >= 2 and _record_name_matches(record, _author_aliases(openalex_author, works)):
                return orcid, record

        return "", {}


def _author_aliases(openalex_author: dict, works: list[dict]) -> list[str]:
    aliases = [clean_text((openalex_author or {}).get("display_name"))]
    for work in works:
        for authorship in work.get("authorships") or []:
            name = clean_text(((authorship or {}).get("author") or {}).get("display_name"))
            if name:
                aliases.append(name)
    return [alias for alias in aliases if alias]


def _record_name_matches(record: dict, aliases: list[str]) -> bool:
    person = (record or {}).get("person") or {}
    name = person.get("name") or {}
    candidates = [
        ((name.get("credit-name") or {}).get("value")),
        ((name.get("given-names") or {}).get("value")),
        ((name.get("family-name") or {}).get("value")),
    ]
    full = " ".join(clean_text(value) for value in candidates[1:] if clean_text(value))
    if full:
        candidates.append(full)
    return any(names_are_similar(candidate, aliases) for candidate in candidates if clean_text(candidate))
```

- [ ] **Step 5: Run ORCID tests and verify pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_api_clients.py temp/test_cv_builder_orcid_resolver.py -q
```

Expected: ORCID client and resolver tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/cv_builder/orcid_client.py src/cv_builder/orcid_resolver.py temp/test_cv_builder_api_clients.py temp/test_cv_builder_orcid_resolver.py
git commit -m "feat: add work-backed orcid resolver"
```

---

### Task 6: Semantic Scholar Resolver

**Files:**
- Create: `src/cv_builder/semantic_scholar_resolver.py`
- Create: `temp/test_cv_builder_semantic_scholar_resolver.py`

- [ ] **Step 1: Write failing S2 resolver tests**

Create `temp/test_cv_builder_semantic_scholar_resolver.py`:

```python
from src.cv_builder.semantic_scholar_resolver import SemanticScholarResolver


class FakeSemanticClient:
    def __init__(self, papers_by_doi=None, search_results=None, authors=None):
        self.papers_by_doi = papers_by_doi or {}
        self.search_results = search_results or {}
        self.authors = authors or {}

    def get_paper_by_doi(self, doi):
        return self.papers_by_doi.get(doi, {})

    def search_papers_by_title(self, title, limit=5):
        return self.search_results.get(title, [])

    def get_author(self, author_id):
        return self.authors.get(author_id, {})


def test_semantic_resolver_rejects_without_work_evidence():
    resolver = SemanticScholarResolver(FakeSemanticClient())

    result = resolver.resolve(
        openalex_author={"display_name": "Junyou Zhang"},
        openalex_works=[],
        existing_work_ids=set(),
    )

    assert result.confirmed_author == {}
    assert result.supplemental_papers == []


def test_semantic_resolver_confirms_author_from_two_doi_matches_and_adds_new_paper():
    client = FakeSemanticClient(
        papers_by_doi={
            "10.1/a": {
                "paperId": "S2P1",
                "externalIds": {"DOI": "10.1/a"},
                "title": "Paper A",
                "year": 2020,
                "authors": [{"authorId": "S2A1", "name": "Junyou Zhang"}],
            },
            "10.1/b": {
                "paperId": "S2P2",
                "externalIds": {"DOI": "10.1/b"},
                "title": "Paper B",
                "year": 2021,
                "authors": [{"authorId": "S2A1", "name": "Juny Zhang"}],
            },
        },
        authors={
            "S2A1": {
                "authorId": "S2A1",
                "name": "Junyou Zhang",
                "hIndex": 9,
                "papers": [
                    {
                        "paperId": "S2P3",
                        "externalIds": {"DOI": "10.1/c"},
                        "title": "Paper C",
                        "year": 2022,
                        "venue": "Journal C",
                        "citationCount": 5,
                        "authors": [{"authorId": "S2A1", "name": "Junyou Zhang"}],
                    }
                ],
            }
        },
    )
    resolver = SemanticScholarResolver(client)

    result = resolver.resolve(
        openalex_author={"display_name": "Junyou Zhang"},
        openalex_works=[
            {"id": "W1", "doi": "10.1/a", "title": "Paper A", "publication_year": 2020, "authorships": [{"author": {"display_name": "Junyou Zhang"}}]},
            {"id": "W2", "doi": "10.1/b", "title": "Paper B", "publication_year": 2021, "authorships": [{"author": {"display_name": "Junyou Zhang"}}]},
        ],
        existing_work_ids={"W1", "W2"},
    )

    assert result.confirmed_author["authorId"] == "S2A1"
    assert result.confirmed_author["hIndex"] == 9
    assert [paper["paperId"] for paper in result.supplemental_papers] == ["S2P3"]
```

- [ ] **Step 2: Run S2 resolver tests and verify failure**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_semantic_scholar_resolver.py -q
```

Expected: fails because resolver does not exist.

- [ ] **Step 3: Implement S2 resolver**

Create `src/cv_builder/semantic_scholar_resolver.py`:

```python
"""Semantic Scholar work-backed resolver for Academic CV supplementation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .builders import clean_text
from .matching import names_are_similar, titles_are_similar, years_are_compatible


@dataclass(frozen=True)
class SemanticScholarResolution:
    confirmed_author: dict
    supplemental_papers: list[dict]


class SemanticScholarResolver:
    def __init__(self, semantic_client) -> None:
        self.semantic_client = semantic_client

    def resolve(self, openalex_author: dict, openalex_works: list[dict], existing_work_ids: set[str]) -> SemanticScholarResolution:
        works = list(openalex_works or [])
        if not works:
            return SemanticScholarResolution({}, [])

        aliases = _author_aliases(openalex_author, works)
        author_counts = Counter()

        for work in works:
            s2_paper = self._lookup_s2_paper(work)
            if not s2_paper or not _paper_matches_work(s2_paper, work):
                continue
            for author in s2_paper.get("authors") or []:
                if names_are_similar(author.get("name"), aliases):
                    author_id = clean_text(author.get("authorId"))
                    if author_id:
                        author_counts[author_id] += 1

        if not author_counts:
            return SemanticScholarResolution({}, [])

        confirmed_author_id, match_count = author_counts.most_common(1)[0]
        if match_count < 1:
            return SemanticScholarResolution({}, [])

        confirmed_author = self.semantic_client.get_author(confirmed_author_id)
        if not confirmed_author:
            return SemanticScholarResolution({}, [])

        supplemental = []
        seen_keys = set(existing_work_ids or set())
        for paper in confirmed_author.get("papers") or []:
            key = _paper_key(paper)
            if not key or key in seen_keys:
                continue
            if not _paper_author_matches(paper, confirmed_author_id, aliases):
                continue
            seen_keys.add(key)
            supplemental.append(paper)

        return SemanticScholarResolution(confirmed_author, supplemental)

    def _lookup_s2_paper(self, work: dict) -> dict:
        doi = clean_text(work.get("doi"))
        if doi:
            return self.semantic_client.get_paper_by_doi(doi)
        title = clean_text(work.get("title") or work.get("display_name"))
        for candidate in self.semantic_client.search_papers_by_title(title):
            if _paper_matches_work(candidate, work):
                return candidate
        return {}


def _author_aliases(openalex_author: dict, works: list[dict]) -> list[str]:
    aliases = [clean_text((openalex_author or {}).get("display_name"))]
    for work in works:
        for authorship in work.get("authorships") or []:
            name = clean_text(((authorship or {}).get("author") or {}).get("display_name"))
            if name:
                aliases.append(name)
    return [alias for alias in aliases if alias]


def _paper_matches_work(paper: dict, work: dict) -> bool:
    paper_doi = clean_text(((paper or {}).get("externalIds") or {}).get("DOI")).lower()
    work_doi = clean_text((work or {}).get("doi")).lower()
    if paper_doi and work_doi and paper_doi == work_doi:
        return True
    return titles_are_similar(paper.get("title"), work.get("title") or work.get("display_name")) and years_are_compatible(
        paper.get("year"),
        work.get("publication_year") or _year_from_date(work.get("publication_date")),
    )


def _paper_author_matches(paper: dict, author_id: str, aliases: list[str]) -> bool:
    for author in paper.get("authors") or []:
        if clean_text(author.get("authorId")) == author_id and names_are_similar(author.get("name"), aliases):
            return True
    return False


def _paper_key(paper: dict) -> str:
    external_ids = (paper or {}).get("externalIds") or {}
    doi = clean_text(external_ids.get("DOI")).lower()
    if doi:
        return f"doi:{doi}"
    paper_id = clean_text(paper.get("paperId"))
    if paper_id:
        return f"s2:{paper_id}"
    title = clean_text(paper.get("title"))
    year = clean_text(paper.get("year"))
    if title and year:
        return f"title:{title.lower()}:{year}"
    return ""


def _year_from_date(value) -> int | None:
    text = clean_text(value)
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None
```

- [ ] **Step 4: Run S2 resolver tests and verify pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_semantic_scholar_resolver.py -q
```

Expected: all S2 resolver tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/cv_builder/semantic_scholar_resolver.py temp/test_cv_builder_semantic_scholar_resolver.py
git commit -m "feat: add semantic scholar cv resolver"
```

---

### Task 7: Runner Orchestration and Supplemental Rows

**Files:**
- Modify: `src/cv_builder/runner.py`
- Modify: `src/cv_builder/cli.py`
- Modify: `src/cv_builder/builders.py`
- Modify: `temp/test_cv_builder_runner.py`

- [ ] **Step 1: Write failing runner tests for ORCID fallback**

In `temp/test_cv_builder_runner.py`, add a fake resolver:

```python
class FakeOrcidResolver:
    def __init__(self, result=("", {})):
        self.result = result
        self.requests = []

    def resolve(self, openalex_author, openalex_works):
        self.requests.append((openalex_author, list(openalex_works)))
        return self.result
```

Add test:

```python
def test_process_author_uses_orcid_resolver_when_openalex_has_no_orcid():
    record = {
        "orcid-identifier": {"path": "0000-0001-0000-0000"},
        "person": {"biography": {"content": "Confirmed bio."}},
    }
    repository = FakeRepository(work_ids=["W456"])
    openalex_client = FakeOpenAlexClient(
        authors={"A123": {"id": "A123", "display_name": "Ada Lovelace"}},
        author_work_ids={"A123": ["W456"]},
        works={"W456": {"id": "W456", "title": "Reliable Paper", "doi": "10.1/a"}},
    )
    resolver = FakeOrcidResolver(result=("0000-0001-0000-0000", record))
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient(), orcid_resolver=resolver)

    runner.process_author("A123")

    assert resolver.requests
    assert repository.profiles[0]["orcid"] == "0000-0001-0000-0000"
    assert repository.profiles[0]["bio"] == "Confirmed bio."
```

- [ ] **Step 2: Write failing runner tests for S2 supplemental works**

Add fake S2 resolver:

```python
class FakeSemanticResolver:
    def __init__(self, confirmed_author=None, supplemental_papers=None):
        self.confirmed_author = confirmed_author or {}
        self.supplemental_papers = supplemental_papers or []
        self.requests = []

    def resolve(self, openalex_author, openalex_works, existing_work_ids):
        self.requests.append((openalex_author, list(openalex_works), set(existing_work_ids)))
        from src.cv_builder.semantic_scholar_resolver import SemanticScholarResolution
        return SemanticScholarResolution(self.confirmed_author, self.supplemental_papers)
```

Add test:

```python
def test_process_author_adds_confirmed_semantic_scholar_supplemental_work():
    repository = FakeRepository(work_ids=[])
    openalex_client = FakeOpenAlexClient(
        authors={"A123": {"id": "A123", "display_name": "Ada Lovelace", "summary_stats": {"h_index": 3}}},
        author_work_ids={"A123": ["W456"]},
        works={"W456": {"id": "W456", "title": "OpenAlex Paper", "cited_by_count": 10}},
    )
    semantic_resolver = FakeSemanticResolver(
        confirmed_author={"authorId": "S2A1", "hIndex": 11},
        supplemental_papers=[
            {
                "paperId": "S2P1",
                "externalIds": {"DOI": "10.2/s2"},
                "title": "S2 Paper",
                "year": 2024,
                "venue": "Journal S2",
                "citationCount": 7,
                "authors": [{"authorId": "S2A1", "name": "Ada Lovelace"}],
            }
        ],
    )
    runner = CvBuildRunner(
        repository,
        openalex_client,
        FakeOrcidClient(),
        FakeCrossrefClient(),
        semantic_resolver=semantic_resolver,
    )

    runner.process_author("A123")

    assert semantic_resolver.requests
    titles = [row["work_title"] for row in repository.research_outputs[0]]
    assert "OpenAlex Paper" in titles
    assert "S2 Paper" in titles
    s2_row = next(row for row in repository.research_outputs[0] if row["work_title"] == "S2 Paper")
    assert s2_row["citation_count"] == 7
```

- [ ] **Step 3: Update runner constructor**

In `src/cv_builder/runner.py`, change constructor:

```python
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
```

- [ ] **Step 4: Refactor research building to return works and rows**

In `runner.py`, replace `_build_research_output_rows()` with a helper that returns both OpenAlex works and rows:

```python
def _build_openalex_research_outputs(self, author_id: str, person_id: str, work_limit: int) -> tuple[list[dict], list[dict]]:
    works = []
    rows = []
    openalex_work_ids = self.openalex_client.get_author_work_ids(author_id, limit=work_limit)
    local_work_ids = self.repository.get_local_work_ids_for_author(author_id, work_limit)
    for work_id in _merge_work_ids(openalex_work_ids, local_work_ids, work_limit):
        openalex_work = self.openalex_client.get_work(work_id)
        if not openalex_work:
            continue
        works.append(openalex_work)
        doi = clean_text(openalex_work.get("doi"))
        crossref_work = self.crossref_client.get_work_by_doi(doi) if doi else {}
        row = build_research_output_row(person_id, openalex_work, crossref_work)
        if row:
            rows.append(row)
    return works, rows
```

- [ ] **Step 5: Use ORCID fallback after OpenAlex works are loaded**

In `process_author()`, load works before building profile:

```python
openalex_works, research_output_rows = self._build_openalex_research_outputs(author_id, person_id, work_limit)
orcid = normalize_orcid(openalex_author.get("orcid"))
orcid_record = self.orcid_client.get_record(orcid) if orcid else {}
if not orcid_record and self.orcid_resolver:
    resolved_orcid, resolved_record = self.orcid_resolver.resolve(openalex_author, openalex_works)
    if resolved_orcid and resolved_record:
        openalex_author = dict(openalex_author)
        openalex_author["orcid"] = resolved_orcid
        orcid_record = resolved_record
```

Then remove the old later call to `_build_research_output_rows()`.

- [ ] **Step 6: Add S2 supplemental rows**

Add helper in `runner.py`:

```python
def _build_semantic_supplemental_rows(self, openalex_author: dict, openalex_works: list[dict], person_id: str, existing_rows: list[dict]) -> list[dict]:
    if not self.semantic_resolver:
        return []
    existing_ids = {row["id"] for row in existing_rows if row.get("id")}
    resolution = self.semantic_resolver.resolve(openalex_author, openalex_works, existing_ids)
    rows = []
    for paper in resolution.supplemental_papers:
        row = build_semantic_research_output_row(person_id, paper)
        if row:
            rows.append(row)
    return rows
```

In `process_author()`, after OpenAlex research rows:

```python
research_output_rows.extend(
    self._build_semantic_supplemental_rows(openalex_author, openalex_works, person_id, research_output_rows)
)
```

- [ ] **Step 7: Add S2 row builder**

In `src/cv_builder/builders.py`, add:

```python
def build_semantic_research_output_row(person_id: str, semantic_paper: dict) -> dict:
    if not clean_text(person_id):
        return {}
    paper = semantic_paper or {}
    paper_id = clean_text(paper.get("paperId"))
    external_ids = paper.get("externalIds") or {}
    doi = clean_text(external_ids.get("DOI"))
    stable_key = doi or paper_id
    title = clean_text(paper.get("title"))
    if not stable_key or not title:
        return {}
    authors = [
        clean_text((author or {}).get("name"))
        for author in paper.get("authors") or []
        if clean_text((author or {}).get("name"))
    ]
    return {
        "id": make_research_output_id(person_id, f"S2:{stable_key}"),
        "author_id": person_id,
        "work_title": title,
        "work_type": _semantic_work_type(paper),
        "venue_name": clean_text(paper.get("venue")),
        "publication_date": clean_text(paper.get("year")),
        "citation_count": _non_negative_int_or_none(paper.get("citationCount")),
        "authors": json.dumps(authors, ensure_ascii=False),
        "source": "semantic_scholar",
        "source_url": f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else "",
        "import_time": datetime.now(),
    }
```

Also add:

```python
def _semantic_work_type(paper: dict) -> str:
    publication_types = paper.get("publicationTypes") or []
    if publication_types:
        return clean_text(publication_types[0])
    return ""
```

- [ ] **Step 8: Wire CLI dependencies**

In `src/cv_builder/cli.py`, import:

```python
from src.cv_builder.orcid_resolver import OrcidResolver
from src.cv_builder.semantic_scholar_client import SemanticScholarClient
from src.cv_builder.semantic_scholar_resolver import SemanticScholarResolver
```

Update `build_runner()`:

```python
orcid_client = OrcidClient(config)
semantic_client = SemanticScholarClient(config)
return CvBuildRunner(
    repository=repository,
    openalex_client=OpenAlexClient(config),
    orcid_client=orcid_client,
    crossref_client=CrossrefClient(config),
    orcid_resolver=OrcidResolver(orcid_client),
    semantic_resolver=SemanticScholarResolver(semantic_client),
)
```

- [ ] **Step 9: Run runner tests and fix integration issues**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_runner.py -q
```

Expected: all runner tests pass.

- [ ] **Step 10: Commit**

Run:

```bash
git add src/cv_builder/runner.py src/cv_builder/cli.py src/cv_builder/builders.py temp/test_cv_builder_runner.py
git commit -m "feat: orchestrate cv supplemental sources"
```

---

### Task 8: Full Test, Schema Migration, and 20-Author CSV Review Sample

**Files:**
- Modify: `README.md`
- Output: `output/academic_cv_sample_20/personal_profile.csv`
- Output: `output/academic_cv_sample_20/education_work_experience.csv`
- Output: `output/academic_cv_sample_20/research_outputs.csv`
- Output: `output/academic_cv_sample_20/funding_info.csv`

- [ ] **Step 1: Run full CV builder test suite**

Run:

```bash
venv/bin/python3 -m pytest temp/test_cv_builder_cli.py temp/test_cv_builder_runner.py temp/test_cv_builder_repository_sql.py temp/test_cv_builder_builders.py temp/test_cv_builder_ids.py temp/test_cv_builder_api_clients.py temp/test_cv_builder_matching.py temp/test_cv_builder_orcid_resolver.py temp/test_cv_builder_semantic_scholar_resolver.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

Run:

```bash
venv/bin/python3 -m py_compile src/cv_builder/*.py
```

Expected: command exits 0.

- [ ] **Step 3: Migrate local ClickHouse tables**

Run:

```bash
clickhouse-client --query "ALTER TABLE academic_cv.personal_profile ADD COLUMN IF NOT EXISTS h_index Nullable(UInt32) AFTER email"
clickhouse-client --query "ALTER TABLE academic_cv.research_outputs ADD COLUMN IF NOT EXISTS citation_count Nullable(UInt32) AFTER publication_date"
clickhouse-client --query "DESCRIBE TABLE academic_cv.personal_profile"
clickhouse-client --query "DESCRIBE TABLE academic_cv.research_outputs"
```

Expected:

```text
personal_profile contains h_index Nullable(UInt32)
research_outputs contains citation_count Nullable(UInt32)
```

- [ ] **Step 4: Reprocess the existing 20 sample authors only**

Run:

```bash
venv/bin/python3 - <<'PY'
import csv
import subprocess
from pathlib import Path

base = Path("output/academic_cv_sample_20")
authors = []
with (base / "personal_profile.csv").open(newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        openalex_id = row.get("openalex_id")
        if openalex_id:
            authors.append(openalex_id)

for openalex_id in authors:
    subprocess.run(
        ["venv/bin/python3", "-m", "src.cv_builder.cli", "process-author", openalex_id, "--work-limit", "200"],
        check=True,
    )
PY
```

Expected: 20 authors process without uncaught exceptions.

- [ ] **Step 5: Export exactly those 20 authors to CSV**

Run:

```bash
ids=$(venv/bin/python3 - <<'PY'
import csv
from pathlib import Path
ids = []
path = Path("output/academic_cv_sample_20/personal_profile.csv")
with path.open(newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        value = row.get("id")
        if value:
            ids.append(value)
print(",".join("'" + value.replace("'", "\\'") + "'" for value in sorted(set(ids))))
PY
)

clickhouse-client --query "SELECT id, openalex_id, orcid, name, bio, country, email, h_index, source, source_url, import_time FROM academic_cv.personal_profile FINAL WHERE id IN ($ids) ORDER BY id FORMAT CSVWithNames" > output/academic_cv_sample_20/personal_profile.csv

clickhouse-client --query "SELECT id, author_id, role_title, institution_name, department_name, city, affiliation_type, province, date_range, country, source, source_url, import_time FROM academic_cv.education_work_experience FINAL WHERE author_id IN ($ids) ORDER BY author_id, id FORMAT CSVWithNames" > output/academic_cv_sample_20/education_work_experience.csv

clickhouse-client --query "SELECT id, author_id, work_title, work_type, venue_name, publication_date, citation_count, authors, source, source_url, import_time FROM academic_cv.research_outputs FINAL WHERE author_id IN ($ids) ORDER BY author_id, publication_date, id FORMAT CSVWithNames" > output/academic_cv_sample_20/research_outputs.csv

clickhouse-client --query "SELECT id, author_id, end_date, award_title, city, funder_name, province, funding_type, country, start_date, source, source_url, import_time FROM academic_cv.funding_info FINAL WHERE author_id IN ($ids) ORDER BY author_id, id FORMAT CSVWithNames" > output/academic_cv_sample_20/funding_info.csv
```

Expected: four CSV files are refreshed under `output/academic_cv_sample_20/`.

- [ ] **Step 6: Validate CSV linkage and required columns**

Run:

```bash
venv/bin/python3 - <<'PY'
import csv
from pathlib import Path

base = Path("output/academic_cv_sample_20")
profiles = list(csv.DictReader((base / "personal_profile.csv").open(newline="", encoding="utf-8")))
profile_ids = {row["id"] for row in profiles}
profile_fields = set(profiles[0].keys()) if profiles else set()
print("profiles", len(profiles))
print("profile_has_h_index", "h_index" in profile_fields)

research = list(csv.DictReader((base / "research_outputs.csv").open(newline="", encoding="utf-8")))
research_fields = set(research[0].keys()) if research else set()
print("research_outputs", len(research))
print("research_has_citation_count", "citation_count" in research_fields)

for name in ["education_work_experience", "research_outputs", "funding_info"]:
    rows = list(csv.DictReader((base / f"{name}.csv").open(newline="", encoding="utf-8")))
    orphan = sorted({row["author_id"] for row in rows if row.get("author_id") not in profile_ids})
    print(name, len(rows), "orphan_author_ids", len(orphan))

for forbidden in ["semantic_author_id", "dblp_pid", "candidate", "score", "evidence"]:
    if forbidden in profile_fields or forbidden in research_fields:
        raise SystemExit(f"forbidden field exported: {forbidden}")
PY
```

Expected:

```text
profiles 20
profile_has_h_index True
research_has_citation_count True
orphan_author_ids 0 for all child tables
```

- [ ] **Step 7: Update README with phase-1 stop gate**

In `README.md`, add under Academic CV Builder:

```markdown
Supplemental source development uses a review gate: after schema and resolver
logic changes, regenerate `output/academic_cv_sample_20/*.csv` for the same 20
authors and stop for review before running larger queues.
```

- [ ] **Step 8: Commit code, tests, docs, and sample CSV**

Run:

```bash
git add README.md src/cv_builder temp/test_cv_builder_*.py
git add -f output/academic_cv_sample_20
git commit -m "feat: add cv supplemental source sample"
```

- [ ] **Step 9: Stop and report sample**

Do not continue to a production run.

Report:

```text
Generated output/academic_cv_sample_20/*.csv for 20 authors.
personal_profile rows: <count>
research_outputs rows: <count>
education_work_experience rows: <count>
funding_info rows: <count>
Tests: <command and pass count>
Waiting for user review before further work.
```

---

## Self-Review Checklist

- [x] Spec coverage: fields, ORCID fallback, S2 supplementation, no candidate/score/evidence persistence, 20-author sample stop gate.
- [x] Placeholder scan: no unfinished-marker words or vague implementation steps.
- [x] Type consistency: `h_index` and `citation_count` are `Nullable(UInt32)` in schema and `None` in Python for unknown values.
- [x] Boundary check: S2 author IDs and ORCID/S2 matching evidence stay internal to resolvers.
- [x] Stop gate: plan stops after generating and reporting the 20-author CSV sample.
