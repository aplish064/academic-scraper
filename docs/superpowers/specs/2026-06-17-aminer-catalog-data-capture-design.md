# AMiner Catalog Data Capture Design

Issue: #1 `Define AMiner catalog data capture`

Date: 2026-06-17

Status: Approved design discussion, ready for implementation planning after user review.

Branch note: this work is intentionally branched from `feature/academic-cv-builder-sample` because `origin/main` does not yet contain `src/cv_builder`, which is the local reference architecture for this design.

## Goal

Build an AMiner data capture layer in the `academic` repository that uses broad topic catalog runs to discover AMiner people and capture person-related AMiner data into ClickHouse raw and observation tables.

The first implementation should support broad AMiner coverage through topic shards rather than an unbounded crawler:

1. Load a versioned academic topic catalog.
2. Use AMiner rec5 topic recall to discover papers and paper-author AMiner IDs.
3. Queue authors with `aminer_person_id` for profile enrichment.
4. Fetch full person-related AMiner data, including public profile JSON, optional paid Open Platform detail/figure data, and authenticated browser parsed snapshots.
5. Store raw endpoint responses plus parsed observation rows.
6. Keep AMiner data separate from normalized `academic_cv` tables until a later identity/merge layer is designed.

## Non-Goals

- Do not write AMiner facts directly into `academic_cv.personal_profile`, `academic_cv.education_work_experience`, or other normalized CV tables.
- Do not build a JD parser or recruitment ranking system in `academic`.
- Do not crawl arbitrary AMiner URLs or recursively expand through all coauthors by default.
- Do not store full authenticated browser HTML, full visible text, screenshots, cookies, local storage, or session storage.
- Do not automate login credentials or bypass AMiner access controls.
- Do not auto-fetch profiles for name-only authors without an AMiner ID in the first version.

## Existing References

Reference implementation patterns:

- `src/cv_builder`: ClickHouse schema/repository/runner/CLI structure.
- `ai-toptalent-workstation-server/talent_radar/talent_harness/aminer_openapi_client.py`: AMiner Open Platform and public profile HTTP client behavior.
- `ai-toptalent-workstation-server/talent_radar/talent_harness/aminer_browser_context.py`: authenticated browser parsed snapshot capture.
- `ai-toptalent-workstation-server/talent_radar/talent_harness/aminer_topic_recall.py`: rec5 topic recall, paper-author normalization, and public profile enrichment helpers.

Relevant `academic` constraints:

- Core scraping scripts live under `academic/src`.
- Process logs live under `academic/log`.
- Tests and temporary development files live under `academic/temp`.
- Captured data is stored in local ClickHouse.

## Architecture

Create a new package:

```text
src/aminer_builder/
  __init__.py
  config.py
  schema.py
  repository.py
  aminer_client.py
  browser_client.py
  recall.py
  profile_fetcher.py
  parsers.py
  cli.py
```

Module responsibilities:

- `config.py`: load environment variables and catalog/shard/domain config files.
- `schema.py`: define ClickHouse DDL for the AMiner raw and observation layer.
- `repository.py`: insert raw responses, observations, queue state, run state, and coverage reports.
- `aminer_client.py`: port and narrow AMiner HTTP helpers from `talent_radar` for this repo.
- `browser_client.py`: port browser parsed snapshot capture, preserving the no-full-HTML policy.
- `recall.py`: execute rec5 topic recall and produce recalled paper and paper-author observations.
- `profile_fetcher.py`: consume person fetch queue and fetch public/paid/browser profile data.
- `parsers.py`: convert raw AMiner payloads and browser snapshots into observation rows.
- `cli.py`: expose schema initialization, catalog/shard/topic runs, queue processing, and stale recovery.

## Data Model

Use a separate ClickHouse database by default:

```text
AMINER_DATABASE=academic_aminer
```

This database is a source observation layer, not a normalized CV layer.

### Run State

`aminer_fetch_runs`

Purpose: record catalog, shard, topic-group, topic, and profile-batch runs.

Columns:

```text
run_id String
parent_run_id String
run_scope String
catalog_key String
catalog_version String
shard_key String
topic_group_key String
topic String
domain_key String
domain_label String
budget_name String
config_path String
config_json String
status String
started_at DateTime
finished_at Nullable(DateTime)
error_summary String
```

`run_scope` values:

```text
catalog
shard
topic_group
topic
profile_batch
domain
```

`status` values:

```text
running
done
failed
cancelled
```

### Person Fetch Queue

`aminer_person_fetch_queue`

