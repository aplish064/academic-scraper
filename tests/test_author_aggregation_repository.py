import unittest
from datetime import datetime

from src.author_aggregation import repository
from src.author_aggregation.models import AuthorObservation


class RepositorySqlTests(unittest.TestCase):
    def test_source_query_for_arxiv_uses_overlap_days(self):
        start = datetime(2026, 5, 7, 12, 0, 0)
        sql = repository.build_source_extract_sql("arxiv", start, limit=100, overlap_days=2)
        self.assertIn("FROM academic_db.arxiv", sql)
        self.assertIn("updated", sql)
        self.assertIn("LIMIT 100", sql)
        self.assertIn("2026-05-05", sql)

    def test_source_query_for_openalex_uses_import_time(self):
        start = datetime(2026, 5, 7, 12, 0, 0)
        sql = repository.build_source_extract_sql("openalex", start, limit=100, overlap_days=2)
        self.assertIn("FROM academic_db.OpenAlex", sql)
        self.assertIn("import_time >=", sql)
        self.assertIn("LIMIT 100", sql)

    def test_source_query_uses_window_end_when_supplied(self):
        start = datetime(2026, 5, 7, 12, 0, 0)
        end = datetime(2026, 5, 7, 18, 0, 0)
        sql = repository.build_source_extract_sql(
            "semantic",
            start,
            limit=None,
            overlap_days=2,
            window_end=end,
        )
        self.assertIn("import_time >= toDateTime('2026-05-07 12:00:00')", sql)
        self.assertIn("import_time < toDateTime('2026-05-07 18:00:00')", sql)
        self.assertNotIn("LIMIT", sql)

    def test_ingest_state_query_prefers_successful_watermark(self):
        fake = FakeClickHouseClient()
        repo = repository.AuthorAggregationRepository(fake)

        repo.get_ingest_state("openalex")

        self.assertIn("if(last_status = 'success', 0, 1)", fake.queries[0])

    def test_min_watermark_query_uses_source_watermark_field(self):
        fake = FakeClickHouseClient()
        fake.next_query_result = FakeQueryResult(
            column_names=["min(updated)"],
            result_rows=[(datetime(2000, 1, 1, 0, 0, 0),)],
        )
        repo = repository.AuthorAggregationRepository(fake)

        value = repo.get_min_watermark("arxiv")

        self.assertEqual(value, datetime(2000, 1, 1, 0, 0, 0))
        self.assertIn("min(updated)", fake.queries[0])
        self.assertIn("FROM academic_db.arxiv", fake.queries[0])

    def test_next_watermark_query_uses_current_watermark_lower_bound(self):
        fake = FakeClickHouseClient()
        fake.next_query_result = FakeQueryResult(
            column_names=["min(import_time)"],
            result_rows=[(datetime(2026, 4, 22, 16, 57, 40),)],
        )
        repo = repository.AuthorAggregationRepository(fake)

        value = repo.get_next_watermark("openalex", datetime(2026, 4, 22, 12, 33, 55))

        self.assertEqual(value, datetime(2026, 4, 22, 16, 57, 40))
        self.assertIn("import_time >= toDateTime('2026-04-22 12:33:55')", fake.queries[0])

    def test_observation_insert_sql_anti_joins_source_row_key(self):
        sql = repository.build_observation_insert_sql("temp_author_observations")
        self.assertIn("LEFT ANTI JOIN authors_db.author_observations", sql)
        self.assertIn("tmp.source_row_key = tgt.source_row_key", sql)


class FakeQueryResult:
    def __init__(self, column_names, result_rows):
        self.column_names = column_names
        self.result_rows = result_rows


class FakeClickHouseClient:
    def __init__(self):
        self.commands = []
        self.inserted = []
        self.queries = []
        self.next_query_result = FakeQueryResult([], [])

    def command(self, sql):
        self.commands.append(sql)

    def insert(self, table, rows, column_names=None):
        self.inserted.append((table, rows, column_names))

    def query(self, sql):
        self.queries.append(sql)
        return self.next_query_result


class RepositoryCommandTests(unittest.TestCase):
    def test_create_schema_executes_all_ddls(self):
        fake = FakeClickHouseClient()
        repo = repository.AuthorAggregationRepository(fake)
        repo.create_schema()
        self.assertGreaterEqual(len(fake.commands), 7)
        self.assertIn("CREATE DATABASE IF NOT EXISTS authors_db", fake.commands[0])

    def test_fetch_source_rows_returns_dict_rows(self):
        fake = FakeClickHouseClient()
        fake.next_query_result = FakeQueryResult(
            column_names=["uid", "author", "rank"],
            result_rows=[("W1", "Ada", 1), ("W2", "Grace", 2)],
        )
        repo = repository.AuthorAggregationRepository(fake)

        rows = repo.fetch_source_rows("openalex", datetime(2026, 5, 7, 12, 0, 0), limit=10, overlap_days=2)

        self.assertEqual(
            rows,
            [
                {"uid": "W1", "author": "Ada", "rank": 1},
                {"uid": "W2", "author": "Grace", "rank": 2},
            ],
        )
        self.assertEqual(len(fake.queries), 1)

    def test_ensure_source_watermark_indexes_adds_and_materializes_indexes(self):
        fake = FakeClickHouseClient()
        repo = repository.AuthorAggregationRepository(fake)

        repo.ensure_source_watermark_indexes(materialize=True)

        joined = "\n".join(fake.commands)
        self.assertIn("ADD INDEX IF NOT EXISTS idx_author_aggregation_openalex_watermark import_time", joined)
        self.assertIn("ADD INDEX IF NOT EXISTS idx_author_aggregation_arxiv_watermark updated", joined)
        self.assertIn("MATERIALIZE INDEX idx_author_aggregation_openalex_watermark", joined)

    def test_insert_observations_creates_temp_table_and_inserts_rows(self):
        fake = FakeClickHouseClient()
        repo = repository.AuthorAggregationRepository(fake)
        observation = AuthorObservation(
            observation_id=1,
            source="openalex",
            source_row_key="openalex:W1:1:A1",
            source_paper_id="W1",
            source_author_id="A1",
            author_name="Ada",
            normalized_author_name="ada",
            author_rank=1,
            author_role="first",
            doi="10.1000/xyz",
            arxiv_id="",
            dblp_key="",
            semantic_id="",
            openalex_id="W1",
            title="A Paper",
            normalized_title="a paper",
            publication_date=None,
            publication_year=2026,
            venue="Venue",
            institution_id="I1",
            institution_name="Inst",
            institution_country="US",
            raw_affiliation="Inst",
            citation_count=0,
            fwci=0.0,
            primary_topic="",
            ccf_class="",
            source_import_time=datetime(2026, 5, 7, 12, 0, 0),
            observed_at=datetime(2026, 5, 7, 12, 0, 0),
            pipeline_run_id="run-test",
        )

        repo.insert_observations([observation])

        self.assertEqual(len(fake.inserted), 1)
        table, rows, column_names = fake.inserted[0]
        self.assertEqual(table, "authors_db.temp_author_observations")
        self.assertEqual(len(rows), 1)
        self.assertEqual(column_names[0], "observation_id")
        self.assertIn("DROP TABLE IF EXISTS authors_db.temp_author_observations", fake.commands[0])


if __name__ == "__main__":
    unittest.main()
