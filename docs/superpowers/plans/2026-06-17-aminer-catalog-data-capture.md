# AMiner Catalog Data Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `src/aminer_builder` so `academic` can run bounded AMiner topic catalog sweeps, store raw AMiner responses, parse source observations, queue person profile fetches, and verify each stage with both mock tests and fixed instance tests.

**Architecture:** Implement a queue-based pipeline in the `academic` repo, separate from `academic_cv`. The pipeline expands catalog/shard/topic configs into rec5 recall jobs, builds raw response and observation rows, produces a mandatory 20-person CSV review package before any live ClickHouse data write, then enables ClickHouse queue/profile persistence after user approval.

**Tech Stack:** Python 3, stdlib HTTP/JSON/argparse/dataclasses, `clickhouse_connect`, pytest tests under `temp`, existing `venv/bin/python3` command style, ClickHouse `MergeTree` / `ReplacingMergeTree`.

---

## Scope Check

The approved spec covers several related units: schema, config, AMiner clients, parsers, repository, recall, profile fetch, CLI, catalog files, and verification. They share one data model and one queue, so a single implementation plan is acceptable, but execution must be incremental. Each task below creates working, testable software and commits before moving to the next unit.

Approval-sensitive execution order:

```text
Task 1 -> Task 2 -> Task 3 -> Task 5 -> Task 6 -> Task 7 -> Task 8 build-review-csv path
  -> generate 20-person CSV review package
  -> stop for user review
  -> after explicit approval, execute Task 4 ClickHouse repository work
  -> finish Task 8 live commands, Task 9 docs, and Task 10 verification
```

Task 4 is listed near the schema work because it implements the ClickHouse writer for the same tables, but it must not be executed until after the CSV review package is approved.

## Files

Create:

- `src/aminer_builder/__init__.py`: package marker and version string.
- `src/aminer_builder/ids.py`: deterministic IDs for runs, responses, observations, facts, and queue rows.
- `src/aminer_builder/schema.py`: ClickHouse table definitions and SQL builders.
- `src/aminer_builder/config.py`: env config, catalog config parser, budget expansion, browser config.
- `src/aminer_builder/csv_review.py`: schema-ordered CSV preview writer used before ClickHouse writes are enabled.
- `src/aminer_builder/repository.py`: ClickHouse writes, queue state transitions, stale recovery, coverage insert.
- `src/aminer_builder/aminer_client.py`: AMiner rec5/public/paid HTTP client copied and narrowed from `talent_radar`.
- `src/aminer_builder/browser_client.py`: authenticated browser parsed snapshot wrapper, with strict snapshot-only storage.
- `src/aminer_builder/parsers.py`: rec5/public/browser payload normalizers to observation rows.
- `src/aminer_builder/recall.py`: topic recall service and person queue producer.
- `src/aminer_builder/profile_fetcher.py`: person profile endpoint fetcher and observation producer.
- `src/aminer_builder/coverage.py`: coverage summary builder.
- `src/aminer_builder/cli.py`: command-line entry points.
- `data/aminer_domains/catalog/global_academic_catalog.json`: broad catalog entry point.
- `data/aminer_domains/shards/ai_cs.json`: first full shard with existing high-priority CS/AI topics.
- `data/aminer_domains/shards/engineering.json`: broad engineering shard.
- `data/aminer_domains/shards/natural_science.json`: broad science shard.
- `data/aminer_domains/shards/life_medicine.json`: broad life/medicine shard.
- `data/aminer_domains/shards/social_science.json`: broad social science shard.
- `data/aminer_domains/shards/interdisciplinary.json`: broad interdisciplinary shard.
- `temp/fixtures/aminer_browser_siwei_lyu_snapshot.json`: sanitized browser parsed snapshot fixture copied from the workstation output.
- `temp/fixtures/aminer_rec5_robot_learning.json`: small deterministic rec5-like fixture.
- `temp/fixtures/aminer_public_summary_siwei_lyu.json`: small deterministic public summary fixture.
- `temp/test_aminer_builder_ids.py`
- `temp/test_aminer_builder_schema.py`
- `temp/test_aminer_builder_config.py`
- `temp/test_aminer_builder_csv_review.py`
- `temp/test_aminer_builder_parsers.py`
- `temp/test_aminer_builder_repository.py`
- `temp/test_aminer_builder_recall.py`
- `temp/test_aminer_builder_profile_fetcher.py`
- `temp/test_aminer_builder_cli.py`

Modify:

- `README.md`: add AMiner builder commands and instance-test section.
- `.env.example`: add AMiner builder env variables.

Do not modify:

- `src/cv_builder/*`, except by adding references in README if needed.
- `academic_cv` schema or tables.

## Validation Commands

Use these commands throughout unless a task gives a narrower command:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_ids.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_schema.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_config.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_csv_review.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_parsers.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_repository.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_recall.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_profile_fetcher.py -q
venv/bin/python3 -m pytest temp/test_aminer_builder_cli.py -q
```

If `venv` is unavailable, stop and ask whether to create it, matching `academic/AGENTS.md`.

---

### Task 1: Package, IDs, and Schema

**Files:**

- Create: `src/aminer_builder/__init__.py`
- Create: `src/aminer_builder/ids.py`
- Create: `src/aminer_builder/schema.py`
- Test: `temp/test_aminer_builder_ids.py`
- Test: `temp/test_aminer_builder_schema.py`

- [ ] **Step 1: Write failing ID tests**

Create `temp/test_aminer_builder_ids.py`:

```python
import pytest

from src.aminer_builder.ids import (
    make_fact_id,
    make_observation_id,
    make_response_id,
    make_run_id,
    normalize_aminer_person_id,
)


def test_normalize_aminer_person_id_accepts_profile_urls_and_raw_ids():
    assert normalize_aminer_person_id("53f4271edabfaeb22f3c93b8") == "53f4271edabfaeb22f3c93b8"
    assert (
        normalize_aminer_person_id("https://www.aminer.cn/profile/siwei-lyu/53f4271edabfaeb22f3c93b8")
        == "53f4271edabfaeb22f3c93b8"
    )


def test_normalize_aminer_person_id_rejects_blank_values():
    assert normalize_aminer_person_id("") == ""
    assert normalize_aminer_person_id(None) == ""


def test_stable_ids_are_deterministic_and_prefixed():
    assert make_run_id("catalog", "global", "2026-06-17").startswith("amrun_")
    assert make_response_id("run-1", "rec5", "robot learning", "paper-1").startswith("amresp_")
    assert make_observation_id("paper", "run-1", "topic", "paper-1").startswith("amobs_")
    assert make_fact_id("person-1", "education", "summary.edu[0]", "PhD").startswith("amfact_")
    assert make_response_id("run-1", "rec5", "robot learning", "paper-1") == make_response_id(
        "run-1", "rec5", "robot learning", "paper-1"
    )


def test_make_run_id_requires_non_empty_parts():
    with pytest.raises(ValueError):
        make_run_id("", "global")
```

- [ ] **Step 2: Write failing schema tests**

Create `temp/test_aminer_builder_schema.py`:

```python
import pytest

from src.aminer_builder.schema import (
    AMINER_TABLES,
    build_create_database_sql,
    build_create_table_sql,
    quote_identifier,
)


def test_aminer_schema_has_required_tables():
    assert set(AMINER_TABLES) == {
        "aminer_fetch_runs",
        "aminer_person_fetch_queue",
        "aminer_raw_responses",
        "aminer_recalled_paper_observations",
        "aminer_paper_author_observations",
        "aminer_person_observations",
        "aminer_publication_observations",
        "aminer_profile_fact_observations",
        "aminer_run_coverage_reports",
    }


def test_raw_responses_schema_preserves_payload_json_with_merge_tree():
    sql = build_create_table_sql("academic_aminer", "aminer_raw_responses")
    assert "payload_json String" in sql
    assert "payload_sha1 String" in sql
    assert "endpoint String" in sql
    assert "ENGINE = MergeTree" in sql
    assert "ORDER BY (run_id, endpoint, fetched_at, response_id)" in sql


def test_queue_schema_uses_replacing_merge_tree_for_status_updates():
    sql = build_create_table_sql("academic_aminer", "aminer_person_fetch_queue")
    assert "aminer_person_id String" in sql
    assert "profile_status_json String" in sql
    assert "ENGINE = ReplacingMergeTree(updated_at)" in sql
    assert "ORDER BY (run_id, aminer_person_id)" in sql


def test_fact_schema_carries_source_path_and_review_flag():
    sql = build_create_table_sql("academic_aminer", "aminer_profile_fact_observations")
    assert "source_path String" in sql
    assert "extraction_method String" in sql
    assert "needs_human_review UInt8" in sql


def test_create_database_sql_quotes_identifier():
    assert build_create_database_sql("academic_aminer") == "CREATE DATABASE IF NOT EXISTS `academic_aminer`"


def test_invalid_identifiers_are_rejected():
    with pytest.raises(ValueError):
        quote_identifier("bad-name")
    with pytest.raises(ValueError):
        build_create_table_sql("academic-aminer", "aminer_raw_responses")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_ids.py temp/test_aminer_builder_schema.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.aminer_builder'`.

