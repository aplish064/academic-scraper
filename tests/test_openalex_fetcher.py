import asyncio
import sys
import types
import unittest
from datetime import datetime
from unittest.mock import patch

import httpx


if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)

class _DummyTqdm:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, *_args, **_kwargs):
        pass

    def close(self):
        pass


if "tqdm.asyncio" not in sys.modules:
    tqdm_asyncio_module = types.ModuleType("tqdm.asyncio")
    tqdm_asyncio_module.tqdm = _DummyTqdm
    sys.modules["tqdm.asyncio"] = tqdm_asyncio_module

if "tqdm" not in sys.modules or not isinstance(sys.modules["tqdm"], types.ModuleType):
    tqdm_module = types.ModuleType("tqdm")
    tqdm_module.asyncio = sys.modules["tqdm.asyncio"]
    sys.modules["tqdm"] = tqdm_module
elif not hasattr(sys.modules["tqdm"], "asyncio"):
    sys.modules["tqdm"].asyncio = sys.modules["tqdm.asyncio"]

from src import openalex_fetcher


class _DummyBar:
    def __init__(self):
        self.total = 0

    def update(self, value):
        self.total += value

    def close(self):
        return None


class OpenAlexFetcherTests(unittest.TestCase):
    def test_build_credentials_appends_anonymous(self):
        credentials = openalex_fetcher.build_credentials()
        self.assertGreaterEqual(len(credentials), 2)
        self.assertTrue(credentials[-1].is_anonymous)
        self.assertFalse(credentials[0].is_anonymous)

    def test_build_request_params_omits_empty_fields_for_anonymous(self):
        credential = openalex_fetcher.Credential(email="", api_key="", source="anonymous")
        params = openalex_fetcher.build_request_params("2026-04-10", "*", credential)
        self.assertNotIn("api_key", params)
        self.assertNotIn("mailto", params)

    def test_get_all_dates_backward_includes_first_day_when_not_skipping(self):
        with patch.object(openalex_fetcher, "START_DATE", "20260402"), \
                patch.object(openalex_fetcher, "END_YEAR", 2025), \
                patch.object(openalex_fetcher, "SKIP_FIRST_DAY_OF_MONTH", False):
            dates = openalex_fetcher.get_all_dates_backward()
        self.assertIn("2026-04-01", dates)
        self.assertEqual(dates[0], "2026-04-02")

    def test_expand_papers_to_rows_keeps_publication_date(self):
        papers = [
            {
                "uid": "U1",
                "doi": "D1",
                "title": "T1",
                "authors": [
                    {"id": "A1", "name": "Alice", "rank": 1, "institution": {}},
                    {"id": "A2", "name": "Bob", "rank": 2, "institution": {}},
                ],
                "journal": "J1",
                "publication_date": "2026-04-10",
                "citation_count": 3,
                "fwci": 1.2,
                "citation_percentile": 55,
                "primary_topic": "AI",
                "is_retracted": False,
            }
        ]
        rows = openalex_fetcher.expand_papers_to_rows(papers)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["publication_date"], "2026-04-10")
        self.assertEqual(rows[1]["publication_date"], "2026-04-10")
        self.assertEqual(rows[0]["tag"], "第一作者")
        self.assertEqual(rows[1]["tag"], "最后作者")

    def test_build_dedup_insert_sql_uses_anti_join_and_excludes_import_time(self):
        sql = openalex_fetcher.build_dedup_insert_sql("temp_x")
        self.assertIn("LEFT ANTI JOIN", sql)
        self.assertIn(f"{openalex_fetcher.CH_DATABASE}.{openalex_fetcher.CH_TABLE} tgt", sql)
        self.assertNotIn("tmp.import_time = tgt.import_time", sql)

    def test_compute_next_restart_is_next_day_at_9am(self):
        now = datetime(2026, 5, 7, 23, 59, 0)
        target = openalex_fetcher.compute_next_restart(now=now, restart_hour=9)
        self.assertEqual(target.strftime("%Y-%m-%d %H:%M:%S"), "2026-05-08 09:00:00")

    def test_fetch_openalex_day_returns_rate_limit_status(self):
        async def _run():
            def handler(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(429, json={"message": "Rate limit exceeded", "retryAfter": 3600})

            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                return await openalex_fetcher.fetch_openalex_day(
                    http_client=client,
                    ch_client=object(),
                    date_str="2026-04-10",
                    credential=openalex_fetcher.Credential(email="a@b.com", api_key="k", source="configured"),
                    day_pbar=_DummyBar(),
                    paper_pbar=_DummyBar(),
                )

        result = asyncio.run(_run())
        self.assertEqual(result["status"], openalex_fetcher.RATE_LIMIT_EXCEEDED)
        self.assertEqual(result["retry_after"], 3600)

    def test_fetch_openalex_day_success_path_flushes_final_batch(self):
        async def _run():
            payload = {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Paper",
                        "doi": "https://doi.org/10.1/xx",
                        "authorships": [
                            {
                                "author": {"id": "https://openalex.org/A1", "display_name": "Alice"},
                                "institutions": [],
                                "raw_affiliation_strings": [],
                            }
                        ],
                        "primary_location": {"source": {"display_name": "Journal"}},
                        "publication_date": "2026-04-10",
                        "cited_by_count": 10,
                        "is_retracted": False,
                    }
                ],
                "meta": {},
            }

            def handler(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json=payload)

            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                with patch.object(openalex_fetcher, "batch_insert_clickhouse", return_value=True):
                    return await openalex_fetcher.fetch_openalex_day(
                        http_client=client,
                        ch_client=object(),
                        date_str="2026-04-10",
                        credential=openalex_fetcher.Credential(email="", api_key="", source="anonymous"),
                        day_pbar=_DummyBar(),
                        paper_pbar=_DummyBar(),
                    )

        result = asyncio.run(_run())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["paper_count"], 1)
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["write_count"], 1)


if __name__ == "__main__":
    unittest.main()
