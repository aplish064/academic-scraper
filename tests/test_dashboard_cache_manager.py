import json
import sys
import threading
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "dashboard"
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from dashboard.services.cache_manager import CacheManager
from dashboard.services.data_aggregator import DataSourceAggregator


VALID_PATENT_DATA = {
    "source": "patents",
    "statistics": {
        "total_papers": 9361444,
        "unique_authors": 4164926,
        "unique_journals": 562415,
    },
    "citations_distribution": {
        "0": 761260,
        "1-5": 3589411,
    },
}

INVALID_PATENT_CITATION_DATA = {
    "source": "patents",
    "statistics": {
        "total_papers": 9361444,
        "unique_authors": 4164926,
        "unique_journals": 562415,
    },
    "citations_distribution": {
        "0": 9361444,
    },
}

INVALID_OPENALEX_DATA = {
    "source": "openalex",
    "statistics": {
        "total_papers": 0,
        "unique_authors": 0,
        "unique_journals": 0,
    },
}

INCOMPLETE_OPENALEX_DATA = {
    "source": "openalex",
    "statistics": {
        "total_papers": 46352793,
        "unique_authors": 0,
        "unique_journals": 145506,
        "unique_institutions": 0,
    },
}

VALID_DBLP_DATA = {
    "source": "dblp",
    "papers_by_date": {"2024": 10},
    "citations_distribution": {},
    "author_types": {},
    "top_journals": {"VLDB": 4},
    "top_countries": {},
    "institution_types": {},
    "fwci_distribution": {},
    "ccf_class_distribution": {},
    "publication_type_distribution": {},
    "venue_type_distribution": {},
    "statistics": {
        "total_papers": 10,
        "unique_authors": 8,
        "unique_journals": 2,
        "unique_institutions": 0,
        "high_citations": 0,
        "avg_fwci": 0,
    },
}

VALID_OPENALEX_DATA = {
    "source": "openalex",
    "statistics": {
        "total_papers": 46352793,
        "unique_authors": 49491240,
        "unique_journals": 145506,
        "unique_institutions": 94614,
        "high_citations": 0,
        "avg_fwci": 3.74,
    },
}


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl

    def delete(self, key):
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return 1 if existed else 0


class FakeCacheManager:
    def __init__(self, stale_data):
        self.stale_data = stale_data

    def get_source_data(self, source):
        return None

    def get_stale_source_data(self, source):
        return self.stale_data if source == "patents" else None


