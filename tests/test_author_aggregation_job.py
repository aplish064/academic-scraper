import unittest
from datetime import date, datetime, timezone

from src.author_aggregation.models import AuthorObservation, IngestState
from src.author_aggregation.job import (
    AuthorAggregationJob,
    INITIAL_WATERMARK,
    build_pipeline_run_id,
    normalize_datetime,
    parse_args,
    parse_source_window_hours,
)


class FakeRepository:
    def __init__(self):
        self.created_schema = False
        self.seeded_dictionary = False
        self.inserted_observations = []
        self.inserted_paper_edges = []
        self.inserted_author_edges = []
        self.inserted_entities = []
        self.source_rows = {}
        self.fetch_calls = []
        self.ingest_states = {}
        self.state_calls = []
        self.event_log = []
        self.fail_sources = set()
        self.min_watermarks = {}
        self.next_watermarks = {}
        self.fail_insert_observations = False

    def create_schema(self):
        self.created_schema = True

    def seed_field_dictionary(self):
        self.seeded_dictionary = True

    def insert_observations(self, observations):
        self.event_log.append(("insert", "author_observations", len(observations)))
        if self.fail_insert_observations:
            raise RuntimeError("simulated observation insert failure")
        self.inserted_observations.extend(observations)

    def insert_paper_edges(self, edges):
        self.event_log.append(("insert", "paper_identity_edges", len(edges)))
        self.inserted_paper_edges.extend(edges)

    def insert_author_edges(self, edges):
        self.event_log.append(("insert", "author_identity_edges", len(edges)))
        self.inserted_author_edges.extend(edges)

    def insert_author_entities(self, entities):
        self.event_log.append(("insert", "author_entities", len(entities)))
        self.inserted_entities.extend(entities)

    def get_ingest_state(self, source, *args, **kwargs):
        self.state_calls.append(("read", source, None))
        self.event_log.append(("read", source, None))
        return self.ingest_states.get(source)

    def read_ingest_state(self, source, *args, **kwargs):
        return self.get_ingest_state(source, *args, **kwargs)

    def get_source_ingest_state(self, source, *args, **kwargs):
        return self.get_ingest_state(source, *args, **kwargs)

    def get_min_watermark(self, source):
        self.event_log.append(("min_watermark", source, None))
        return self.min_watermarks.get(source)

    def get_next_watermark(self, source, watermark):
        self.event_log.append(("next_watermark", source, watermark))
        return self.next_watermarks.get(source)

    def upsert_ingest_state(
        self,
        source=None,
        last_watermark=None,
        last_run_id="",
        last_status="",
        last_error="",
        updated_at=None,
        **kwargs,
    ):
        source = source or kwargs.get("source")
        payload = {
            "source": source,
            "source_table": kwargs.get("source_table", f"academic_db.{source}"),
            "watermark_field": kwargs.get("watermark_field", "import_time"),
            "last_watermark": last_watermark
            if last_watermark is not None
            else kwargs.get("watermark"),
            "last_run_id": last_run_id if last_run_id else kwargs.get("run_id", ""),
            "last_status": last_status if last_status else kwargs.get("status", ""),
            "last_error": last_error if last_error else kwargs.get("error", ""),
            "updated_at": updated_at if updated_at is not None else kwargs.get("updated_at"),
        }
        self.state_calls.append(("write", source, payload))
        self.event_log.append(("write", source, payload.get("last_status")))
        previous_state = self.ingest_states.get(source)
        self.ingest_states[source] = IngestState(
            source=source,
            source_table=payload["source_table"] or (previous_state.source_table if previous_state else ""),
            watermark_field=payload["watermark_field"]
            or (previous_state.watermark_field if previous_state else ""),
            last_watermark=payload["last_watermark"]
            if payload["last_watermark"] is not None
            else (previous_state.last_watermark if previous_state else INITIAL_WATERMARK),
            last_run_id=payload["last_run_id"] or (previous_state.last_run_id if previous_state else ""),
            last_status=payload["last_status"] or (previous_state.last_status if previous_state else ""),
            last_error=payload["last_error"] if payload["last_error"] is not None else "",
            updated_at=payload["updated_at"]
            if payload["updated_at"] is not None
            else (previous_state.updated_at if previous_state else datetime(1970, 1, 1, 0, 0, 0)),
        )

    def write_ingest_state(self, source=None, **kwargs):
        self.upsert_ingest_state(source=source, **kwargs)

    def set_ingest_state(self, source=None, **kwargs):
        self.upsert_ingest_state(source=source, **kwargs)

    def fetch_source_rows(self, source, last_watermark, limit, overlap_days, window_end=None):
        self.event_log.append(("fetch", source, last_watermark))
        self.fetch_calls.append((source, last_watermark, limit, overlap_days, window_end))
        if source in self.fail_sources:
            raise RuntimeError(f"simulated fetch failure for source={source}")
        return list(self.source_rows.get(source, []))