- [ ] **Step 4: Implement package and ID helpers**

Create `src/aminer_builder/__init__.py`:

```python
"""AMiner catalog data capture package."""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
```

Create `src/aminer_builder/ids.py`:

```python
"""Stable IDs and AMiner identifier normalization."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit


_AMINER_PERSON_ID_RE = re.compile(r"^[0-9a-f]{16,32}$", re.IGNORECASE)


def clean_text(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def normalize_aminer_person_id(value) -> str:
    text = clean_text(value).strip("/")
    if not text:
        return ""
    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    candidate = path.rstrip("/").rsplit("/", 1)[-1]
    candidate = candidate.split("?", 1)[0].split("#", 1)[0].strip()
    if _AMINER_PERSON_ID_RE.fullmatch(candidate):
        return candidate.lower()
    return ""


def _normalize_part(value) -> str:
    if value is None:
        return ""
    return clean_text(value).lower()


def _stable_id(prefix: str, *parts) -> str:
    normalized = [_normalize_part(part) for part in parts]
    if not any(normalized):
        raise ValueError("at least one non-empty ID part is required")
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def make_run_id(*parts) -> str:
    return _stable_id("amrun", *parts)


def make_response_id(*parts) -> str:
    return _stable_id("amresp", *parts)


def make_observation_id(*parts) -> str:
    return _stable_id("amobs", *parts)


def make_fact_id(*parts) -> str:
    return _stable_id("amfact", *parts)
```

- [ ] **Step 5: Implement schema helpers**

Create `src/aminer_builder/schema.py`:

```python
"""ClickHouse schema definitions for AMiner catalog capture."""

from __future__ import annotations

import re


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


AMINER_TABLES = {
    "aminer_fetch_runs": {
        "columns": [
            ("run_id", "String"),
            ("parent_run_id", "String"),
            ("run_scope", "String"),
            ("catalog_key", "String"),
            ("catalog_version", "String"),
            ("shard_key", "String"),
            ("topic_group_key", "String"),
            ("topic", "String"),
            ("domain_key", "String"),
            ("domain_label", "String"),
            ("budget_name", "String"),
            ("config_path", "String"),
            ("config_json", "String"),
            ("status", "String"),
            ("started_at", "DateTime"),
            ("finished_at", "Nullable(DateTime)"),
            ("error_summary", "String"),
        ],
        "engine": "ReplacingMergeTree(started_at)",
        "order_by": "(run_id)",
    },
    "aminer_person_fetch_queue": {
        "columns": [
            ("aminer_person_id", "String"),
            ("run_id", "String"),
            ("seed_type", "String"),
            ("seed_value", "String"),
            ("name", "String"),
            ("profile_url", "String"),
            ("topic", "String"),
            ("paper_id", "String"),
            ("paper_title", "String"),
            ("author_position", "Nullable(UInt16)"),
            ("priority", "UInt16"),
            ("status", "String"),
            ("retry_count", "UInt16"),
            ("last_error", "String"),
            ("profile_status_json", "String"),
            ("created_at", "DateTime"),
            ("updated_at", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(updated_at)",
        "order_by": "(run_id, aminer_person_id)",
    },
    "aminer_raw_responses": {
        "columns": [
            ("response_id", "String"),
            ("run_id", "String"),
            ("endpoint", "String"),
            ("aminer_person_id", "String"),
            ("aminer_paper_id", "String"),
            ("query_text", "String"),
            ("source_url", "String"),
            ("request_params_json", "String"),
            ("payload_json", "String"),
            ("payload_sha1", "String"),
            ("http_status", "Nullable(UInt16)"),
            ("status", "String"),
            ("parser_version", "String"),
            ("fetched_at", "DateTime"),
            ("error", "String"),
        ],
        "engine": "MergeTree",
        "order_by": "(run_id, endpoint, fetched_at, response_id)",
    },
    "aminer_recalled_paper_observations": {
        "columns": [
            ("observation_id", "String"),
            ("response_id", "String"),
            ("run_id", "String"),
            ("catalog_key", "String"),
            ("shard_key", "String"),
            ("topic_group_key", "String"),
            ("domain_key", "String"),
            ("topic", "String"),
            ("paper_id", "String"),
            ("title", "String"),
            ("year", "Nullable(UInt16)"),
            ("venue", "String"),
            ("citation_count", "Nullable(UInt32)"),
            ("url", "String"),
            ("authors_json", "String"),
            ("topics_json", "String"),
            ("observed_at", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(observed_at)",
        "order_by": "(run_id, topic, paper_id, observation_id)",
    },
    "aminer_paper_author_observations": {
        "columns": [
            ("observation_id", "String"),
            ("response_id", "String"),
            ("run_id", "String"),
            ("catalog_key", "String"),
            ("shard_key", "String"),
            ("topic_group_key", "String"),
            ("domain_key", "String"),
            ("topic", "String"),
            ("paper_id", "String"),
            ("paper_title", "String"),
            ("author_name", "String"),
            ("author_position", "Nullable(UInt16)"),
            ("author_count", "Nullable(UInt16)"),
            ("aminer_person_id", "String"),
            ("affiliation", "String"),
            ("profile_url", "String"),
            ("source_path", "String"),
            ("observed_at", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(observed_at)",
        "order_by": "(run_id, topic, paper_id, author_position, aminer_person_id, observation_id)",
    },
    "aminer_person_observations": {
        "columns": [
            ("observation_id", "String"),
            ("response_id", "String"),
            ("run_id", "String"),
            ("aminer_person_id", "String"),
            ("name", "String"),
            ("name_zh", "String"),
            ("org", "String"),
            ("position", "String"),
            ("homepage", "String"),
            ("bio", "String"),
            ("h_index", "Nullable(UInt32)"),
            ("g_index", "Nullable(UInt32)"),
            ("num_pubs", "Nullable(UInt32)"),
            ("num_citation", "Nullable(UInt32)"),
            ("interests_json", "String"),
            ("source_endpoint", "String"),
            ("source_url", "String"),
            ("observed_at", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(observed_at)",
        "order_by": "(aminer_person_id, source_endpoint, response_id, observation_id)",
    },
    "aminer_publication_observations": {
        "columns": [
            ("observation_id", "String"),
            ("response_id", "String"),
            ("run_id", "String"),
            ("aminer_person_id", "String"),
            ("paper_id", "String"),
            ("title", "String"),
            ("venue", "String"),
            ("year", "Nullable(UInt16)"),
            ("citation_count", "Nullable(UInt32)"),
            ("url", "String"),
            ("authors_json", "String"),
            ("source_endpoint", "String"),
            ("source_url", "String"),
            ("observed_at", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(observed_at)",
        "order_by": "(aminer_person_id, paper_id, source_endpoint, observation_id)",
    },
    "aminer_profile_fact_observations": {
        "columns": [
            ("fact_id", "String"),
            ("response_id", "String"),
            ("run_id", "String"),
            ("aminer_person_id", "String"),
            ("fact_type", "String"),
            ("raw_text", "String"),
            ("normalized_label", "String"),
            ("source_path", "String"),
            ("extraction_method", "String"),
            ("confidence", "Nullable(Float32)"),
            ("source_url", "String"),
            ("needs_human_review", "UInt8"),
            ("observed_at", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(observed_at)",
        "order_by": "(aminer_person_id, fact_type, source_path, fact_id)",
    },
    "aminer_run_coverage_reports": {
        "columns": [
            ("report_id", "String"),
            ("run_id", "String"),
            ("catalog_key", "String"),
            ("shard_key", "String"),
            ("topic_group_key", "String"),
            ("summary_json", "String"),
            ("generated_at", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(generated_at)",
        "order_by": "(run_id, report_id)",
    },
}


def quote_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Invalid ClickHouse identifier: {identifier!r}")
    return f"`{identifier}`"


def build_create_database_sql(database: str) -> str:
    return f"CREATE DATABASE IF NOT EXISTS {quote_identifier(database)}"


def build_create_table_sql(database: str, table: str) -> str:
    if table not in AMINER_TABLES:
        quote_identifier(table)
        raise ValueError(f"Unknown AMiner table: {table!r}")
    schema = AMINER_TABLES[table]
    columns_sql = ",\n    ".join(f"{name} {kind}" for name, kind in schema["columns"])
    return f"""
CREATE TABLE IF NOT EXISTS {quote_identifier(database)}.{quote_identifier(table)}
(
    {columns_sql}
)
ENGINE = {schema["engine"]}
ORDER BY {schema["order_by"]}
""".strip()
```

- [ ] **Step 6: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_ids.py temp/test_aminer_builder_schema.py -q
```

Expected: all tests PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/aminer_builder/__init__.py src/aminer_builder/ids.py src/aminer_builder/schema.py temp/test_aminer_builder_ids.py temp/test_aminer_builder_schema.py
git commit -m "feat: add aminer builder schema"
```

---

### Task 2: Config Loader and Catalog Files

**Files:**