Purpose: queue AMiner person IDs discovered from rec5 paper-author metadata.

Columns:

```text
aminer_person_id String
run_id String
seed_type String
seed_value String
name String
profile_url String
topic String
paper_id String
paper_title String
author_position Nullable(UInt16)
priority UInt16
status String
retry_count UInt16
last_error String
profile_status_json String
created_at DateTime
updated_at DateTime
```

Queue key: `run_id + aminer_person_id`.

`status` values:

```text
pending
processing
done
failed
skipped
```

Only authors with an AMiner person ID are automatically queued. Name-only authors are stored as observations but are not fetched automatically.

### Raw Responses

`aminer_raw_responses`

Purpose: store every AMiner endpoint response and every browser parsed snapshot.

Columns:

```text
response_id String
run_id String
endpoint String
aminer_person_id String
aminer_paper_id String
query_text String
source_url String
request_params_json String
payload_json String
payload_sha1 String
http_status Nullable(UInt16)
status String
parser_version String
fetched_at DateTime
error String
```

Endpoint values:

```text
rec5
public_person_summary
public_person_interests
public_person_pub_stats
public_person_publications
person_detail
person_figure
browser_profile_snapshot
```

`payload_json` is the durable source asset. Parser improvements can replay from this table.

Browser policy:

- Save parsed snapshot JSON only.
- Do not save full HTML.
- Do not save full visible text.
- Do not save screenshots.
- Do not save cookies, local storage values, or session storage values.

Allowed browser snapshot fields include:

```text
source
source_type
source_url
requested_url
final_url
title
http_status
status
error
fetched_at
document_type
text_chars
locked_or_login_prompt
logged_in_likely
education
education_raw
paper_titles
paper_links
links
summary
elapsed_seconds
local_storage_key_count
session_storage_key_count
storage_meta paths and key counts only
```

### Topic and Paper Observations

`aminer_recalled_paper_observations`

Purpose: preserve papers returned by rec5 topic recall.

Columns:

```text
observation_id String
response_id String
run_id String
catalog_key String
shard_key String
topic_group_key String
domain_key String
topic String
paper_id String
title String
year Nullable(UInt16)
venue String
citation_count Nullable(UInt32)
url String
authors_json String
topics_json String
observed_at DateTime
```

`aminer_paper_author_observations`

Purpose: preserve the topic -> paper -> author identity anchor.

Columns:

```text
observation_id String
response_id String
run_id String
catalog_key String
shard_key String
topic_group_key String
domain_key String
topic String
paper_id String
paper_title String
author_name String
author_position Nullable(UInt16)
author_count Nullable(UInt16)
aminer_person_id String
affiliation String
profile_url String
source_path String
observed_at DateTime
```

Rows without `aminer_person_id` are retained for audit and future resolution work.

### Person Observations

`aminer_person_observations`

Purpose: query-friendly person-level fields from public summary, paid detail/figure, and browser metadata.

Columns:

```text
observation_id String
response_id String
run_id String
aminer_person_id String
name String
name_zh String
org String
position String
homepage String
bio String
h_index Nullable(UInt32)
g_index Nullable(UInt32)
num_pubs Nullable(UInt32)
num_citation Nullable(UInt32)
interests_json String
source_endpoint String
source_url String
observed_at DateTime
```

`aminer_publication_observations`

Purpose: profile-publication and rec5-publication facts tied to a person when available.

Columns:

```text
observation_id String
response_id String
run_id String
aminer_person_id String
paper_id String
title String
venue String
year Nullable(UInt16)
citation_count Nullable(UInt32)
url String
authors_json String
source_endpoint String
source_url String
observed_at DateTime
```

`aminer_profile_fact_observations`

Purpose: semi-structured facts from public summary, paid detail/figure, and browser parsed snapshots.

Columns:

```text
fact_id String
response_id String
run_id String
aminer_person_id String
fact_type String
raw_text String
normalized_label String
source_path String
extraction_method String
confidence Nullable(Float32)
source_url String
needs_human_review UInt8
observed_at DateTime
```

Fact types:

```text
education
work
affiliation
homepage
link
interest
metric
bio
```

This table stores evidence candidates. It does not decide final CV truth.

## Catalog Configuration

The primary first-version input is a versioned broad academic catalog, not a single domain JSON.

Recommended layout:

```text
data/aminer_domains/
  catalog/global_academic_catalog.json
  shards/ai_cs.json
  shards/engineering.json
  shards/natural_science.json
  shards/life_medicine.json
  shards/social_science.json
  shards/interdisciplinary.json
```

Global catalog example:

