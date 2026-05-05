import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from dashboard.adapters.patents import PatentsAdapter
from dashboard.adapters.openalex import OpenAlexAdapter
from dashboard.adapters.dblp import DBLPAdapter
from dashboard.utils.query_builder import QueryBuilder


class DashboardPatentQueryTests(unittest.TestCase):
    def test_patent_statistics_uses_table_count_for_total_patents(self):
        sql = PatentsAdapter().get_statistics_sql()

        self.assertIn("SELECT count() FROM patent_db.patents", sql)
        self.assertNotIn("count(DISTINCT patent_id) FROM patent_db.patents", sql)

    def test_patent_date_and_citation_queries_use_row_count(self):
        adapter = PatentsAdapter()
        builder = QueryBuilder(lambda: None)

        date_sql = builder.build_date_query(adapter)
        citation_sql = builder.build_citation_distribution_query(adapter)

        self.assertIn("count() as count", date_sql)
        self.assertIn("count() as count", citation_sql)
        self.assertNotIn("count(DISTINCT patent_id)", date_sql)
        self.assertNotIn("count(DISTINCT patent_id)", citation_sql)

    def test_patent_cpc_distribution_uses_row_count(self):
        aggregator_source = (DASHBOARD_DIR / "services" / "data_aggregator.py").read_text(encoding="utf-8")

        self.assertIn("SELECT cpc_group, count() AS count", aggregator_source)
        self.assertNotIn("SELECT cpc_group, count(DISTINCT patent_id) AS count", aggregator_source)


class DashboardPaperSourceQueryTests(unittest.TestCase):
    def test_openalex_statistics_uses_fast_author_and_institution_estimators(self):
        sql = OpenAlexAdapter().get_statistics_sql()

        self.assertIn("uniq(cityHash64(author_id))", sql)
        self.assertIn("uniq(institution_name)", sql)
        self.assertNotIn("uniqHLL12(author_id)", sql)
        self.assertNotIn("uniqHLL12(institution_name)", sql)
        self.assertIn("SETTINGS max_threads=16", sql)

    def test_dblp_statistics_uses_subqueries_with_parallel_threads(self):
        sql = DBLPAdapter().get_statistics_sql()

        self.assertIn("SELECT uniqHLL12(doi)", sql)
        self.assertIn("SELECT uniqHLL12(author_name)", sql)
        self.assertIn("SETTINGS max_threads=4", sql)

    def test_non_patent_trend_and_citation_queries_use_parallel_threads(self):
        adapter = OpenAlexAdapter()
        builder = QueryBuilder(lambda: None)

        self.assertIn("SETTINGS max_threads=8", builder.build_date_query(adapter))
        self.assertIn("SETTINGS max_threads=8", builder.build_citation_distribution_query(adapter))


if __name__ == "__main__":
    unittest.main()