class JobTests(unittest.TestCase):
    def test_build_pipeline_run_id_contains_prefix(self):
        run_id = build_pipeline_run_id(datetime(2026, 5, 7, 12, 30, 0))
        self.assertEqual(run_id, "author_aggregation_20260507_123000")

    def test_normalize_datetime_preserves_clickhouse_wall_time(self):
        value = datetime(2026, 5, 7, 12, 30, 0, tzinfo=timezone.utc)
        self.assertEqual(normalize_datetime(value), datetime(2026, 5, 7, 12, 30, 0))

    def test_parse_args_accepts_init_schema_and_limit(self):
        args = parse_args(["--init-schema", "--limit", "100", "--sources", "openalex,arxiv"])
        self.assertTrue(args.init_schema)
        self.assertEqual(args.limit, 100)
        self.assertEqual(args.sources, "openalex,arxiv")
        self.assertEqual(args.window_hours, 24)

    def test_parse_args_accepts_init_source_indexes(self):
        args = parse_args(["--init-source-indexes"])
        self.assertTrue(args.init_source_indexes)

    def test_parse_args_accepts_window_hours(self):
        args = parse_args(["--window-hours", "6"])
        self.assertEqual(args.window_hours, 6)

    def test_parse_source_window_hours_accepts_per_source_overrides(self):
        overrides = parse_source_window_hours("arxiv=168,semantic=0.25")
        self.assertEqual(overrides, {"arxiv": 168.0, "semantic": 0.25})

    def test_parse_source_window_hours_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            parse_source_window_hours("unknown=1")

    def test_init_schema_only_creates_schema_and_dictionary(self):
        repo = FakeRepository()
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.init_schema()
        self.assertTrue(repo.created_schema)
        self.assertTrue(repo.seeded_dictionary)

    def test_run_from_observations_builds_edges_and_entities(self):
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

    def test_run_fetches_selected_sources_and_honors_dry_run(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        repo.source_rows = {
            "openalex": [
                {
                    "author_id": "A1",
                    "author": "Ada Lovelace",
                    "uid": "W1",
                    "doi": "10.1/test",
                    "title": "A Conservative Matching Paper",
                    "rank": 1,
                    "publication_date": "2026-01-01",
                    "import_time": now,
                }
            ],
            "semantic": [
                {
                    "author_id": "S1",
                    "author": "Ada Lovelace",
                    "uid": "S1",
                    "doi": "10.1/test",
                    "title": "A Conservative Matching Paper",
                    "rank": 1,
                    "publication_date": "2026-01-01",
                    "year": 2026,
                    "import_time": now,
                }
            ],
        }
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")

        metrics = job.run(
            sources=["openalex", "semantic"],
            last_watermark=datetime(2026, 5, 1, 0, 0, 0),
            timestamp=now,
            limit=100,
            overlap_days=2,
            dry_run=True,
        )

        self.assertEqual([call[0] for call in repo.fetch_calls], ["openalex", "semantic"])
        self.assertEqual(metrics["observations"], 2)
        self.assertEqual(metrics["paper_edges"], 1)
        self.assertEqual(metrics["author_edges"], 1)
        self.assertEqual(metrics["entities"], 1)
        self.assertEqual(metrics["observations_by_source"], {"openalex": 1, "semantic": 1})
        self.assertEqual(len(repo.inserted_observations), 0)
        self.assertEqual(len(repo.inserted_paper_edges), 0)
        self.assertEqual(len(repo.inserted_author_edges), 0)
        self.assertEqual(len(repo.inserted_entities), 0)

    def test_run_reads_last_watermark_per_source_with_default_fallback(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        openalex_watermark = datetime(2026, 5, 6, 8, 30, 0)
        repo.ingest_states["openalex"] = IngestState(
            source="openalex",
            source_table="academic_db.OpenAlex",
            watermark_field="import_time",
            last_watermark=openalex_watermark,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 6, 8, 30, 0),
        )

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["openalex", "semantic"],
            timestamp=now,
            dry_run=True,
            window_hours=0,
        )

        watermarks = {source: value for source, value, *_ in repo.fetch_calls}
        self.assertEqual(watermarks["openalex"], openalex_watermark)
        self.assertEqual(watermarks["semantic"], INITIAL_WATERMARK)

    def test_run_uses_source_min_watermark_when_state_field_changed(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        old_arxiv_watermark = datetime(2026, 4, 23, 0, 0, 0)
        min_arxiv_watermark = datetime(2000, 1, 1, 0, 0, 0)
        repo.ingest_states["arxiv"] = IngestState(
            source="arxiv",
            source_table="academic_db.arxiv",
            watermark_field="toDateTime(import_date)",
            last_watermark=old_arxiv_watermark,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 1, 0, 0, 0),
        )
        repo.min_watermarks["arxiv"] = min_arxiv_watermark

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["arxiv"],
            timestamp=now,
            dry_run=True,
            window_hours=24,
        )

        self.assertEqual(repo.fetch_calls[0][1], min_arxiv_watermark)
        self.assertEqual(repo.fetch_calls[0][4], datetime(2000, 1, 2, 0, 0, 0))

    def test_run_uses_source_min_watermark_when_state_is_before_source_min(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        state_watermark = datetime(2026, 4, 21, 7, 52, 56)
        min_watermark = datetime(2026, 4, 21, 15, 52, 53)
        repo.ingest_states["dblp"] = IngestState(
            source="dblp",
            source_table="academic_db.dblp",
            watermark_field="created_at",
            last_watermark=state_watermark,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 1, 0, 0, 0),
        )
        repo.min_watermarks["dblp"] = min_watermark

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["dblp"],
            timestamp=now,
            dry_run=True,
            window_hours=1,
        )

        self.assertEqual(repo.fetch_calls[0][1], min_watermark)
        self.assertEqual(repo.fetch_calls[0][4], datetime(2026, 4, 21, 16, 52, 53))

    def test_run_skips_to_next_available_source_watermark(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        state_watermark = datetime(2026, 4, 22, 12, 33, 55)
        next_watermark = datetime(2026, 4, 22, 16, 57, 40)
        repo.ingest_states["openalex"] = IngestState(
            source="openalex",
            source_table="academic_db.OpenAlex",
            watermark_field="import_time",
            last_watermark=state_watermark,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 1, 0, 0, 0),
        )
        repo.next_watermarks["openalex"] = next_watermark

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["openalex"],
            timestamp=now,
            dry_run=True,
            window_hours=1,
        )

        self.assertEqual(repo.fetch_calls[0][1], next_watermark)
        self.assertEqual(repo.fetch_calls[0][4], datetime(2026, 4, 22, 17, 57, 40))

    def test_run_uses_per_source_window_hours(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        openalex_watermark = datetime(2026, 5, 1, 0, 0, 0)
        semantic_watermark = datetime(2026, 5, 2, 0, 0, 0)
        repo.ingest_states["openalex"] = IngestState(
            source="openalex",
            source_table="academic_db.OpenAlex",
            watermark_field="import_time",
            last_watermark=openalex_watermark,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 1, 0, 0, 0),
        )
        repo.ingest_states["semantic"] = IngestState(
            source="semantic",
            source_table="academic_db.semantic",
            watermark_field="import_time",
            last_watermark=semantic_watermark,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 2, 0, 0, 0),
        )

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["openalex", "semantic"],
            timestamp=now,
            dry_run=True,
            window_hours=24,
            source_window_hours={"openalex": 6, "semantic": 0.5},
        )

        self.assertEqual(repo.fetch_calls[0][4], datetime(2026, 5, 1, 6, 0, 0))
        self.assertEqual(repo.fetch_calls[1][4], datetime(2026, 5, 2, 0, 30, 0))

    def test_run_writes_running_state_before_fetching_each_source(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")

        job.run(
            sources=["openalex"],
            last_watermark=datetime(2026, 1, 1, 0, 0, 0),
            timestamp=now,
            dry_run=True,
            window_hours=0,
        )

        running_write_indexes = [
            idx
            for idx, event in enumerate(repo.event_log)
            if event[0] == "write" and event[1] == "openalex" and event[2] == "running"
        ]
        fetch_indexes = [
            idx
            for idx, event in enumerate(repo.event_log)
            if event[0] == "fetch" and event[1] == "openalex"
        ]
        self.assertTrue(running_write_indexes, "expected running status write before fetch")
        self.assertTrue(fetch_indexes, "expected fetch event for source")
        self.assertLess(running_write_indexes[0], fetch_indexes[0])

    def test_run_writes_success_and_advances_watermark_from_source_data(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        openalex_old = datetime(2026, 5, 1, 0, 0, 0)
        semantic_old = datetime(2026, 5, 2, 0, 0, 0)
        repo.ingest_states["openalex"] = IngestState(
            source="openalex",
            source_table="academic_db.OpenAlex",
            watermark_field="import_time",
            last_watermark=openalex_old,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 1, 0, 0, 0),
        )
        repo.ingest_states["semantic"] = IngestState(
            source="semantic",
            source_table="academic_db.semantic",
            watermark_field="import_time",
            last_watermark=semantic_old,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 2, 0, 0, 0),
        )
        repo.source_rows = {
            "openalex": [
                {
                    "author_id": "A1",
                    "author": "Ada Lovelace",
                    "uid": "W1",
                    "doi": "10.1/test",
                    "title": "A Conservative Matching Paper",
                    "rank": 1,
                    "publication_date": "2026-01-01",
                    "import_time": datetime(2026, 5, 7, 8, 0, 0),
                },
                {
                    "author_id": "A2",
                    "author": "Ada Lovelace",
                    "uid": "W2",
                    "doi": "10.1/test-2",
                    "title": "A Conservative Matching Paper II",
                    "rank": 1,
                    "publication_date": "2026-01-02",
                    "import_time": datetime(2026, 5, 7, 9, 30, 0),
                },
            ],
            "semantic": [],
        }

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["openalex", "semantic"],
            last_watermark=datetime(2026, 1, 1, 0, 0, 0),
            timestamp=now,
            dry_run=True,
            window_hours=0,
        )

        self.assertEqual(repo.ingest_states["openalex"].last_status, "success")
        self.assertEqual(
            repo.ingest_states["openalex"].last_watermark,
            datetime(2026, 5, 7, 9, 30, 0),
        )
        self.assertEqual(repo.ingest_states["semantic"].last_status, "success")
        self.assertEqual(repo.ingest_states["semantic"].last_watermark, semantic_old)

    def test_run_window_mode_advances_to_window_end_without_rows(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        source_watermark = datetime(2026, 5, 1, 0, 0, 0)
        repo.ingest_states["openalex"] = IngestState(
            source="openalex",
            source_table="academic_db.OpenAlex",
            watermark_field="import_time",
            last_watermark=source_watermark,
            last_run_id="run-old",
            last_status="success",
            last_error="",
            updated_at=datetime(2026, 5, 1, 0, 0, 0),
        )

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["openalex"],
            timestamp=now,
            dry_run=True,
            window_hours=6,
        )

        self.assertEqual(
            repo.fetch_calls[0],
            ("openalex", source_watermark, None, 2, datetime(2026, 5, 1, 6, 0, 0)),
        )
        self.assertEqual(repo.ingest_states["openalex"].last_status, "success")
        self.assertEqual(repo.ingest_states["openalex"].last_watermark, datetime(2026, 5, 1, 6, 0, 0))

    def test_run_writes_failed_state_and_continues_other_sources(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        repo.fail_sources.add("semantic")
        repo.source_rows = {
            "openalex": [
                {
                    "author_id": "A1",
                    "author": "Ada Lovelace",
                    "uid": "W1",
                    "doi": "10.1/test",
                    "title": "A Conservative Matching Paper",
                    "rank": 1,
                    "publication_date": "2026-01-01",
                    "import_time": now,
                }
            ]
        }

        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        metrics = job.run(
            sources=["semantic", "openalex"],
            last_watermark=datetime(2026, 1, 1, 0, 0, 0),
            timestamp=now,
            dry_run=True,
            window_hours=0,
        )

        self.assertEqual(repo.ingest_states["semantic"].last_status, "failed")
        self.assertIn("simulated fetch failure", repo.ingest_states["semantic"].last_error)
        self.assertEqual(repo.ingest_states["openalex"].last_status, "success")
        self.assertEqual(metrics["observations_by_source"].get("semantic"), 0)
        self.assertEqual(metrics["observations_by_source"].get("openalex"), 1)
        self.assertEqual(metrics["observations"], 1)

    def test_run_dry_run_keeps_data_tables_unchanged_but_writes_state(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        repo.source_rows = {
            "openalex": [
                {
                    "author_id": "A1",
                    "author": "Ada Lovelace",
                    "uid": "W1",
                    "doi": "10.1/test",
                    "title": "A Conservative Matching Paper",
                    "rank": 1,
                    "publication_date": "2026-01-01",
                    "import_time": now,
                }
            ]
        }
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        metrics = job.run(
            sources=["openalex"],
            last_watermark=datetime(2026, 1, 1, 0, 0, 0),
            timestamp=now,
            dry_run=True,
            window_hours=0,
        )

        self.assertEqual(len(repo.inserted_observations), 0)
        self.assertEqual(len(repo.inserted_paper_edges), 0)
        self.assertEqual(len(repo.inserted_author_edges), 0)
        self.assertEqual(len(repo.inserted_entities), 0)
        self.assertEqual(repo.ingest_states["openalex"].last_status, "success")
        running_events = [
            event
            for event in repo.event_log
            if event[0] == "write" and event[1] == "openalex" and event[2] == "running"
        ]
        success_events = [
            event
            for event in repo.event_log
            if event[0] == "write" and event[1] == "openalex" and event[2] == "success"
        ]
        self.assertTrue(running_events)
        self.assertTrue(success_events)
        self.assertTrue(metrics["dry_run"])

    def test_run_writes_success_state_after_data_insert(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        repo.source_rows = {
            "openalex": [
                {
                    "author_id": "A1",
                    "author": "Ada Lovelace",
                    "uid": "W1",
                    "doi": "10.1/test",
                    "title": "A Conservative Matching Paper",
                    "rank": 1,
                    "publication_date": "2026-01-01",
                    "import_time": now,
                }
            ]
        }
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")
        job.run(
            sources=["openalex"],
            last_watermark=datetime(2026, 1, 1, 0, 0, 0),
            timestamp=now,
            dry_run=False,
            window_hours=0,
        )

        insert_index = next(
            idx for idx, event in enumerate(repo.event_log) if event[0] == "insert"
        )
        success_index = next(
            idx
            for idx, event in enumerate(repo.event_log)
            if event[0] == "write" and event[1] == "openalex" and event[2] == "success"
        )
        self.assertLess(insert_index, success_index)

    def test_run_marks_fetched_sources_failed_when_data_insert_fails(self):
        now = datetime(2026, 5, 7, 12, 0, 0)
        repo = FakeRepository()
        repo.fail_insert_observations = True
        repo.source_rows = {
            "openalex": [
                {
                    "author_id": "A1",
                    "author": "Ada Lovelace",
                    "uid": "W1",
                    "doi": "10.1/test",
                    "title": "A Conservative Matching Paper",
                    "rank": 1,
                    "publication_date": "2026-01-01",
                    "import_time": now,
                }
            ]
        }
        job = AuthorAggregationJob(repository=repo, pipeline_run_id="run-test")

        with self.assertRaises(RuntimeError):
            job.run(
                sources=["openalex"],
                last_watermark=datetime(2026, 1, 1, 0, 0, 0),
                timestamp=now,
                dry_run=False,
                window_hours=0,
            )

        self.assertEqual(repo.ingest_states["openalex"].last_status, "failed")
        self.assertIn("simulated observation insert failure", repo.ingest_states["openalex"].last_error)


if __name__ == "__main__":
    unittest.main()