```json
{
  "catalog_key": "global_academic_v1",
  "catalog_label": "AMiner global academic coverage v1",
  "catalog_version": "2026-06-17",
  "goal": "broad_person_coverage_from_aminer_rec5_topics",
  "default_budget": "pilot",
  "budgets": {
    "pilot": {
      "papers_per_topic": 20,
      "max_topics_per_shard": 30,
      "max_people_per_shard": 1000
    },
    "standard": {
      "papers_per_topic": 50,
      "max_topics_per_shard": 120,
      "max_people_per_shard": 10000
    },
    "deep": {
      "papers_per_topic": 100,
      "max_topics_per_shard": 300,
      "max_people_per_shard": 50000
    }
  },
  "rate_limits": {
    "rec5_sleep_seconds": 0.2,
    "profile_sleep_seconds": 0.5,
    "browser_parallel_pages": 3,
    "daily_profile_fetch_limit": 5000,
    "stop_on_429": true,
    "cooldown_minutes_on_auth_error": 60
  },
  "profile_enrichment": {
    "profile_depth": "full-with-browser",
    "publication_limit_per_person": 200,
    "include_interests": true,
    "include_pub_stats": true,
    "include_paid_detail": true,
    "include_browser": true,
    "browser_raw_policy": "parsed_snapshot_only"
  },
  "identity_policy": {
    "require_aminer_author_id_for_profile_fetch": true,
    "store_name_only_authors": true,
    "auto_fetch_name_only_authors": false
  },
  "shards": [
    "shards/ai_cs.json",
    "shards/engineering.json",
    "shards/natural_science.json",
    "shards/life_medicine.json",
    "shards/social_science.json",
    "shards/interdisciplinary.json"
  ]
}
```

Shard example:

```json
{
  "shard_key": "ai_cs",
  "shard_label": "AI and Computer Science",
  "topic_groups": [
    {
      "group_key": "machine_learning",
      "priority": 1,
      "topics": [
        "machine learning",
        "deep learning",
        "representation learning",
        "self-supervised learning",
        "reinforcement learning",
        "federated learning",
        "trustworthy machine learning"
      ]
    },
    {
      "group_key": "natural_language_processing",
      "priority": 1,
      "topics": [
        "natural language processing",
        "large language models",
        "information extraction",
        "machine translation",
        "question answering",
        "retrieval augmented generation",
        "LLM agents"
      ]
    }
  ]
}
```

Initial shard coverage should include:

- `ai_cs`: AI, machine learning, NLP, computer vision, robotics, information retrieval, data mining, databases, HCI, security, software engineering, systems, networks, theory, visualization.
- `engineering`: electrical engineering, control, signal processing, communications, mechanical, civil, aerospace, energy, materials, manufacturing, transportation.
- `natural_science`: mathematics, statistics, physics, chemistry, earth science, climate, environment, astronomy, geoscience.
- `life_medicine`: biology, bioinformatics, genomics, neuroscience, medicine, public health, pharmacology, biomedical engineering.
- `social_science`: economics, finance, management, psychology, education, sociology, political science, law, communication.
- `interdisciplinary`: AI for science, computational social science, digital humanities, climate AI, smart cities, human-centered AI, data science.

Existing `talent_radar/knowledge/domain_filters` should seed high-priority groups in catalog v1:

- `ai4science`
- `cyber_security`
- `data_mining_recommender`
- `multimodal_llm`
- `cross_domain`

## CLI Workflows

Initialize schema:

```bash
venv/bin/python3 -m src.aminer_builder.cli init-schema
```

Run a full catalog budget:

```bash
venv/bin/python3 -m src.aminer_builder.cli run-catalog \
  --catalog data/aminer_domains/catalog/global_academic_catalog.json \
  --budget pilot
```

Run one shard:

```bash
venv/bin/python3 -m src.aminer_builder.cli run-shard \
  --catalog data/aminer_domains/catalog/global_academic_catalog.json \
  --shard ai_cs \
  --budget standard
```

Run one topic group:

```bash
venv/bin/python3 -m src.aminer_builder.cli run-topic-group \
  --shard data/aminer_domains/shards/ai_cs.json \
  --group natural_language_processing \
  --budget pilot
```

Run one legacy-style domain file:

```bash
venv/bin/python3 -m src.aminer_builder.cli recall-domain \
  --config data/aminer_domains/robot_learning.json
```

Process person queue:

```bash
venv/bin/python3 -m src.aminer_builder.cli process-people \
  --count 100
```

One-command small run:

