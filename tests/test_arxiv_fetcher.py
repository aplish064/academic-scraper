import sys
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace


if "feedparser" not in sys.modules:
    sys.modules["feedparser"] = types.SimpleNamespace(parse=lambda *_args, **_kwargs: types.SimpleNamespace(entries=[]))

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)

if "tqdm" not in sys.modules:
    class _DummyTqdm:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self, *_args, **_kwargs):
            pass

        def set_postfix_str(self, *_args, **_kwargs):
            pass

    sys.modules["tqdm"] = types.SimpleNamespace(tqdm=_DummyTqdm)

from src import arxiv_fetcher


class ArxivFetcherTests(unittest.TestCase):
    def test_make_request_includes_user_agent_header(self):
        fake_response = SimpleNamespace(status_code=200, text="<feed></feed>")
        with patch.object(arxiv_fetcher.requests, "get", return_value=fake_response) as mocked_get:
            result = arxiv_fetcher.make_request("https://export.arxiv.org/api/query", {"search_query": "all:test"})

        self.assertEqual(result, "<feed></feed>")
        _, kwargs = mocked_get.call_args
        self.assertIn("headers", kwargs)
        self.assertIn("User-Agent", kwargs["headers"])
        self.assertIn("academic-scraper", kwargs["headers"]["User-Agent"])

    def test_build_last_updated_date_query_uses_full_day_bounds(self):
        query = arxiv_fetcher.build_last_updated_date_query("2026-04-21")
        self.assertEqual(query, "lastUpdatedDate:[202604210000 TO 202604212359]")

    def test_build_date_query_defaults_to_submitted_date(self):
        query = arxiv_fetcher.build_date_query("2026-04-21")
        self.assertEqual(query, "submittedDate:[202604210000 TO 202604212359]")

    def test_get_dates_in_window_inclusive_descending(self):
        dates = arxiv_fetcher.get_dates_in_window("2026-04-18", "2026-04-20")
        self.assertEqual(dates, ["2026-04-20", "2026-04-19", "2026-04-18"])

    def test_get_dates_in_window_accepts_reverse_input(self):
        dates = arxiv_fetcher.get_dates_in_window("2026-04-20", "2026-04-18")
        self.assertEqual(dates, ["2026-04-20", "2026-04-19", "2026-04-18"])

    def test_compute_recovery_wait_seconds_grows_with_attempt(self):
        with patch.object(arxiv_fetcher.random, "uniform", return_value=1.0):
            wait1 = arxiv_fetcher.compute_recovery_wait_seconds(0, base_wait=10, max_wait=120)
            wait2 = arxiv_fetcher.compute_recovery_wait_seconds(2, base_wait=10, max_wait=120)

        self.assertEqual(wait1, 10)
        self.assertEqual(wait2, 40)

    def test_compute_recovery_wait_seconds_honors_max_wait(self):
        with patch.object(arxiv_fetcher.random, "uniform", return_value=1.2):
            wait = arxiv_fetcher.compute_recovery_wait_seconds(6, base_wait=30, max_wait=300)
        self.assertLessEqual(wait, 300)

    def test_window_mode_refetches_all_dates_by_default(self):
        fetcher = arxiv_fetcher.ArxivFetcher(
            start_date="2026-04-22",
            end_year=1990,
            ch_client=object(),
            dry_run=True,
            from_date="2026-04-18",
            to_date="2026-04-20",
        )
        fetcher.progress = {
            "start_date": "2026-04-22",
            "end_year": 1990,
            "total_dates": 0,
            "completed_dates": ["20260419"],
            "last_updated": None
        }
        called_dates = []

        def _fake_fetch(date_str, *_args, **_kwargs):
            called_dates.append(date_str)
            return True

        with patch.object(arxiv_fetcher, "create_arxiv_table"), \
                patch.object(arxiv_fetcher, "fetch_papers_by_date", side_effect=_fake_fetch):
            fetcher.run()

        self.assertEqual(called_dates, ["2026-04-20", "2026-04-19", "2026-04-18"])

    def test_build_dedup_insert_sql_uses_anti_join_and_excludes_import_date(self):
        sql = arxiv_fetcher.build_dedup_insert_sql("temp_x")

        self.assertIn("LEFT ANTI JOIN", sql)
        self.assertIn(f"{arxiv_fetcher.CH_DATABASE}.{arxiv_fetcher.CH_TABLE} tgt", sql)
        self.assertIn("tmp.arxiv_id = tgt.arxiv_id", sql)
        self.assertIn("tmp.rank = tgt.rank", sql)
        self.assertNotIn("tmp.import_date = tgt.import_date", sql)

    def test_dedup_key_columns_do_not_include_import_date(self):
        self.assertNotIn("import_date", arxiv_fetcher.DEDUP_KEY_COLUMNS)

    def test_fetch_papers_by_date_marks_empty_day_as_completed(self):
        progress = arxiv_fetcher.get_empty_progress()

        with patch.object(arxiv_fetcher, "make_request", return_value="<feed></feed>"), \
                patch.object(arxiv_fetcher, "parse_arxiv_xml", return_value=[]), \
                patch.object(arxiv_fetcher, "save_progress") as mocked_save:
            ok = arxiv_fetcher.fetch_papers_by_date(
                "2026-04-21",
                progress,
                ch_client=object(),
                per_page=50,
                request_interval=0,
            )

        self.assertTrue(ok)
        self.assertIn("20260421", progress["completed_dates"])
        mocked_save.assert_called_once()

    def test_fetch_papers_by_date_respects_custom_per_page_and_query(self):
        progress = arxiv_fetcher.get_empty_progress()
        captured_params = []

        def _fake_make_request(_url, params):
            captured_params.append(params)
            return "<feed></feed>"

        with patch.object(arxiv_fetcher, "make_request", side_effect=_fake_make_request), \
                patch.object(arxiv_fetcher, "parse_arxiv_xml", return_value=[]), \
                patch.object(arxiv_fetcher, "save_progress"):
            ok = arxiv_fetcher.fetch_papers_by_date(
                "2026-04-21",
                progress,
                ch_client=object(),
                per_page=123,
                request_interval=0,
            )

        self.assertTrue(ok)
        self.assertEqual(captured_params[0]["max_results"], 123)
        self.assertEqual(captured_params[0]["search_query"], "submittedDate:[202604210000 TO 202604212359]")

    def test_fetch_papers_by_date_dry_run_skips_database_insert(self):
        progress = arxiv_fetcher.get_empty_progress()
        papers = [{
            "arxiv_id": "1234.56789",
            "uid": "http://arxiv.org/abs/1234.56789v1",
            "title": "Test Paper",
            "published": "2026-04-21T00:00:00Z",
            "updated": "2026-04-21T12:00:00Z",
            "authors": [{"name": "A", "affiliation": ""}],
            "categories": ["cs.AI"],
            "primary_category": "cs.AI",
            "journal_ref": "",
            "comment": "",
            "url": "http://arxiv.org/abs/1234.56789v1",
            "pdf_url": "http://arxiv.org/pdf/1234.56789v1",
        }]

        with patch.object(arxiv_fetcher, "make_request", return_value="<feed></feed>"), \
                patch.object(arxiv_fetcher, "parse_arxiv_xml", side_effect=[papers, []]), \
                patch.object(arxiv_fetcher, "batch_insert_clickhouse") as mocked_insert, \
                patch.object(arxiv_fetcher, "save_progress"):
            ok = arxiv_fetcher.fetch_papers_by_date(
                "2026-04-21",
                progress,
                ch_client=object(),
                per_page=50,
                request_interval=0,
                dry_run=True,
            )

        self.assertTrue(ok)
        mocked_insert.assert_not_called()
        self.assertIn("20260421", progress["completed_dates"])


if __name__ == "__main__":
    unittest.main()