class DashboardCacheManagerTests(unittest.TestCase):
    def test_source_data_writes_stale_cache_copy(self):
        redis = FakeRedis()
        manager = CacheManager(redis)

        manager.set_source_data("patents", VALID_PATENT_DATA)

        stale_key = manager.get_stale_cache_key("patents")
        self.assertIn(stale_key, redis.values)
        self.assertGreaterEqual(redis.ttls[stale_key], 24 * 60 * 60)

    def test_get_stale_source_data_returns_valid_stale_payload(self):
        redis = FakeRedis()
        manager = CacheManager(redis)
        stale_key = manager.get_stale_cache_key("patents")
        redis.setex(stale_key, 86400, json.dumps(VALID_PATENT_DATA))

        self.assertEqual(manager.get_stale_source_data("patents"), VALID_PATENT_DATA)

    def test_live_cache_hit_backfills_stale_cache_copy(self):
        redis = FakeRedis()
        manager = CacheManager(redis)
        live_key = manager.get_cache_key("patents")
        redis.setex(live_key, 60, json.dumps(VALID_PATENT_DATA))

        self.assertEqual(manager.get_source_data("patents"), VALID_PATENT_DATA)

        self.assertIn(manager.get_stale_cache_key("patents"), redis.values)

    def test_patents_live_cache_ttl_is_longer_than_proxy_timeout(self):
        manager = CacheManager(FakeRedis())

        self.assertGreaterEqual(manager.get_source_ttl("patents"), 60 * 60)

    def test_paper_source_live_cache_ttl_is_long_enough_for_source_switching(self):
        manager = CacheManager(FakeRedis())

        for source in ["openalex", "semantic", "dblp", "arxiv"]:
            self.assertGreaterEqual(manager.get_source_ttl(source), 60 * 60)

    def test_invalid_source_data_is_not_written_to_cache(self):
        redis = FakeRedis()
        manager = CacheManager(redis)

        saved = manager.set_source_data("openalex", INVALID_OPENALEX_DATA)

        self.assertFalse(saved)
        self.assertNotIn(manager.get_cache_key("openalex"), redis.values)
        self.assertNotIn(manager.get_stale_cache_key("openalex"), redis.values)

    def test_patent_cache_rejects_all_zero_citation_distribution(self):
        manager = CacheManager(FakeRedis())

        self.assertFalse(manager.validate_data_integrity(INVALID_PATENT_CITATION_DATA, "patents"))

    def test_incomplete_openalex_statistics_are_not_valid_cache(self):
        manager = CacheManager(FakeRedis())

        self.assertFalse(manager.validate_data_integrity(INCOMPLETE_OPENALEX_DATA, "openalex"))

    def test_invalid_live_cache_is_removed_and_not_returned(self):
        redis = FakeRedis()
        manager = CacheManager(redis)
        live_key = manager.get_cache_key("openalex")
        redis.setex(live_key, 60, json.dumps(INVALID_OPENALEX_DATA))

        self.assertIsNone(manager.get_source_data("openalex"))

        self.assertNotIn(live_key, redis.values)

    def test_source_data_can_be_reused_from_all_cache(self):
        redis = FakeRedis()
        manager = CacheManager(redis)
        all_data = {
            "source": "all",
            "statistics": {
                "total_papers": 10,
                "unique_authors": 8,
                "unique_journals": 2,
            },
            "_source_data": {
                "dblp": VALID_DBLP_DATA,
            },
        }
        manager.set_source_data("all", all_data, ttl=900)

        self.assertEqual(manager.get_source_data_from_all("dblp"), VALID_DBLP_DATA)