- Create: `src/aminer_builder/config.py`
- Create: `data/aminer_domains/catalog/global_academic_catalog.json`
- Create: `data/aminer_domains/shards/ai_cs.json`
- Create: `data/aminer_domains/shards/engineering.json`
- Create: `data/aminer_domains/shards/natural_science.json`
- Create: `data/aminer_domains/shards/life_medicine.json`
- Create: `data/aminer_domains/shards/social_science.json`
- Create: `data/aminer_domains/shards/interdisciplinary.json`
- Test: `temp/test_aminer_builder_config.py`

- [ ] **Step 1: Write failing config tests**

Create `temp/test_aminer_builder_config.py`:

```python
import json
from pathlib import Path

import pytest

from src.aminer_builder.config import (
    AMinerBuilderConfig,
    expand_catalog_topics,
    get_config,
    load_catalog,
    load_shard,
)


def test_get_config_uses_env_and_defaults(monkeypatch):
    monkeypatch.setenv("AMINER_DATABASE", "aminer_test")
    monkeypatch.setenv("AMINER_API_TOKEN", "token-1")
    monkeypatch.setenv("AMINER_BROWSER_PROFILE_DIR", ".auth/aminer/chrome_profile")

    config = get_config(load_dotenv=False)

    assert config.aminer_database == "aminer_test"
    assert config.aminer_api_token == "token-1"
    assert config.browser_profile_dir == Path(".auth/aminer/chrome_profile")
    assert config.public_profile_base_url == "https://api.aminer.cn/api"


def test_load_catalog_resolves_shards_relative_to_catalog(tmp_path):
    root = tmp_path / "data" / "aminer_domains"
    (root / "catalog").mkdir(parents=True)
    (root / "shards").mkdir()
    shard = root / "shards" / "ai_cs.json"
    shard.write_text(
        json.dumps(
            {
                "shard_key": "ai_cs",
                "shard_label": "AI and Computer Science",
                "topic_groups": [{"group_key": "ml", "priority": 1, "topics": ["machine learning"]}],
            }
        ),
        encoding="utf-8",
    )
    catalog_path = root / "catalog" / "global.json"
    catalog_path.write_text(
        json.dumps(
            {
                "catalog_key": "global",
                "catalog_label": "Global",
                "catalog_version": "2026-06-17",
                "default_budget": "pilot",
                "budgets": {"pilot": {"papers_per_topic": 2, "max_topics_per_shard": 10, "max_people_per_shard": 20}},
                "rate_limits": {"rec5_sleep_seconds": 0.1},
                "profile_enrichment": {"profile_depth": "full-with-browser"},
                "identity_policy": {"require_aminer_author_id_for_profile_fetch": True},
                "shards": ["../shards/ai_cs.json"],
            }
        ),
        encoding="utf-8",
    )

    catalog = load_catalog(catalog_path)

    assert catalog.catalog_key == "global"
    assert catalog.shard_paths == [shard]
    assert catalog.budgets["pilot"]["papers_per_topic"] == 2


def test_expand_catalog_topics_respects_budget_and_group_filter(tmp_path):
    shard_path = tmp_path / "ai_cs.json"
    shard_path.write_text(
        json.dumps(
            {
                "shard_key": "ai_cs",
                "shard_label": "AI and Computer Science",
                "topic_groups": [
                    {"group_key": "ml", "priority": 2, "topics": ["machine learning", "deep learning"]},
                    {"group_key": "nlp", "priority": 1, "topics": ["large language models"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    shard = load_shard(shard_path)
    topics = expand_catalog_topics(
        catalog_key="global",
        catalog_version="v1",
        shard=shard,
        budget={"papers_per_topic": 5, "max_topics_per_shard": 2, "max_people_per_shard": 100},
        group_key="nlp",
    )

    assert [topic.query for topic in topics] == ["large language models"]
    assert topics[0].papers_per_topic == 5
    assert topics[0].shard_key == "ai_cs"


def test_load_shard_rejects_empty_topic_groups(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"shard_key": "bad", "shard_label": "Bad", "topic_groups": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="topic_groups"):
        load_shard(path)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_config.py -q
```

Expected: FAIL because `src.aminer_builder.config` is missing.

- [ ] **Step 3: Implement config loader**

Create `src/aminer_builder/config.py`:

```python
"""Configuration and catalog loading for AMiner builder."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AMinerBuilderConfig:
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_database: str
    clickhouse_user: str
    clickhouse_password: str
    aminer_database: str
    aminer_api_token: str
    aminer_api_base_url: str
    public_profile_base_url: str
    browser_profile_dir: Path
    request_timeout: float


@dataclass(frozen=True)
class CatalogConfig:
    path: Path
    catalog_key: str
    catalog_label: str
    catalog_version: str
    default_budget: str
    budgets: dict[str, dict[str, Any]]
    rate_limits: dict[str, Any]
    profile_enrichment: dict[str, Any]
    identity_policy: dict[str, Any]
    shard_paths: list[Path]
    raw: dict[str, Any]


@dataclass(frozen=True)
class ShardConfig:
    path: Path
    shard_key: str
    shard_label: str
    topic_groups: list[dict[str, Any]]
    raw: dict[str, Any]


@dataclass(frozen=True)
class TopicSpec:
    catalog_key: str
    catalog_version: str
    shard_key: str
    topic_group_key: str
    topic_group_priority: int
    query: str
    papers_per_topic: int
    max_people_per_shard: int


def _get_int_env(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer, got {raw!r}") from exc


def _get_float_env(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number, got {raw!r}") from exc


def load_env_file(path: Path | None = None) -> None:
    env_path = path or Path(os.environ.get("AMINER_BUILDER_ENV_FILE", ".env"))
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def get_config(load_dotenv: bool = True, env_file: Path | None = None) -> AMinerBuilderConfig:
    if load_dotenv:
        load_env_file(env_file)
    token = os.environ.get("AMINER_API_TOKEN") or os.environ.get("AMINER_API_KEY", "")
    return AMinerBuilderConfig(
        clickhouse_host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        clickhouse_port=_get_int_env("CLICKHOUSE_PORT", 8123),
        clickhouse_database=os.environ.get("CLICKHOUSE_DATABASE", "academic_db"),
        clickhouse_user=os.environ.get("CLICKHOUSE_USER", "default"),
        clickhouse_password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        aminer_database=os.environ.get("AMINER_DATABASE", "academic_aminer"),
        aminer_api_token=token,
        aminer_api_base_url=os.environ.get("AMINER_API_BASE_URL", "https://datacenter.aminer.cn/gateway/open_platform"),
        public_profile_base_url=os.environ.get("AMINER_PUBLIC_PROFILE_BASE_URL", "https://api.aminer.cn/api"),
        browser_profile_dir=Path(os.environ.get("AMINER_BROWSER_PROFILE_DIR", ".auth/aminer/chrome_profile")),
        request_timeout=_get_float_env("AMINER_BUILDER_REQUEST_TIMEOUT", 30.0),
    )


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_catalog(path: str | Path) -> CatalogConfig:
    catalog_path = Path(path)
    raw = _read_json(catalog_path)
    shard_paths = []
    for value in raw.get("shards") or []:
        shard_path = Path(value)
        if not shard_path.is_absolute():
            shard_path = (catalog_path.parent / shard_path).resolve()
        shard_paths.append(shard_path)
    if not shard_paths:
        raise ValueError("catalog must define at least one shard")
    budgets = raw.get("budgets") or {}
    if not isinstance(budgets, dict) or not budgets:
        raise ValueError("catalog budgets must be a non-empty object")
    return CatalogConfig(
        path=catalog_path,
        catalog_key=str(raw.get("catalog_key") or ""),
        catalog_label=str(raw.get("catalog_label") or ""),
        catalog_version=str(raw.get("catalog_version") or ""),
        default_budget=str(raw.get("default_budget") or "pilot"),
        budgets=budgets,
        rate_limits=raw.get("rate_limits") if isinstance(raw.get("rate_limits"), dict) else {},
        profile_enrichment=raw.get("profile_enrichment") if isinstance(raw.get("profile_enrichment"), dict) else {},
        identity_policy=raw.get("identity_policy") if isinstance(raw.get("identity_policy"), dict) else {},
        shard_paths=shard_paths,
        raw=raw,
    )


def load_shard(path: str | Path) -> ShardConfig:
    shard_path = Path(path)
    raw = _read_json(shard_path)
    groups = raw.get("topic_groups") or []
    if not isinstance(groups, list) or not groups:
        raise ValueError("shard topic_groups must be a non-empty list")
    return ShardConfig(
        path=shard_path,
        shard_key=str(raw.get("shard_key") or ""),
        shard_label=str(raw.get("shard_label") or ""),
        topic_groups=groups,
        raw=raw,
    )


def expand_catalog_topics(
    *,
    catalog_key: str,
    catalog_version: str,
    shard: ShardConfig,
    budget: dict[str, Any],
    group_key: str = "",
) -> list[TopicSpec]:
    max_topics = int(budget.get("max_topics_per_shard") or 0)
    papers_per_topic = int(budget.get("papers_per_topic") or 20)
    max_people = int(budget.get("max_people_per_shard") or 1000)
    groups = sorted(shard.topic_groups, key=lambda item: int(item.get("priority") or 999))
    topics: list[TopicSpec] = []
    for group in groups:
        current_group_key = str(group.get("group_key") or "")
        if group_key and current_group_key != group_key:
            continue
        for query in group.get("topics") or []:
            text = str(query).strip()
            if not text:
                continue
            topics.append(
                TopicSpec(
                    catalog_key=catalog_key,
                    catalog_version=catalog_version,
                    shard_key=shard.shard_key,
                    topic_group_key=current_group_key,
                    topic_group_priority=int(group.get("priority") or 999),
                    query=text,
                    papers_per_topic=papers_per_topic,
                    max_people_per_shard=max_people,
                )
            )
            if max_topics and len(topics) >= max_topics:
                return topics
    return topics
```

