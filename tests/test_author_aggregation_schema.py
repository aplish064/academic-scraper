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
            row for row in rows if row["table_name"] == "author_observations" and row["column_name"] == "source"
        ]
        self.assertEqual(len(source_rows), 1)
        self.assertTrue(source_rows[0]["used_for_matching"])
        self.assertIn("openalex", source_rows[0]["description"])


if __name__ == "__main__":
    unittest.main()