```bash
venv/bin/python3 -m src.aminer_builder.cli run-domain \
  --config data/aminer_domains/robot_learning.json \
  --process-count 100
```

Recover stale processing jobs:

```bash
venv/bin/python3 -m src.aminer_builder.cli recover-stale \
  --older-than-hours 6
```

## Topic Recall Flow

For each topic, in priority order:

1. Create or update an `aminer_fetch_runs` row.
2. Call AMiner rec5 with configured `papers_per_topic`, language preference, and timeout.
3. Store the rec5 response in `aminer_raw_responses`.
4. Parse recalled papers into `aminer_recalled_paper_observations`.
5. Parse paper authors into `aminer_paper_author_observations`.
6. Enqueue authors with `aminer_person_id` into `aminer_person_fetch_queue`.
7. Store name-only authors as observations only.

The audit chain must remain queryable:

```text
catalog -> shard -> topic_group -> topic -> paper -> author -> aminer_person_id -> profile responses
```

## Person Profile Flow

For each pending person:

1. Mark queue row `processing`.
2. Fetch `public_person_summary`.
3. Fetch `public_person_interests` when enabled.
4. Fetch `public_person_pub_stats` when enabled.
5. Fetch `public_person_publications` pages up to `publication_limit_per_person`.
6. Fetch `person_detail` and `person_figure` when `include_paid_detail=true`; auth failures do not block public data.
7. Fetch `browser_profile_snapshot` when `include_browser=true`; login/profile failures do not block public data.
8. Store every endpoint success or failure in `aminer_raw_responses`.
9. Parse person, publication, and profile fact observations.
10. Mark queue row `done` if core public summary and at least one useful profile response completed; otherwise `failed` or `skipped`.

`profile_status_json` records per-endpoint results:

```json
{
  "public_person_summary": "ok",
  "public_person_interests": "ok",
  "public_person_pub_stats": "failed",
  "public_person_publications": "partial",
  "person_detail": "auth_error",
  "person_figure": "auth_error",
  "browser_profile_snapshot": "ok"
}
```

## Failure Handling

Failures are classified before retry:

```text
network_timeout
  Retry with exponential backoff, max 3 attempts.

http_429 / rate_limited
  Stop current shard when stop_on_429=true. Record cooldown event.

auth_error / token_parse_error
  Stop paid or token-dependent endpoint class for this run. Keep public/browser successes.

browser_login_prompt
  Stop browser enrichment for the current run and ask operator to refresh login. Keep public API data.

not_found / empty_profile
  Do not retry. Mark endpoint empty or queue skipped.

parse_error
  Keep raw response and mark parser failed. Parser replay can repair later.
```

Profile fetching uses partial success. One endpoint failure does not erase other endpoint data.

## Logging

Write process logs under:

```text
log/aminer_builder/
```

Per run:

```text
log/aminer_builder/<run_id>.jsonl
log/aminer_builder/<run_id>_summary.json
```

JSONL event types:

```text
run_started
topic_started
rec5_response_saved
paper_observations_written
authors_enqueued
person_fetch_started
endpoint_response_saved
person_observations_written
profile_facts_written
person_done
person_failed
rate_limit_detected
auth_error_detected
browser_login_prompt_detected
run_finished
```

## Coverage Reports

Write a coverage summary after each run. It can first be a JSON summary file, then become a ClickHouse table in implementation if useful.

Metrics:

```text
catalog coverage
  total_shards
  completed_shards
  total_topic_groups
  completed_topic_groups
  total_topics
  completed_topics

recall coverage
  rec5_queries_attempted
  rec5_queries_ok
  rec5_queries_empty
  recalled_paper_count
  unique_recalled_paper_count

author coverage
  paper_author_observation_count
  author_rows_with_aminer_person_id
  author_rows_without_aminer_person_id
  unique_aminer_person_ids_discovered
  unique_people_enqueued

profile coverage
  people_attempted
  people_done
  people_failed
  public_summary_ok
  public_publications_ok
  pub_stats_ok
  interests_ok
  paid_detail_ok
  browser_snapshot_ok
  browser_login_prompt_count

data richness
  people_with_org
  people_with_position
  people_with_homepage
  people_with_interests
  people_with_h_index
  people_with_publications
  people_with_education_fact
  people_with_work_fact
```

## Stop Conditions

Every catalog run requires bounded budgets:

```text
budget_name
max_topics_per_shard
max_people_per_shard
daily_profile_fetch_limit
stop_on_429
stop_on_auth_error
max_runtime_hours
```

Default to `pilot`. `deep` requires explicit operator selection.