- [ ] **Step 4: Add catalog and shard files**

Create the catalog and shard files exactly at the paths listed in this task. Include the approved budget, rate limit, profile, and identity policy keys in `global_academic_catalog.json`. Each shard must include at least these concrete topic groups:

```text
ai_cs: machine_learning, natural_language_processing, computer_vision, robotics, information_retrieval, data_mining_recommender, databases, hci, cyber_security, software_engineering, systems_networks, theory_visualization
engineering: electrical_engineering, control_signal_processing, communications, mechanical_manufacturing, civil_transportation, aerospace_energy, materials_engineering
natural_science: mathematics_statistics, physics_astronomy, chemistry_materials, earth_environment_climate
life_medicine: biology_genomics, bioinformatics, neuroscience, medicine_public_health, pharmacology_biomedical_engineering
social_science: economics_finance, management, psychology_education, sociology_political_science, law_communication
interdisciplinary: ai4science, computational_social_science, digital_humanities, climate_ai, smart_cities, human_centered_ai, data_science
```

Use topic strings from the approved spec plus the existing `talent_radar/knowledge/domain_filters/*.json` terms for high-priority groups.

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_config.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/aminer_builder/config.py data/aminer_domains temp/test_aminer_builder_config.py
git commit -m "feat: add aminer catalog config"
```

---

### Task 3: CSV Review Gate Before ClickHouse Writes

**Files:**

- Create: `src/aminer_builder/csv_review.py`
- Test: `temp/test_aminer_builder_csv_review.py`

This task is a hard implementation gate. Do not implement live ClickHouse insert behavior until this task exists and the 20-person CSV review package can be generated for user review.

- [ ] **Step 1: Write failing CSV review tests**

Create `temp/test_aminer_builder_csv_review.py`:

```python
import csv
import json
from pathlib import Path

from src.aminer_builder.csv_review import build_csv_rows_for_table, write_review_csv_package
from src.aminer_builder.schema import AMINER_TABLES


def test_build_csv_rows_uses_schema_column_order_and_json_serializes_nested_values():
    rows = build_csv_rows_for_table(
        "aminer_raw_responses",
        [
            {
                "response_id": "resp-1",
                "run_id": "run-1",
                "endpoint": "rec5",
                "request_params_json": {"topics": ["robot learning"]},
                "payload_json": {"data": [{"papers": []}]},
                "http_status": None,
            }
        ],
    )

    expected_columns = [name for name, _ in AMINER_TABLES["aminer_raw_responses"]["columns"]]
    assert rows["fieldnames"] == expected_columns
    assert rows["rows"][0][0] == "resp-1"
    assert rows["rows"][0][7] == '{"topics":["robot learning"]}'
    assert rows["rows"][0][8] == '{"data":[{"papers":[]}]}'
    assert rows["rows"][0][10] == ""