class DashboardAggregatorStaleCacheTests(unittest.TestCase):
    def test_openalex_statistics_uses_independent_scalar_queries(self):
        class QueryResult:
            def __init__(self, value):
                self.result_rows = [value if isinstance(value, tuple) else (value,)]

        class FakeQueryBuilder:
            def __init__(self):
                self.calls = []

            def execute_query(self, sql):
                self.calls.append(sql)
                normalized_sql = " ".join(sql.split())

                if normalized_sql.startswith("SELECT (SELECT"):
                    return QueryResult((0, 0, 0, 0, 0, 0))
                if "uniqHLL12(doi)" in sql:
                    return QueryResult(46352793)
                if "uniq(cityHash64(author_id))" in sql:
                    return QueryResult(49491240)
                if "uniqHLL12(journal)" in sql:
                    return QueryResult(145506)
                if "uniq(institution_name)" in sql:
                    return QueryResult(94614)
                if "sum(if(isFinite(fwci)" in sql:
                    return QueryResult(597137474.1022049)
                if "countIf(fwci > 0)" in sql:
                    return QueryResult(159816863)
                return None

        aggregator = DataSourceAggregator(
            ch_client_getter=lambda: None,
            cache_manager=FakeCacheManager(None),
        )
        fake_query_builder = FakeQueryBuilder()
        aggregator.query_builder = fake_query_builder

        stats = aggregator.query_statistics("openalex")

        self.assertGreaterEqual(len(fake_query_builder.calls), 6)
        self.assertEqual(stats["total_papers"], 46352793)
        self.assertEqual(stats["unique_authors"], 49491240)
        self.assertEqual(stats["unique_journals"], 145506)
        self.assertEqual(stats["unique_institutions"], 94614)
        self.assertEqual(stats["avg_fwci"], 3.74)

    def test_stale_cache_returns_without_synchronous_database_query(self):
        aggregator = DataSourceAggregator(
            ch_client_getter=lambda: None,
            cache_manager=FakeCacheManager(VALID_PATENT_DATA),
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("database query should not run when stale cache is available")

        aggregator.query_statistics = fail_if_called
        aggregator._refresh_source_cache_async = lambda source: None

        result = aggregator.get_single_source_data("patents")

        self.assertEqual(result["statistics"]["total_papers"], 9361444)

    def test_concurrent_cold_requests_share_one_database_query(self):
        class SingleFlightCache:
            def __init__(self):
                self.data = None
                self.lock = threading.Lock()

            def get_source_data(self, source):
                with self.lock:
                    return self.data

            def get_stale_source_data(self, source):
                return None

            def set_source_data(self, source, data):
                with self.lock:
                    self.data = data

        class SlowAggregator(DataSourceAggregator):
            def __init__(self, cache_manager):
                super().__init__(lambda: None, cache_manager)
                self.query_count = 0

            def _query_single_source_data(self, source, adapter):
                self.query_count += 1
                time.sleep(0.05)
                self.cache_manager.set_source_data(source, VALID_PATENT_DATA)
                return VALID_PATENT_DATA

        aggregator = SlowAggregator(SingleFlightCache())
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(aggregator.get_single_source_data("patents")))
            for _ in range(2)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(aggregator.query_count, 1)
        self.assertEqual([r["statistics"]["total_papers"] for r in results], [9361444, 9361444])

    def test_all_uses_available_cache_without_synchronous_database_query(self):
        class PartialCache:
            def get_source_data(self, source):
                if source == "all":
                    return None
                if source == "dblp":
                    return VALID_DBLP_DATA
                return None

            def get_stale_source_data(self, source):
                if source == "all":
                    return None
                if source == "patents":
                    return VALID_PATENT_DATA
                return None

            def get_available_merged_data(self):
                return VALID_DBLP_DATA

            def set_source_data(self, source, data, ttl=None):
                self.saved = (source, data, ttl)

        aggregator = DataSourceAggregator(
            ch_client_getter=lambda: None,
            cache_manager=PartialCache(),
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("all must not synchronously query missing large sources")

        aggregator._query_all_sources_parallel = fail_if_called
        aggregator.update_cross_source_statistics = fail_if_called

        result = aggregator.aggregate_all_sources()

        self.assertEqual(result["source"], "all")
        self.assertEqual(result["statistics"]["total_papers"], 10)

    def test_all_cached_response_hydrates_openalex_only_statistics(self):
        cached_all = {
            "source": "all",
            "statistics": {
                "total_papers": 47949180,
                "unique_authors": 58366275,
                "unique_journals": 1102922,
            },
        }

        class AllCache:
            def get_source_data(self, source):
                if source == "all":
                    return cached_all
                if source == "openalex":
                    return VALID_OPENALEX_DATA
                return None

        aggregator = DataSourceAggregator(
            ch_client_getter=lambda: None,
            cache_manager=AllCache(),
        )

        result = aggregator.aggregate_all_sources()

        self.assertEqual(result["statistics"]["unique_institutions"], 94614)
        self.assertEqual(result["statistics"]["avg_fwci"], 3.74)

    def test_single_source_uses_all_cache_snapshot_before_database_query(self):
        class AllSnapshotCache:
            def get_source_data(self, source):
                return None

            def get_stale_source_data(self, source):
                return None

            def get_source_data_from_all(self, source):
                return VALID_DBLP_DATA if source == "dblp" else None

        aggregator = DataSourceAggregator(
            ch_client_getter=lambda: None,
            cache_manager=AllSnapshotCache(),
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("database query should not run when all cache has this source")

        aggregator._query_single_source_data = fail_if_called

        result = aggregator.get_single_source_data("dblp")

        self.assertEqual(result["statistics"]["total_papers"], 10)


if __name__ == "__main__":
    unittest.main()
