from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "dashboard" / "index.html"
API_SERVER = REPO_ROOT / "dashboard" / "api_server.py"
CONFIG = REPO_ROOT / "dashboard" / "config.py"


class DashboardStaticTests(unittest.TestCase):
    def test_dashboard_defaults_to_all_source(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        config = CONFIG.read_text(encoding="utf-8")

        self.assertIn('<option value="all" selected>全部数据</option>', html)
        self.assertIn("let currentDataSource = 'all'", html)
        self.assertIn("DEFAULT_TABLE = 'all'", config)

    def test_dashboard_ignores_stale_data_source_responses(self):
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("let latestDataRequestId = 0", html)
        self.assertIn("requestId !== latestDataRequestId", html)

    def test_dashboard_renders_patent_cpc_distribution(self):
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("data.source === 'patents'", html)
        self.assertIn("data.ccf_class_distribution", html)
        self.assertIn("renderCategoryChart(data.ccf_class_distribution", html)

    def test_dashboard_uses_patent_specific_labels(self):
        html = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("papers: '总专利数'", html)
        self.assertIn("authors: '发明人总数'", html)
        self.assertIn("journalChartTitle: 'TOP 50 权利人分布'", html)
        self.assertIn("papersTrendTitle: '专利授权趋势'", html)
        self.assertIn("setStatCardLabel('totalPapers'", html)
        self.assertIn("setChartHeader('journalDistCard'", html)

    def test_dashboard_cache_warmup_is_opt_in(self):
        server = API_SERVER.read_text(encoding="utf-8")

        self.assertIn("DASHBOARD_PRELOAD_CACHE", server)
        self.assertIn("DASHBOARD_REFRESH_CACHE", server)
        self.assertIn("if PRELOAD_CACHE:", server)

    def test_arxiv_uses_shared_cache_manager(self):
        server = API_SERVER.read_text(encoding="utf-8")

        self.assertIn("cache_manager.get_source_data('arxiv')", server)
        self.assertIn("cache_manager.get_stale_source_data('arxiv')", server)
        self.assertIn("cache_manager.set_source_data('arxiv'", server)


if __name__ == "__main__":
    unittest.main()