def test_write_review_csv_package_writes_all_target_tables(tmp_path):
    output_dir = tmp_path / "review"
    written = write_review_csv_package(
        output_dir,
        {
            "aminer_person_observations": [
                {
                    "observation_id": "obs-1",
                    "response_id": "resp-1",
                    "run_id": "run-1",
                    "aminer_person_id": "53f4271edabfaeb22f3c93b8",
                    "name": "Siwei Lyu",
                }
            ],
            "aminer_profile_fact_observations": [
                {
                    "fact_id": "fact-1",
                    "response_id": "resp-1",
                    "run_id": "run-1",
                    "aminer_person_id": "53f4271edabfaeb22f3c93b8",
                    "fact_type": "education",
                    "raw_text": "Ph.D, Dartmouth College",
                }
            ],
        },
    )

    assert output_dir.joinpath("aminer_person_observations.csv").exists()
    assert output_dir.joinpath("aminer_profile_fact_observations.csv").exists()
    assert written["aminer_person_observations"] == 1
    with output_dir.joinpath("aminer_person_observations.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
    assert row["aminer_person_id"] == "53f4271edabfaeb22f3c93b8"
    assert row["name"] == "Siwei Lyu"


def test_review_package_rejects_unknown_tables(tmp_path):
    try:
        write_review_csv_package(tmp_path, {"not_a_table": []})
    except ValueError as exc:
        assert "Unknown AMiner table" in str(exc)
    else:
        raise AssertionError("unknown table should be rejected")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_csv_review.py -q
```

Expected: FAIL because `src.aminer_builder.csv_review` is missing.

- [ ] **Step 3: Implement schema-ordered CSV preview writer**

Create `src/aminer_builder/csv_review.py`:

```python
"""CSV review package writer used before enabling ClickHouse writes."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from src.aminer_builder.schema import AMINER_TABLES


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def build_csv_rows_for_table(table: str, rows: list[dict]) -> dict:
    if table not in AMINER_TABLES:
        raise ValueError(f"Unknown AMiner table: {table!r}")
    fieldnames = [name for name, _ in AMINER_TABLES[table]["columns"]]
    csv_rows = []
    for row in rows:
        csv_rows.append([_csv_value(row.get(column)) for column in fieldnames])
    return {"fieldnames": fieldnames, "rows": csv_rows}


def write_review_csv_package(output_dir: str | Path, table_rows: dict[str, list[dict]]) -> dict[str, int]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}
    for table, rows in table_rows.items():
        built = build_csv_rows_for_table(table, rows)
        path = out / f"{table}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(built["fieldnames"])
            writer.writerows(built["rows"])
        written[table] = len(rows)
    return written
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_csv_review.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Run fixed 20-person CSV instance package at the review gate**

When execution reaches the review gate described in the approval-sensitive execution order, run the review package command before live ClickHouse writes:

```bash
venv/bin/python3 -m src.aminer_builder.cli build-review-csv \
  --catalog data/aminer_domains/catalog/global_academic_catalog.json \
  --shard ai_cs \
  --group natural_language_processing \
  --people-limit 20 \
  --output-dir output/aminer_builder_review
```

Expected output:

```text
review CSV package written to output/aminer_builder_review/<run_id>
```

Expected files:

```text
aminer_raw_responses.csv
aminer_recalled_paper_observations.csv
aminer_paper_author_observations.csv
aminer_person_observations.csv
aminer_publication_observations.csv
aminer_profile_fact_observations.csv
aminer_person_fetch_queue.csv
aminer_run_coverage_reports.csv
```

Stop after this command and ask the user to review the CSV files. Do not proceed to live ClickHouse insert implementation until the user explicitly approves the review package.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/aminer_builder/csv_review.py temp/test_aminer_builder_csv_review.py
git commit -m "feat: add aminer csv review gate"
```

---

### Task 4: Repository and Queue State

**Files:**

- Create: `src/aminer_builder/repository.py`
- Test: `temp/test_aminer_builder_repository.py`

Start this task only after the user has approved the 20-person CSV review package from Task 3. The repository implements live ClickHouse writes, so it is intentionally placed after the CSV review gate.

- [ ] **Step 1: Write failing repository tests**

Create `temp/test_aminer_builder_repository.py`:

```python
from datetime import datetime, timedelta

from src.aminer_builder.config import AMinerBuilderConfig
from src.aminer_builder.repository import AMinerRepository, table_name
from src.aminer_builder.schema import AMINER_TABLES, build_create_database_sql, build_create_table_sql


class FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class FakeClient:
    def __init__(self, query_results=None):
        self.commands = []
        self.inserts = []
        self.queries = []
        self.query_results = list(query_results or [])

    def command(self, sql):
        self.commands.append(sql)

    def insert(self, table, values, column_names=None):
        self.inserts.append({"table": table, "values": values, "column_names": column_names})

    def query(self, sql, parameters=None):
        self.queries.append({"sql": sql, "parameters": parameters or {}})
        if self.query_results:
            return self.query_results.pop(0)
        return FakeResult([])


def make_config():
    return AMinerBuilderConfig(
        clickhouse_host="clickhouse.local",
        clickhouse_port=8123,
        clickhouse_database="academic_db",
        clickhouse_user="default",
        clickhouse_password="",
        aminer_database="academic_aminer",
        aminer_api_token="token",
        aminer_api_base_url="https://datacenter.aminer.cn/gateway/open_platform",
        public_profile_base_url="https://api.aminer.cn/api",
        browser_profile_dir=__import__("pathlib").Path(".auth/aminer/chrome_profile"),
        request_timeout=30.0,
    )


def make_repository(client):
    repository = object.__new__(AMinerRepository)
    repository.config = make_config()
    repository.client = client
    return repository


def test_table_name_quotes_identifiers():
    assert table_name("academic_aminer", "aminer_raw_responses") == "`academic_aminer`.`aminer_raw_responses`"


def test_init_schema_creates_database_and_all_tables():
    client = FakeClient()
    repo = make_repository(client)

    repo.init_schema()

    assert client.commands[0] == build_create_database_sql("academic_aminer")
    for table in AMINER_TABLES:
        assert build_create_table_sql("academic_aminer", table) in client.commands


def test_insert_rows_uses_schema_order_and_defaults():
    client = FakeClient()
    repo = make_repository(client)

    repo.insert_rows("aminer_person_observations", [{"observation_id": "o1", "aminer_person_id": "p1"}])

    insert = client.inserts[0]
    assert insert["table"] == "`academic_aminer`.`aminer_person_observations`"
    assert insert["column_names"][0] == "observation_id"
    assert insert["values"][0][0] == "o1"
    assert insert["values"][0][3] == "p1"


def test_enqueue_people_dedupes_existing_queue_rows():
    client = FakeClient(query_results=[FakeResult([("p1",)])])
    repo = make_repository(client)

    inserted = repo.enqueue_people(
        run_id="run-1",
        rows=[
            {"aminer_person_id": "p1", "name": "Existing"},
            {"aminer_person_id": "p2", "name": "New", "topic": "robot learning", "paper_id": "paper-1"},
        ],
    )

    assert inserted == 1
    assert client.inserts[0]["table"] == "`academic_aminer`.`aminer_person_fetch_queue`"
    assert client.inserts[0]["values"][0][0] == "p2"


def test_next_pending_person_marks_processing():
    client = FakeClient(query_results=[FakeResult([("p2", "run-1", 1)])])
    repo = make_repository(client)

    row = repo.next_pending_person()

    assert row == {"aminer_person_id": "p2", "run_id": "run-1", "retry_count": 1}
    assert client.inserts[0]["values"][0][11] == "processing"


def test_recover_stale_processing_requeues_rows_without_retry_increment():
    stale = datetime.now() - timedelta(hours=7)
    client = FakeClient(query_results=[FakeResult([("p1", "run-1", 2, stale)])])
    repo = make_repository(client)

    recovered = repo.recover_stale_processing(older_than_hours=6)

    assert recovered == 1
    values = client.inserts[0]["values"][0]
    assert values[0] == "p1"
    assert values[11] == "pending"
    assert values[12] == 2
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_repository.py -q
```

Expected: FAIL because `src.aminer_builder.repository` is missing.

- [ ] **Step 3: Implement repository**

Create `src/aminer_builder/repository.py` with:

- `table_name(database, table)`
- `AMinerRepository.__init__` using `clickhouse_connect.get_client`
- `init_schema()`
- `insert_rows(table, rows)`
- `insert_raw_response(row)`
- `insert_observations(table, rows)`
- `enqueue_people(run_id, rows)`
- `next_pending_person()`
- `mark_person_done(aminer_person_id, run_id, profile_status)`
- `mark_person_failed(aminer_person_id, run_id, error)`
- `recover_stale_processing(older_than_hours)`

Use `src.cv_builder.repository` as the implementation pattern for defaults and safe table names. `_default_for_clickhouse_type` must return `None` for `Nullable(...)`, `datetime.now()` for `DateTime`, `0` for `UInt`, `0.0` for `Float`, and `""` otherwise.

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_repository.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/aminer_builder/repository.py temp/test_aminer_builder_repository.py
git commit -m "feat: add aminer repository queue"
```

---

### Task 5: Parsers and Fixtures

**Files:**

- Create: `src/aminer_builder/parsers.py`
- Create: `temp/fixtures/aminer_rec5_robot_learning.json`
- Create: `temp/fixtures/aminer_public_summary_siwei_lyu.json`
- Create: `temp/fixtures/aminer_browser_siwei_lyu_snapshot.json`
- Test: `temp/test_aminer_builder_parsers.py`

- [ ] **Step 1: Add fixture files**

Create `temp/fixtures/aminer_rec5_robot_learning.json`:

```json
{
  "data": [
    {
      "papers": [
        {
          "paper_id": "rec5-p1",
          "title": "Robot Learning for Generalist Manipulation",
          "year": 2026,
          "venue": "CoRL",
          "num_citation": 12,
          "authors": ["Ada Scholar", "Grace Scientist"],
          "aminer_author_profiles": [
            {
              "name": "Ada Scholar",
              "author_id": "53f4271edabfaeb22f3c93b8",
              "affiliation": "Example University",
              "profile_url": "https://www.aminer.cn/profile/ada-scholar/53f4271edabfaeb22f3c93b8"
            },
            {
              "name": "Grace Scientist",
              "affiliation": "Example Institute"
            }
          ],
          "links": {"aminer": "https://www.aminer.cn/pub/rec5-p1"}
        }
      ]
    }
  ]
}
```

Create `temp/fixtures/aminer_public_summary_siwei_lyu.json`:

```json
{
  "id": "53f4271edabfaeb22f3c93b8",
  "name": "Siwei Lyu",
  "name_zh": "呂思偉",
  "aff": {"desc": "University at Buffalo"},
  "pos": [{"n": "Distinguished Professor"}],
  "contact": {
    "homepage": "https://cse.buffalo.edu/~siweilyu/",
    "bio": "Researcher in media forensics.",
    "edu": "2001-2005 Dartmouth College Ph.D, Computer Science",
    "work": "University at Buffalo"
  },
  "indices": {"h_index": 73, "g_index": 100, "num_pubs": 350, "num_citation": 25000},
  "tags": [{"t": "Computer Vision"}, {"t": "Multimedia Forensics"}]
}
```

Create `temp/fixtures/aminer_browser_siwei_lyu_snapshot.json` by copying the existing parsed snapshot shape, reduced to these fields:

```json
{
  "source": "aminer_browser_context",
  "source_type": "aminer_browser_profile",
  "source_url": "https://www.aminer.cn/profile/siwei-lyu/53f4271edabfaeb22f3c93b8",
  "status": "parsed",
  "document_type": "browser_dom",
  "text_chars": 10089,
  "locked_or_login_prompt": false,
  "logged_in_likely": true,
  "education": [
    {
      "kind": "education",
      "label": "2001-2005 Dartmouth College Ph.D, Computer Science",
      "evidence_quote": "2001-2005 Dartmouth College Ph.D, Computer Science",
      "extraction_method": "aminer_browser_text_section",
      "confidence": 0.74
    }
  ],
  "education_raw": "2001-2005 Dartmouth College Ph.D, Computer Science",
  "paper_titles": ["Robot Learning for Generalist Manipulation"],
  "paper_links": ["https://www.aminer.cn/pub/rec5-p1"],
  "links": ["https://cse.buffalo.edu/~siweilyu/"],
  "summary": "education=1; paper_titles=1; paper_links=1; login_prompt=False",
  "requested_url": "https://www.aminer.cn/profile/siwei-lyu/53f4271edabfaeb22f3c93b8",
  "final_url": "https://www.aminer.cn/profile/siwei-lyu/53f4271edabfaeb22f3c93b8",
  "title": "Siwei Lyu | AMiner",
  "http_status": 200,
  "error": "",
  "local_storage_key_count": 15,
  "session_storage_key_count": 4,
  "elapsed_seconds": 18.002
}
```

- [ ] **Step 2: Write failing parser tests**

Create `temp/test_aminer_builder_parsers.py`:

```python
import json
from pathlib import Path

from src.aminer_builder.parsers import (
    browser_snapshot_to_facts,
    public_summary_to_observations,
    rec5_payload_to_observations,
)


FIXTURES = Path("temp/fixtures")


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_rec5_payload_to_observations_extracts_paper_author_anchor_and_queue_seed():
    payload = load_fixture("aminer_rec5_robot_learning.json")

    papers, authors, queue_rows = rec5_payload_to_observations(
        payload,
        run_id="run-1",
        response_id="resp-1",
        catalog_key="global",
        shard_key="ai_cs",
        topic_group_key="robotics",
        domain_key="robotics",
        topic="robot learning",
    )

    assert papers[0]["paper_id"] == "rec5-p1"
    assert papers[0]["title"] == "Robot Learning for Generalist Manipulation"
    assert len(authors) == 2
    assert authors[0]["aminer_person_id"] == "53f4271edabfaeb22f3c93b8"
    assert authors[0]["author_position"] == 1
    assert authors[1]["aminer_person_id"] == ""
    assert queue_rows == [
        {
            "aminer_person_id": "53f4271edabfaeb22f3c93b8",
            "name": "Ada Scholar",
            "profile_url": "https://www.aminer.cn/profile/ada-scholar/53f4271edabfaeb22f3c93b8",
            "topic": "robot learning",
            "paper_id": "rec5-p1",
            "paper_title": "Robot Learning for Generalist Manipulation",
            "author_position": 1,
            "priority": 1,
        }
    ]


def test_public_summary_to_observations_extracts_person_and_facts():
    payload = load_fixture("aminer_public_summary_siwei_lyu.json")

    people, facts = public_summary_to_observations(
        payload,
        run_id="run-1",
        response_id="resp-2",
        aminer_person_id="53f4271edabfaeb22f3c93b8",
        source_url="https://www.aminer.cn/profile/53f4271edabfaeb22f3c93b8",
    )

    assert people[0]["name"] == "Siwei Lyu"
    assert people[0]["org"] == "University at Buffalo"
    assert people[0]["position"] == "Distinguished Professor"
    assert people[0]["h_index"] == 73
    fact_types = {fact["fact_type"] for fact in facts}
    assert {"education", "work", "homepage", "bio", "interest"}.issubset(fact_types)
    assert any(fact["source_path"] == "summary.contact.edu" for fact in facts)


def test_browser_snapshot_to_facts_rejects_full_html_and_text_fields():
    snapshot = load_fixture("aminer_browser_siwei_lyu_snapshot.json")
    snapshot["html"] = "<html>must not be stored</html>"
    snapshot["text"] = "full visible text must not be stored"

    raw_payload, facts = browser_snapshot_to_facts(
        snapshot,
        run_id="run-1",
        response_id="resp-3",
        aminer_person_id="53f4271edabfaeb22f3c93b8",
    )

    assert "html" not in raw_payload
    assert "text" not in raw_payload
    assert raw_payload["education_raw"] == "2001-2005 Dartmouth College Ph.D, Computer Science"
    assert facts[0]["fact_type"] == "education"
    assert facts[0]["needs_human_review"] == 0
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_parsers.py -q
```

Expected: FAIL because parser functions are missing.

- [ ] **Step 4: Implement parsers**

Create `src/aminer_builder/parsers.py` with:

- `clean_text(value)`
- `safe_int(value)`
- `json_dumps(value)`
- `rec5_payload_to_observations(...)`
- `public_summary_to_observations(...)`
- `browser_snapshot_to_facts(...)`

Implementation rules:

- Use deterministic IDs from `src.aminer_builder.ids`.
- Extract rec5 papers from `payload["data"][*]["papers"]`.
- Extract rec5 authors from `aminer_author_profiles` first, falling back to `authors`.
- Queue only rows with normalized `aminer_person_id`.
- Public summary fact `source_path` values must include `summary.contact.edu`, `summary.contact.work`, `summary.contact.homepage`, `summary.contact.bio`, and `summary.tags[*]` where data exists.
- Browser snapshot raw payload must whitelist fields listed in the spec and drop `html`, `text`, `screenshot`, `cookies`, `local_storage`, and `session_storage`.

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_parsers.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/aminer_builder/parsers.py temp/fixtures temp/test_aminer_builder_parsers.py
git commit -m "feat: parse aminer payload observations"
```

---

### Task 6: AMiner Client, Recall Service, and Queue Producer

**Files:**

- Create: `src/aminer_builder/aminer_client.py`
- Create: `src/aminer_builder/recall.py`
- Test: `temp/test_aminer_builder_recall.py`

- [ ] **Step 1: Write failing recall tests**

Create `temp/test_aminer_builder_recall.py`:

```python
import json
from pathlib import Path

from src.aminer_builder.config import TopicSpec
from src.aminer_builder.recall import RecallService


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def recommend_papers(self, *, topics, size, language_sort="", timeout=30):
        self.calls.append({"topics": topics, "size": size, "language_sort": language_sort, "timeout": timeout})
        return self.payload["data"][0]["papers"]


class FakeRepository:
    def __init__(self):
        self.raw = []
        self.paper_rows = []
        self.author_rows = []
        self.queued = []

    def insert_raw_response(self, row):
        self.raw.append(row)

    def insert_observations(self, table, rows):
        if table == "aminer_recalled_paper_observations":
            self.paper_rows.extend(rows)
        if table == "aminer_paper_author_observations":
            self.author_rows.extend(rows)

    def enqueue_people(self, run_id, rows):
        self.queued.extend(rows)
        return len(rows)


def test_recall_topic_saves_raw_observations_and_queues_person_ids():
    payload = json.loads(Path("temp/fixtures/aminer_rec5_robot_learning.json").read_text(encoding="utf-8"))
    repo = FakeRepository()
    service = RecallService(repository=repo, aminer_client=FakeClient(payload))
    topic = TopicSpec(
        catalog_key="global",
        catalog_version="v1",
        shard_key="ai_cs",
        topic_group_key="robotics",
        topic_group_priority=1,
        query="robot learning",
        papers_per_topic=5,
        max_people_per_shard=100,
    )

    result = service.recall_topic(run_id="run-1", topic=topic)

    assert result["papers"] == 1
    assert result["authors"] == 2
    assert result["queued_people"] == 1
    assert repo.raw[0]["endpoint"] == "rec5"
    assert "Robot Learning for Generalist Manipulation" in repo.raw[0]["payload_json"]
    assert repo.paper_rows[0]["paper_id"] == "rec5-p1"
    assert repo.author_rows[0]["aminer_person_id"] == "53f4271edabfaeb22f3c93b8"
    assert repo.queued[0]["aminer_person_id"] == "53f4271edabfaeb22f3c93b8"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_recall.py -q
```

Expected: FAIL because `RecallService` is missing.

- [ ] **Step 3: Implement AMiner client**

Create `src/aminer_builder/aminer_client.py` by porting these functions from `talent_radar/talent_harness/aminer_openapi_client.py`:

- `AMinerAPIError`
- `AMinerClient.__init__(config)`
- `recommend_papers(topics, size, language_sort="", timeout=30)`
- `public_person_summary(person_id, timeout=20)`
- `public_person_interests(person_id, timeout=20)`
- `public_person_pub_stats(person_id, timeout=20)`
- `public_person_publications(person_id, sort="year", offset=0, size=100, timeout=20)`
- `person_detail(person_id, timeout=30)`
- `person_figure(person_id, timeout=30)`

Keep token handling in the instance config. Do not print token values. Use `urllib.request` to match the existing client style.

- [ ] **Step 4: Implement recall service**

Create `src/aminer_builder/recall.py`:

```python
"""AMiner topic recall service."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from src.aminer_builder.ids import make_response_id
from src.aminer_builder.parsers import rec5_payload_to_observations


class RecallService:
    def __init__(self, repository, aminer_client):
        self.repository = repository
        self.aminer_client = aminer_client

    def recall_topic(self, *, run_id: str, topic) -> dict:
        papers = self.aminer_client.recommend_papers(
            topics=[topic.query],
            size=topic.papers_per_topic,
        )
        payload = {"data": [{"papers": papers}]}
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        response_id = make_response_id(run_id, "rec5", topic.query, payload_json)
        self.repository.insert_raw_response(
            {
                "response_id": response_id,
                "run_id": run_id,
                "endpoint": "rec5",
                "aminer_person_id": "",
                "aminer_paper_id": "",
                "query_text": topic.query,
                "source_url": "",
                "request_params_json": json.dumps({"topics": [topic.query], "size": topic.papers_per_topic}, ensure_ascii=False),
                "payload_json": payload_json,
                "payload_sha1": hashlib.sha1(payload_json.encode("utf-8")).hexdigest(),
                "http_status": None,
                "status": "ok" if papers else "empty",
                "parser_version": "aminer_builder_v1",
                "fetched_at": datetime.now(),
                "error": "",
            }
        )
        paper_rows, author_rows, queue_rows = rec5_payload_to_observations(
            payload,
            run_id=run_id,
            response_id=response_id,
            catalog_key=topic.catalog_key,
            shard_key=topic.shard_key,
            topic_group_key=topic.topic_group_key,
            domain_key=topic.topic_group_key,
            topic=topic.query,
        )
        self.repository.insert_observations("aminer_recalled_paper_observations", paper_rows)
        self.repository.insert_observations("aminer_paper_author_observations", author_rows)
        queued = self.repository.enqueue_people(run_id, queue_rows)
        return {"papers": len(paper_rows), "authors": len(author_rows), "queued_people": queued}
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_recall.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/aminer_builder/aminer_client.py src/aminer_builder/recall.py temp/test_aminer_builder_recall.py
git commit -m "feat: add aminer topic recall"
```

---

### Task 7: Browser Client and Profile Fetcher

**Files:**

- Create: `src/aminer_builder/browser_client.py`
- Create: `src/aminer_builder/profile_fetcher.py`
- Test: `temp/test_aminer_builder_profile_fetcher.py`

- [ ] **Step 1: Write failing profile fetcher tests**

Create `temp/test_aminer_builder_profile_fetcher.py`:

```python
import json
from pathlib import Path

from src.aminer_builder.profile_fetcher import ProfileFetcher


class FakeAMinerClient:
    def public_person_summary(self, person_id, timeout=20):
        return json.loads(Path("temp/fixtures/aminer_public_summary_siwei_lyu.json").read_text(encoding="utf-8"))

    def public_person_interests(self, person_id, timeout=20):
        return {"interests": [{"key": "Computer Vision"}]}

    def public_person_pub_stats(self, person_id, timeout=20):
        return {"years": [{"year": 2026, "count": 2}]}

    def public_person_publications(self, person_id, sort="year", offset=0, size=100, timeout=20):
        if offset > 0:
            return []
        return [{"id": "pub-1", "title": "Robot Learning for Generalist Manipulation", "year": 2026, "venue": "CoRL"}]

    def person_detail(self, person_id, timeout=30):
        raise RuntimeError("paid auth unavailable")

    def person_figure(self, person_id, timeout=30):
        raise RuntimeError("paid auth unavailable")


class FakeBrowserClient:
    def capture_profile(self, person_id, name=""):
        return json.loads(Path("temp/fixtures/aminer_browser_siwei_lyu_snapshot.json").read_text(encoding="utf-8"))


class FakeRepository:
    def __init__(self):
        self.raw = []
        self.observations = []
        self.done = []
        self.failed = []

    def insert_raw_response(self, row):
        self.raw.append(row)

    def insert_observations(self, table, rows):
        self.observations.append((table, list(rows)))

    def mark_person_done(self, aminer_person_id, run_id, profile_status):
        self.done.append((aminer_person_id, run_id, profile_status))

    def mark_person_failed(self, aminer_person_id, run_id, error):
        self.failed.append((aminer_person_id, run_id, error))


def test_fetch_person_stores_partial_success_and_browser_snapshot():
    repo = FakeRepository()
    fetcher = ProfileFetcher(
        repository=repo,
        aminer_client=FakeAMinerClient(),
        browser_client=FakeBrowserClient(),
        include_paid_detail=True,
        include_browser=True,
        publication_limit=100,
    )

    result = fetcher.fetch_person(
        run_id="run-1",
        aminer_person_id="53f4271edabfaeb22f3c93b8",
        name="Siwei Lyu",
    )

    assert result["status"] == "done"
    endpoints = {row["endpoint"]: row["status"] for row in repo.raw}
    assert endpoints["public_person_summary"] == "ok"
    assert endpoints["person_detail"] == "failed"
    assert endpoints["browser_profile_snapshot"] == "ok"
    assert repo.done[0][0] == "53f4271edabfaeb22f3c93b8"
    fact_tables = [table for table, rows in repo.observations if table == "aminer_profile_fact_observations" and rows]
    assert fact_tables
    browser_payloads = [json.loads(row["payload_json"]) for row in repo.raw if row["endpoint"] == "browser_profile_snapshot"]
    assert "html" not in browser_payloads[0]
    assert "text" not in browser_payloads[0]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_profile_fetcher.py -q
```

Expected: FAIL because `ProfileFetcher` is missing.

- [ ] **Step 3: Implement browser client**

Create `src/aminer_builder/browser_client.py`. Port the minimal safe behavior from `talent_radar/talent_harness/aminer_browser_context.py`:

- `aminer_profile_url(person_id, name="")`
- `BrowserCaptureConfig`
- `BrowserClient.capture_profile(person_id, name="")`

Use Playwright import inside `capture_profile` so unit tests do not require Playwright import. The method should return the parsed snapshot dict from the browser context code. If Playwright is unavailable, raise `RuntimeError("playwright_unavailable")`.

- [ ] **Step 4: Implement profile fetcher**

Create `src/aminer_builder/profile_fetcher.py` with:

- `ProfileFetcher.__init__(repository, aminer_client, browser_client=None, include_paid_detail=True, include_browser=True, publication_limit=200)`
- `fetch_person(run_id, aminer_person_id, name="")`
- internal `_save_endpoint(...)`

Rules:

- Always attempt public summary first.
- Continue if interests, pub stats, publications, paid detail, paid figure, or browser snapshot fail.
- Store failed endpoint rows in `aminer_raw_responses` with `status="failed"` and `error` set to the exception class name and message.
- Use `public_summary_to_observations` and `browser_snapshot_to_facts` to insert observations.
- Mark person done when public summary succeeds or browser snapshot succeeds. Mark failed only when no useful endpoint succeeds.

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_profile_fetcher.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add src/aminer_builder/browser_client.py src/aminer_builder/profile_fetcher.py temp/test_aminer_builder_profile_fetcher.py
git commit -m "feat: add aminer profile fetcher"
```

---

### Task 8: Coverage, CLI, and Stale Recovery

**Files:**

- Create: `src/aminer_builder/coverage.py`
- Create: `src/aminer_builder/cli.py`
- Test: `temp/test_aminer_builder_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `temp/test_aminer_builder_cli.py`:

```python
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class FakeConfig:
    aminer_database: str = "academic_aminer"


class FakeRepository:
    instances = []
    recovered = 0

    def __init__(self, config):
        self.config = config
        self.init_schema_calls = 0
        FakeRepository.instances.append(self)

    def init_schema(self):
        self.init_schema_calls += 1

    def recover_stale_processing(self, older_than_hours):
        return self.recovered


class FakeRecallService:
    calls = []

    def __init__(self, repository, aminer_client):
        self.repository = repository
        self.aminer_client = aminer_client

    def recall_topic(self, run_id, topic):
        self.calls.append((run_id, topic.query))
        return {"papers": 1, "authors": 2, "queued_people": 1}


class FakeAMinerClient:
    def __init__(self, config):
        self.config = config


def test_init_schema_command_initializes_aminer_database(monkeypatch, capsys):
    import src.aminer_builder.cli as cli

    FakeRepository.instances = []
    monkeypatch.setattr(cli, "get_config", lambda: FakeConfig())
    monkeypatch.setattr(cli, "AMinerRepository", FakeRepository)

    assert cli.main(["init-schema"]) == 0

    assert FakeRepository.instances[0].init_schema_calls == 1
    assert capsys.readouterr().out == "initialized academic_aminer\n"


def test_recover_stale_command_reports_recovered_count(monkeypatch, capsys):
    import src.aminer_builder.cli as cli

    FakeRepository.instances = []
    FakeRepository.recovered = 3
    monkeypatch.setattr(cli, "get_config", lambda: FakeConfig())
    monkeypatch.setattr(cli, "AMinerRepository", FakeRepository)

    assert cli.main(["recover-stale", "--older-than-hours", "6"]) == 0

    assert capsys.readouterr().out == "recovered 3 stale queue rows\n"


def test_run_topic_group_loads_catalog_and_calls_recall(monkeypatch, tmp_path, capsys):
    import json
    import src.aminer_builder.cli as cli

    root = tmp_path / "data"
    (root / "catalog").mkdir(parents=True)
    (root / "shards").mkdir()
    shard = root / "shards" / "ai_cs.json"
    shard.write_text(
        json.dumps(
            {
                "shard_key": "ai_cs",
                "shard_label": "AI",
                "topic_groups": [{"group_key": "nlp", "priority": 1, "topics": ["large language models"]}],
            }
        ),
        encoding="utf-8",
    )
    catalog = root / "catalog" / "global.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog_key": "global",
                "catalog_label": "Global",
                "catalog_version": "v1",
                "default_budget": "pilot",
                "budgets": {"pilot": {"papers_per_topic": 1, "max_topics_per_shard": 2, "max_people_per_shard": 10}},
                "shards": ["../shards/ai_cs.json"],
            }
        ),
        encoding="utf-8",
    )

    FakeRecallService.calls = []
    monkeypatch.setattr(cli, "get_config", lambda: FakeConfig())
    monkeypatch.setattr(cli, "AMinerRepository", FakeRepository)
    monkeypatch.setattr(cli, "AMinerClient", FakeAMinerClient)
    monkeypatch.setattr(cli, "RecallService", FakeRecallService)

    assert cli.main(["run-topic-group", "--catalog", str(catalog), "--shard", "ai_cs", "--group", "nlp"]) == 0

    assert FakeRecallService.calls[0][1] == "large language models"
    assert "recall complete" in capsys.readouterr().out


