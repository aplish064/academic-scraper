import unittest
from datetime import date, datetime

from src.author_aggregation import source_mappers


RUN_ID = "run-test"
NOW = datetime(2026, 5, 7, 11, 0, 0)


class SourceMapperTests(unittest.TestCase):
    def test_parse_date_out_of_clickhouse_date_range_returns_none(self):
        self.assertIsNone(source_mappers.parse_date("1936-12-31"))
        self.assertIsNone(source_mappers.parse_date("2200-01-01"))

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

    def test_map_openalex_row_keeps_year_when_publication_date_out_of_range(self):
        row = {
            "author_id": "A1",
            "author": "Ada Lovelace",
            "uid": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1000/XYZ",
            "title": "A Conservative Matching Paper",
            "rank": 1,
            "publication_date": "1936-12-31",
            "import_time": NOW,
        }
        obs = source_mappers.map_openalex_row(row, RUN_ID, NOW)
        self.assertIsNone(obs.publication_date)
        self.assertEqual(obs.publication_year, 1936)

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