## Testing Strategy

Tests live under `temp`, matching the existing `academic` convention.

### Mock Smoke Tests

Mock tests must not call AMiner network endpoints by default.

Files:

```text
temp/test_aminer_builder_config.py
temp/test_aminer_builder_schema.py
temp/test_aminer_builder_parsers.py
temp/test_aminer_builder_queue.py
temp/test_aminer_builder_cli.py
```

Coverage:

- Catalog, shard, and topic group expansion.
- ClickHouse DDL generation.
- rec5 paper payload -> recalled paper observations.
- rec5 `aminer_author_profiles` -> paper-author observations and queue rows.
- public summary payload -> person observations and education/work/profile facts.
- browser parsed snapshot -> profile facts without full HTML/full text/screenshot fields.
- queue status transitions and retry counters.
- CLI argument parsing and command dispatch.

### Fixed Instance Tests

Each implementation stage must include at least one fixed instance test in addition to smoke tests.

Instance tests may be operator-run when they require AMiner network or authenticated browser state. They must use fixed seeds and record expected artifacts.

Required instance tests:

1. Topic recall instance:
   - Seed: a fixed catalog shard/group such as `ai_cs:natural_language_processing` with one or two fixed topics.
   - Expected: at least one rec5 raw response row, recalled paper observation rows, paper-author observation rows, and queued `aminer_person_id` rows when AMiner returns author IDs.

2. Person public profile instance:
   - Seed: fixed AMiner person ID `53f4271edabfaeb22f3c93b8` for Siwei Lyu, or another stable AMiner ID selected during implementation.
   - Expected: public summary raw response, person observation with name/org when available, publication observations, and profile facts from public JSON when available.

3. Browser parsed snapshot instance:
   - Seed: fixed browser snapshot fixture from `talent_radar/outputs/login_state_check/aminer_browser_siwei_lyu.json` or a copied sanitized fixture under `temp/fixtures`.
   - Expected: education facts parsed; no full HTML, no full visible text, no screenshot fields in stored payload.

4. Queue recovery instance:
   - Seed: synthetic queue rows with stale `processing` timestamps.
   - Expected: `recover-stale` returns stale rows to `pending` without incrementing retry count.

5. End-to-end pilot instance:
   - Seed: a tiny catalog with one shard, one topic group, one topic, and a small process count.
   - Expected: run summary reports topic, paper, author, profile, and fact coverage.

Instance test results should be summarized in the design or implementation PR description so reviewers can see both mocked behavior and real-data behavior.

## Rollout Plan

1. Create schema and config loading with mock tests.
2. Implement rec5 recall and raw/paper/author observation storage.
3. Implement person queue and public profile fetch.
4. Implement browser parsed snapshot fetch with strict raw policy.
5. Implement catalog/shard/topic-group orchestration.
6. Add coverage reports and stale recovery.
7. Run mock tests and fixed instance tests.
8. Stop before normalized `academic_cv` integration; design that separately.

## ClickHouse Engine Defaults

The first implementation should use these engines unless an implementation-time test exposes a concrete problem:

- `aminer_fetch_runs`: `ReplacingMergeTree(started_at)` ordered by `(run_id)`.
- `aminer_person_fetch_queue`: `ReplacingMergeTree(updated_at)` ordered by `(run_id, aminer_person_id)`.
- `aminer_raw_responses`: `MergeTree` ordered by `(run_id, endpoint, fetched_at, response_id)`. Raw responses should retain multiple observations over time even when payload hashes match.
- `aminer_recalled_paper_observations`: `ReplacingMergeTree(observed_at)` ordered by `(run_id, topic, paper_id, observation_id)`.
- `aminer_paper_author_observations`: `ReplacingMergeTree(observed_at)` ordered by `(run_id, topic, paper_id, author_position, aminer_person_id, observation_id)`.
- `aminer_person_observations`: `ReplacingMergeTree(observed_at)` ordered by `(aminer_person_id, source_endpoint, response_id, observation_id)`.
- `aminer_publication_observations`: `ReplacingMergeTree(observed_at)` ordered by `(aminer_person_id, paper_id, source_endpoint, observation_id)`.
- `aminer_profile_fact_observations`: `ReplacingMergeTree(observed_at)` ordered by `(aminer_person_id, fact_type, source_path, fact_id)`.
- `aminer_run_coverage_reports`: `ReplacingMergeTree(generated_at)` ordered by `(run_id, report_id)`.

Coverage summaries should be written both as JSON files under `log/aminer_builder/` and as rows in `aminer_run_coverage_reports` in v1.