def test_positive_int_rejects_zero():
    import src.aminer_builder.cli as cli

    with pytest.raises(SystemExit):
        cli.main(["recover-stale", "--older-than-hours", "0"])
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_cli.py -q
```

Expected: FAIL because `src.aminer_builder.cli` is missing.

- [ ] **Step 3: Implement coverage helper**

Create `src/aminer_builder/coverage.py` with a pure function:

```python
def build_coverage_summary(*, topics_attempted=0, rec5_ok=0, rec5_empty=0, paper_rows=0, author_rows=0, queued_people=0, people_done=0, people_failed=0):
    return {
        "recall": {
            "rec5_queries_attempted": topics_attempted,
            "rec5_queries_ok": rec5_ok,
            "rec5_queries_empty": rec5_empty,
            "recalled_paper_count": paper_rows,
        },
        "author": {
            "paper_author_observation_count": author_rows,
            "unique_people_enqueued": queued_people,
        },
        "profile": {
            "people_done": people_done,
            "people_failed": people_failed,
        },
    }
```

- [ ] **Step 4: Implement CLI**

Create `src/aminer_builder/cli.py` with commands:

- `init-schema`
- `run-topic-group --catalog PATH --shard KEY --group KEY --budget NAME`
- `build-review-csv --catalog PATH --shard KEY --group KEY --people-limit N --output-dir PATH`
- `recover-stale --older-than-hours N`

Also add parser stubs for these commands so help output is stable, even if full orchestration is completed in Task 10:

- `run-catalog`
- `run-shard`
- `recall-domain`
- `run-domain`
- `process-people`
- `build-review-csv`

Use `positive_int` copied from `src/cv_builder/cli.py`.

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_cli.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 8**

```bash
git add src/aminer_builder/coverage.py src/aminer_builder/cli.py temp/test_aminer_builder_cli.py
git commit -m "feat: add aminer builder cli"
```

---

### Task 9: Instance Test Commands and Documentation

**Files:**

- Modify: `README.md`
- Modify: `.env.example`
- Create: `temp/test_aminer_builder_instance_docs.py`

- [ ] **Step 1: Write failing documentation tests**

Create `temp/test_aminer_builder_instance_docs.py`:

```python
from pathlib import Path


