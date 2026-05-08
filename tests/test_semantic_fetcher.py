import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import semantic_fetcher


class SemanticFetcherTests(unittest.TestCase):
    def test_should_stop_for_offset(self):
        self.assertFalse(semantic_fetcher.should_stop_for_offset(0, 100))
        self.assertFalse(semantic_fetcher.should_stop_for_offset(9, 100))
        self.assertTrue(semantic_fetcher.should_stop_for_offset(10, 100))

    def test_make_request_http_400_returns_none_without_retry(self):
        response = SimpleNamespace(status_code=400, text="Bad Request", headers={})
        with patch.object(semantic_fetcher.session, "get", return_value=response) as mocked_get:
            data, error = semantic_fetcher.make_request("https://example.com", {"q": "x"})

        self.assertIsNone(data)
        self.assertEqual(error, "http_400")
        self.assertEqual(mocked_get.call_count, 1)

    def test_make_request_429_then_200(self):
        response_429 = SimpleNamespace(status_code=429, text="", headers={"Retry-After": "1"})
        response_200 = SimpleNamespace(status_code=200, text="", headers={}, json=lambda: {"data": [1]})
        with patch.object(semantic_fetcher.session, "get", side_effect=[response_429, response_200]) as mocked_get, \
                patch.object(semantic_fetcher.time, "sleep") as mocked_sleep:
            data, error = semantic_fetcher.make_request("https://example.com", {"q": "x"})

        self.assertEqual(data, {"data": [1]})
        self.assertIsNone(error)
        self.assertEqual(mocked_get.call_count, 2)
        mocked_sleep.assert_called_once_with(1)

    def test_flush_buffered_rows_success(self):
        rows = [{"uid": "1"}, {"uid": "2"}]
        with patch.object(semantic_fetcher, "batch_insert_clickhouse", return_value=True):
            ok, papers, row_count = semantic_fetcher.flush_buffered_rows(
                ch_client=object(),
                buffered_rows=rows,
                buffered_papers=2,
                journal_name="Demo Journal",
            )
        self.assertTrue(ok)
        self.assertEqual(papers, 2)
        self.assertEqual(row_count, 2)

    def test_fetch_papers_by_journal_buffers_then_flushes_once(self):
        progress = semantic_fetcher.get_empty_progress()
        semantic_fetcher.update_journal_progress(progress, "Demo Journal", status="valid", query_type="query")

        papers_page_1 = [{"paperId": "p1", "externalIds": {}, "authors": []}]
        papers_page_2 = [{"paperId": "p2", "externalIds": {}, "authors": []}]
        responses = [
            ({"data": papers_page_1}, None),
            ({"data": papers_page_2}, None),
            ({"data": []}, None),
        ]

        with patch.object(semantic_fetcher, "make_request", side_effect=responses), \
                patch.object(semantic_fetcher, "paper_to_rows", side_effect=[[{"uid": "p1"}], [{"uid": "p2"}]]), \
                patch.object(semantic_fetcher, "batch_insert_clickhouse", return_value=True) as mocked_insert, \
                patch.object(semantic_fetcher, "save_progress"), \
                patch.object(semantic_fetcher.time, "sleep"):
            original_flush_rows = semantic_fetcher.INSERT_FLUSH_ROWS
            semantic_fetcher.INSERT_FLUSH_ROWS = 10
            try:
                total_papers, total_rows = semantic_fetcher.fetch_papers_by_journal(
                    "Demo Journal",
                    query_type="query",
                    start_page=0,
                    progress_data=progress,
                    ch_client=object(),
                )
            finally:
                semantic_fetcher.INSERT_FLUSH_ROWS = original_flush_rows

        self.assertEqual(total_papers, 2)
        self.assertEqual(total_rows, 2)
        self.assertEqual(mocked_insert.call_count, 1)

    def test_fetch_papers_http_400_after_pages_flushes_and_completes(self):
        progress = semantic_fetcher.get_empty_progress()
        semantic_fetcher.update_journal_progress(progress, "Demo Journal", status="valid", query_type="query")

        papers_page_1 = [{"paperId": "p1", "externalIds": {}, "authors": []}]
        responses = [
            ({"data": papers_page_1}, None),
            (None, "http_400"),
        ]

        with patch.object(semantic_fetcher, "make_request", side_effect=responses), \
                patch.object(semantic_fetcher, "paper_to_rows", side_effect=[[{"uid": "p1"}]]), \
                patch.object(semantic_fetcher, "batch_insert_clickhouse", return_value=True) as mocked_insert, \
                patch.object(semantic_fetcher, "save_progress"), \
                patch.object(semantic_fetcher.time, "sleep"):
            total_papers, total_rows = semantic_fetcher.fetch_papers_by_journal(
                "Demo Journal",
                query_type="query",
                start_page=0,
                progress_data=progress,
                ch_client=object(),
            )

        self.assertEqual(total_papers, 1)
        self.assertEqual(total_rows, 1)
        self.assertEqual(progress["journals"]["Demo Journal"]["status"], "completed")
        self.assertEqual(mocked_insert.call_count, 1)


if __name__ == "__main__":
    unittest.main()