def test_readme_documents_aminer_builder_instance_tests():
    text = Path("README.md").read_text(encoding="utf-8")

    assert "AMiner Catalog Builder" in text
    assert "Instance tests" in text
    assert "run-topic-group" in text
    assert "build-review-csv" in text
    assert "53f4271edabfaeb22f3c93b8" in text
    assert "browser parsed snapshot" in text


def test_env_example_documents_aminer_builder_variables():
    text = Path(".env.example").read_text(encoding="utf-8")

    assert "AMINER_DATABASE=academic_aminer" in text
    assert "AMINER_API_TOKEN=" in text
    assert "AMINER_BROWSER_PROFILE_DIR=.auth/aminer/chrome_profile" in text
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_instance_docs.py -q
```

Expected: FAIL because README and `.env.example` do not yet document AMiner builder.

- [ ] **Step 3: Update `.env.example`**

Append:

```dotenv

# AMiner catalog builder
AMINER_DATABASE=academic_aminer
AMINER_API_TOKEN=
AMINER_API_KEY=
AMINER_API_BASE_URL=https://datacenter.aminer.cn/gateway/open_platform
AMINER_PUBLIC_PROFILE_BASE_URL=https://api.aminer.cn/api
AMINER_BROWSER_PROFILE_DIR=.auth/aminer/chrome_profile
AMINER_BUILDER_REQUEST_TIMEOUT=30
AMINER_BUILDER_ENV_FILE=
```

- [ ] **Step 4: Update README**

Add a section:

```markdown
### AMiner Catalog Builder

The AMiner catalog builder captures AMiner people data into the separate `academic_aminer` ClickHouse database. It does not write into `academic_cv` normalized CV tables.

Initialize schema:

```bash
venv/bin/python3 -m src.aminer_builder.cli init-schema
```

Run a fixed topic-group pilot:

```bash
venv/bin/python3 -m src.aminer_builder.cli run-topic-group \
  --catalog data/aminer_domains/catalog/global_academic_catalog.json \
  --shard ai_cs \
  --group natural_language_processing \
  --budget pilot
```

Recover stale queue rows:

```bash
venv/bin/python3 -m src.aminer_builder.cli recover-stale --older-than-hours 6
```

Build the mandatory pre-ClickHouse 20-person CSV review package:

```bash
venv/bin/python3 -m src.aminer_builder.cli build-review-csv \
  --catalog data/aminer_domains/catalog/global_academic_catalog.json \
  --shard ai_cs \
  --group natural_language_processing \
  --people-limit 20 \
  --output-dir output/aminer_builder_review
```

Stop after this command and review the generated CSV files before enabling live ClickHouse writes.

#### Instance tests

Instance tests complement mock smoke tests and use fixed seeds:

- Topic recall instance: run `ai_cs:natural_language_processing` with `pilot` budget and verify raw rec5, recalled paper, paper-author, and queue rows exist.
- Person profile instance: fetch AMiner person `53f4271edabfaeb22f3c93b8` and verify public summary, publication observations, and profile facts.
- Browser parsed snapshot instance: parse `temp/fixtures/aminer_browser_siwei_lyu_snapshot.json` and verify no full HTML, no full visible text, and no screenshot fields are persisted.
- Queue recovery instance: create stale `processing` rows and run `recover-stale`.
- Pre-ClickHouse CSV review instance: generate exactly 20 people into `output/aminer_builder_review/<run_id>/*.csv` with headers matching the target ClickHouse tables; wait for user approval before database writes.
- End-to-end pilot instance: run a tiny catalog and inspect `log/aminer_builder/<run_id>_summary.json`.

Authenticated browser capture stores parsed snapshots only. Do not commit `.auth/`, browser storage state, full HTML, screenshots, or private session data.
```

- [ ] **Step 5: Run documentation tests**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_instance_docs.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Commit Task 9**

```bash
git add README.md .env.example temp/test_aminer_builder_instance_docs.py
git commit -m "docs: document aminer instance tests"
```

---

### Task 10: Final Verification and PR Prep

**Files:**

- No new source files.
- Update implementation notes in PR body when creating PR.

- [ ] **Step 1: Run all AMiner builder mock tests**

Run:

```bash
venv/bin/python3 -m pytest \
  temp/test_aminer_builder_ids.py \
  temp/test_aminer_builder_schema.py \
  temp/test_aminer_builder_config.py \
  temp/test_aminer_builder_csv_review.py \
  temp/test_aminer_builder_parsers.py \
  temp/test_aminer_builder_repository.py \
  temp/test_aminer_builder_recall.py \
  temp/test_aminer_builder_profile_fetcher.py \
  temp/test_aminer_builder_cli.py \
  temp/test_aminer_builder_instance_docs.py \
  -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run existing CV builder tests to guard reference behavior**

Run:

```bash
venv/bin/python3 -m pytest \
  temp/test_cv_builder_ids.py \
  temp/test_cv_builder_builders.py \
  temp/test_cv_builder_repository_sql.py \
  temp/test_cv_builder_cli.py \
  temp/test_cv_builder_runner.py \
  -q
```

Expected: all tests PASS.

- [ ] **Step 3: Run fixed parser instance tests**

Run:

```bash
venv/bin/python3 -m pytest temp/test_aminer_builder_parsers.py::test_browser_snapshot_to_facts_rejects_full_html_and_text_fields -q
```

Expected: PASS, proving the browser parsed snapshot fixture does not persist `html` or `text`.

- [ ] **Step 4: Generate the mandatory 20-person CSV review package**

Run:

```bash
venv/bin/python3 -m src.aminer_builder.cli build-review-csv \
  --catalog data/aminer_domains/catalog/global_academic_catalog.json \
  --shard ai_cs \
  --group natural_language_processing \
  --people-limit 20 \
  --output-dir output/aminer_builder_review
```

Expected:

```text
review CSV package written to output/aminer_builder_review/<run_id>
```

Expected files:

```text
output/aminer_builder_review/<run_id>/aminer_raw_responses.csv
output/aminer_builder_review/<run_id>/aminer_recalled_paper_observations.csv
output/aminer_builder_review/<run_id>/aminer_paper_author_observations.csv
output/aminer_builder_review/<run_id>/aminer_person_observations.csv
output/aminer_builder_review/<run_id>/aminer_publication_observations.csv
output/aminer_builder_review/<run_id>/aminer_profile_fact_observations.csv
output/aminer_builder_review/<run_id>/aminer_person_fetch_queue.csv
output/aminer_builder_review/<run_id>/aminer_run_coverage_reports.csv
```

Stop here and ask the user to review the CSV package. Do not run live ClickHouse insert validation until the user approves the CSV package.

- [ ] **Step 5: Run optional live ClickHouse instance test after CSV approval**

Run only after the user approves the 20-person CSV review package and `AMINER_API_TOKEN` or `AMINER_API_KEY` is configured:

```bash
venv/bin/python3 -m src.aminer_builder.cli run-topic-group \
  --catalog data/aminer_domains/catalog/global_academic_catalog.json \
  --shard ai_cs \
  --group natural_language_processing \
  --budget pilot
```

Expected:

```text
recall complete
```

Then inspect ClickHouse:

```bash
clickhouse-client --query "SELECT endpoint, count() FROM academic_aminer.aminer_raw_responses GROUP BY endpoint ORDER BY endpoint"
clickhouse-client --query "SELECT count() FROM academic_aminer.aminer_paper_author_observations WHERE aminer_person_id != ''"
```

Expected: at least one `rec5` raw response row and at least one paper-author row with `aminer_person_id` when AMiner returns author IDs.

- [ ] **Step 6: Check git status**

Run:

```bash
git status --short
```

Expected: no unstaged or uncommitted files.

- [ ] **Step 7: Create PR using team-collab `+pr` workflow**

Before PR, run local CI as required by `team-collab`. If no project-wide CI script exists, use the test commands from Steps 1 and 2 as the local gate.

PR body must include:

```markdown
Closes #1

## Summary
- Added AMiner catalog builder package with ClickHouse raw and observation schema.
- Added catalog/shard config for broad AMiner topic coverage.
- Added mock tests and fixed instance tests for rec5, public profile, browser parsed snapshot, queue, and CLI flows.

## Validation
- `venv/bin/python3 -m pytest ...aminer builder tests... -q`
- `venv/bin/python3 -m pytest ...cv builder guard tests... -q`
- 20-person CSV review package path and user approval status.
- Live ClickHouse instance test result: run only after CSV approval, or explicitly note not run because token/browser state or approval was unavailable.
```
