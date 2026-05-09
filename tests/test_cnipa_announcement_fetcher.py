import hashlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import date
from unittest import mock

import requests

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)

from src import cn_patent_fetcher
from src import cnipa_announcement_fetcher


class CnipaAnnouncementFetcherHelperTests(unittest.TestCase):
    def test_build_signature_hashes_prefix_and_request_time(self):
        request_time = "1714380800123"

        signature = cnipa_announcement_fetcher.build_signature(request_time)

        self.assertEqual(
            signature,
            hashlib.md5(f"zscqgbgg{request_time}".encode("utf-8")).hexdigest(),
        )

    def test_parse_yyyymmdd_accepts_int_and_string(self):
        self.assertEqual(cnipa_announcement_fetcher.parse_yyyymmdd(20240501), date(2024, 5, 1))
        self.assertEqual(cnipa_announcement_fetcher.parse_yyyymmdd("20240502"), date(2024, 5, 2))

    def test_parse_yyyymmdd_returns_none_for_none(self):
        self.assertIsNone(cnipa_announcement_fetcher.parse_yyyymmdd(None))

    def test_parse_yyyymmdd_returns_none_for_malformed_values(self):
        for value in ["", "00000000", "202405", "202405011", "20261301"]:
            with self.subTest(value=value):
                self.assertIsNone(cnipa_announcement_fetcher.parse_yyyymmdd(value))

    def test_parse_pubtypes_accepts_comma_list_all_and_blank(self):
        self.assertEqual(cnipa_announcement_fetcher.parse_pubtypes("1,3,6"), [1, 3, 6])
        self.assertEqual(cnipa_announcement_fetcher.parse_pubtypes("all"), [])
        self.assertEqual(cnipa_announcement_fetcher.parse_pubtypes(""), [])

    def test_map_announcement_record_adapts_cnipa_fields_for_cn_patent_parser(self):
        record = {
            "pn": "CN117000001A",
            "an": "CN202410000001.2",
            "ti": "一种学术数据处理方法",
            "abs": "用于测试的摘要。",
            "pd": 20240419,
            "ad": "20240115",
            "pubtype": 1,
            "e72": "张三; 李四",
            "e71_73": "示例大学; 北京样例科技有限公司",
            "e51": "G06F16/00; G06F40/00",
            "codeUrl": "https://example.test/announcement/CN117000001A",
        }

        mapped = cnipa_announcement_fetcher.map_announcement_record(record)

        self.assertEqual(mapped["source"], "cnipa_announcement")
        self.assertEqual(mapped["country"], "CN")
        self.assertEqual(mapped["publication_number"], "CN117000001A")
        self.assertEqual(mapped["application_number"], "CN202410000001.2")
        self.assertEqual(mapped["patent_title"], "一种学术数据处理方法")
        self.assertEqual(mapped["patent_abstract"], "用于测试的摘要。")
        self.assertEqual(mapped["publication_date"], "2024-04-19")
        self.assertEqual(mapped["application_date"], "2024-01-15")
        self.assertEqual(mapped["patent_type"], "发布公告")
        self.assertEqual(mapped["status"], "发布公告")
        self.assertEqual(mapped["inventors"], "张三; 李四")
        self.assertEqual(mapped["assignees"], "示例大学; 北京样例科技有限公司")
        self.assertEqual(mapped["ipc_codes"], "G06F16/00; G06F40/00")
        self.assertEqual(mapped["source_url"], "https://example.test/announcement/CN117000001A")

        raw_json = json.loads(mapped["raw_json"])
        self.assertEqual(raw_json["pn"], "CN117000001A")
        self.assertEqual(raw_json["pubtype"], 1)

    def test_mapped_announcement_record_preserves_expanded_people_and_ipc_rows(self):
        mapped = cnipa_announcement_fetcher.map_announcement_record(
            {
                "pn": "CN117000001A",
                "an": "CN202410000001.2",
                "ti": "一种学术数据处理方法",
                "abs": "用于测试的摘要。",
                "pd": "20240419",
                "ad": "20240115",
                "pubtype": 3,
                "e72": "张三; 李四",
                "e71_73": "示例大学; 北京样例科技有限公司",
                "e51": "G06F16/00; G06F40/00",
                "codeUrl": "https://example.test/announcement/CN117000001A",
            }
        )

        parsed = cn_patent_fetcher.parse_cn_patent_record(mapped)
        expanded = cn_patent_fetcher.expand_patent_rows(parsed)

        self.assertEqual(parsed["source"], "cnipa_announcement")
        self.assertEqual(parsed["publication_date"], date(2024, 4, 19))
        self.assertEqual(parsed["application_date"], date(2024, 1, 15))
        self.assertEqual(parsed["grant_date"], date(2024, 4, 19))
        self.assertEqual(expanded["patents"][0]["source"], "cnipa_announcement")
        self.assertEqual([row["inventor_name"] for row in expanded["inventors"]], ["张三", "李四"])
        self.assertEqual(
            [row["assignee_name"] for row in expanded["assignees"]],
            ["示例大学", "北京样例科技有限公司"],
        )
        self.assertEqual([row["ipc_code"] for row in expanded["ipc"]], ["G06F16/00", "G06F40/00"])

    def test_map_announcement_record_sets_grant_date_for_grant_pubtypes(self):
        for pubtype in [3, 4, 6, 7, 9, 10]:
            with self.subTest(pubtype=pubtype):
                row = cnipa_announcement_fetcher.map_announcement_record(
                    {
                        "pn": f"CN11700000{pubtype}",
                        "pd": "20240419",
                        "pubtype": pubtype,
                    }
                )

                self.assertEqual(row["grant_date"], "2024-04-19")

    def test_map_announcement_record_accepts_pubtype_name(self):
        row = cnipa_announcement_fetcher.map_announcement_record(
            {
                "pn": "CN117000001A",
                "pd": "20240419",
                "pubtype": "发布公告",
            }
        )

        self.assertEqual(row["patent_type"], "发布公告")
        self.assertEqual(row["status"], "发布公告")
        self.assertNotIn("grant_date", row)

    def test_map_announcement_record_accepts_unknown_pubtype_string(self):
        row = cnipa_announcement_fetcher.map_announcement_record(
            {
                "pn": "CN117000001A",
                "pd": "20240419",
                "pubtype": "unknown",
            }
        )

        self.assertEqual(row["patent_type"], "unknown")
        self.assertEqual(row["status"], "unknown")
        self.assertNotIn("grant_date", row)

    def test_build_search_payload_encodes_condition_under_param_json(self):
        request_time = "1714380800123"

        payload = cnipa_announcement_fetcher.build_search_payload(
            keyword="量子通信",
            announcement_date=date(2024, 4, 19),
            pubtype=3,
            offset=20,
            size=10,
            request_time=request_time,
        )

        param = json.loads(payload["param"])
        self.assertEqual(param["from"], "1")
        self.assertEqual(param["key"], cnipa_announcement_fetcher.ANNOUNCEMENT_KEY)
        self.assertEqual(param["sign"], cnipa_announcement_fetcher.build_signature(request_time))
        self.assertEqual(param["requestTime"], request_time)
        raw = param["raw"]
        self.assertEqual(raw["searchStr"], "量子通信")
        self.assertEqual(raw["ggr_begin"], "20240419")
        self.assertEqual(raw["ggr_end"], "20240419")
        self.assertEqual(raw["from"], 20)
        self.assertEqual(raw["size"], 10)
        self.assertEqual(raw["pubtypeList"], [3])

    def test_build_search_payload_does_not_require_out_of_band_condition_field(self):
        request_time = "1714380800123"

        payload = cnipa_announcement_fetcher.build_search_payload(
            keyword="",
            announcement_date="2024-04-19",
            pubtype=6,
            offset=0,
            size=100,
            request_time=request_time,
        )

        self.assertNotIn("condition", payload)
        condition = json.loads(payload["param"])
        self.assertEqual(condition["from"], "1")
        self.assertEqual(condition["key"], cnipa_announcement_fetcher.ANNOUNCEMENT_KEY)
        self.assertEqual(condition["sign"], cnipa_announcement_fetcher.build_signature(request_time))
        self.assertEqual(condition["requestTime"], request_time)
        raw = condition["raw"]
        self.assertEqual(raw["ggr_begin"], "20240419")
        self.assertEqual(raw["ggr_end"], "20240419")
        self.assertEqual(raw["from"], 0)
        self.assertEqual(raw["size"], 100)
        self.assertEqual(raw["pubtypeList"], [6])

    def test_count_bucket_reads_all_count_from_response(self):
        session = FakeSession([FakeResponse({"allCount": 17, "patentList": []})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(session=session, request_delay=0)

        count = client.count_bucket("量子通信", date(2024, 4, 19), 3, request_time="1714380800123")

        self.assertEqual(count, 17)

    def test_search_bucket_returns_patent_list_from_response(self):
        patents = [{"pn": "CN117000001A"}, {"pn": "CN117000002A"}]
        session = FakeSession([FakeResponse({"allCount": 2, "patentList": patents})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(session=session, request_delay=0)

        result = client.search_bucket(
            "量子通信",
            date(2024, 4, 19),
            3,
            offset=0,
            size=100,
            request_time="1714380800123",
        )

        self.assertEqual(result, patents)

    def test_count_bucket_raises_when_all_count_is_absent(self):
        session = FakeSession([FakeResponse({})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(session=session, request_delay=0)

        with self.assertRaises(RuntimeError):
            client.count_bucket("量子通信", date(2024, 4, 19), 3, request_time="1714380800123")

    def test_count_bucket_raises_when_all_count_is_not_parseable(self):
        session = FakeSession([FakeResponse({"allCount": "not-a-number"})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(session=session, request_delay=0)

        with self.assertRaises(RuntimeError):
            client.count_bucket("量子通信", date(2024, 4, 19), 3, request_time="1714380800123")

    def test_search_bucket_raises_when_patent_list_is_absent(self):
        session = FakeSession([FakeResponse({"allCount": 2})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(session=session, request_delay=0)

        with self.assertRaises(RuntimeError):
            client.search_bucket("量子通信", date(2024, 4, 19), 3, request_time="1714380800123")

    def test_search_bucket_raises_when_patent_list_is_not_a_list(self):
        session = FakeSession([FakeResponse({"allCount": 2, "patentList": {}})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(session=session, request_delay=0)

        with self.assertRaises(RuntimeError):
            client.search_bucket("量子通信", date(2024, 4, 19), 3, request_time="1714380800123")

    def test_post_search_treats_error_code_response_as_endpoint_error(self):
        session = FakeSession([FakeResponse({"reason": "非法请求", "error_code": "10008"})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(
            session=session,
            request_delay=0,
            max_retries=1,
        )

        with self.assertRaisesRegex(RuntimeError, "10008"):
            client.count_bucket("量子通信", date(2024, 4, 19), 3, request_time="1714380800123")

    def test_post_search_applies_request_delay_before_each_request(self):
        sleeps = []
        session = FakeSession([FakeResponse({"allCount": 1, "patentList": []})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(
            session=session,
            request_delay=0.2,
            max_retries=1,
            sleep_func=sleeps.append,
        )

        client.count_bucket("量子通信", date(2024, 4, 19), 3, request_time="1714380800123")

        self.assertEqual(sleeps, [0.2])

    def test_post_search_retries_with_fresh_request_time(self):
        session = FakeSession([requests.ConnectionError("temporary"), FakeResponse({"allCount": 0, "patentList": []})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(
            session=session,
            request_delay=1,
            max_retries=2,
            sleep_func=lambda _seconds: None,
            now_ms_func=SequenceClock(["1714380800001", "1714380800002"]),
        )

        client.post_search("量子通信", date(2024, 4, 19), 3)

        first = json.loads(session.calls[0][1]["data"]["param"])
        second = json.loads(session.calls[1][1]["data"]["param"])
        self.assertEqual(first["requestTime"], "1714380800001")
        self.assertEqual(second["requestTime"], "1714380800002")
        self.assertNotEqual(first["sign"], second["sign"])

    def test_post_search_keeps_explicit_request_time_stable_across_retries(self):
        session = FakeSession([requests.ConnectionError("temporary"), FakeResponse({"allCount": 0, "patentList": []})])
        client = cnipa_announcement_fetcher.CnipaAnnouncementClient(
            session=session,
            request_delay=1,
            max_retries=2,
            sleep_func=lambda _seconds: None,
            now_ms_func=SequenceClock(["1714380800001", "1714380800002"]),
        )

        client.post_search("量子通信", date(2024, 4, 19), 3, request_time="fixed-time")

        first = json.loads(session.calls[0][1]["data"]["param"])
        second = json.loads(session.calls[1][1]["data"]["param"])
        self.assertEqual(first["requestTime"], "fixed-time")
        self.assertEqual(second["requestTime"], "fixed-time")
        self.assertEqual(first["sign"], second["sign"])

    def test_write_progress_merges_fields_preserves_previous_fields_and_adds_updated_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            with open(progress_file, "w", encoding="utf-8") as handle:
                json.dump({"completed": 1, "keep": "yes"}, handle)

            cnipa_announcement_fetcher.write_progress(progress_file, completed=2, current_date=date(2024, 4, 19))

            with open(progress_file, "r", encoding="utf-8") as handle:
                progress = json.load(handle)

        self.assertEqual(progress["completed"], 2)
        self.assertEqual(progress["keep"], "yes")
        self.assertEqual(progress["current_date"], "2024-04-19")
        self.assertIn("updated_at", progress)

    def test_write_progress_uses_unique_temp_file_without_clobbering_fixed_tmp_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            fixed_tmp_path = f"{progress_file}.tmp"
            with open(fixed_tmp_path, "w", encoding="utf-8") as handle:
                handle.write("sentinel")

            cnipa_announcement_fetcher.write_progress(progress_file, completed=1)

            with open(fixed_tmp_path, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "sentinel")

    def test_write_progress_cleans_temp_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")

            with mock.patch.object(cnipa_announcement_fetcher.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    cnipa_announcement_fetcher.write_progress(progress_file, completed=1)

            leftovers = [
                name for name in os.listdir(tmpdir)
                if name.startswith("progress.json.") and name.endswith(".tmp")
            ]
            self.assertEqual(leftovers, [])

    def test_initial_buckets_are_decimal_digits(self):
        self.assertEqual(cnipa_announcement_fetcher.INITIAL_BUCKETS, list("0123456789"))

    def test_parse_date_arg_and_iter_dates_accept_iso_ranges(self):
        self.assertEqual(cnipa_announcement_fetcher.parse_date_arg("2024-04-19"), date(2024, 4, 19))
        self.assertEqual(
            list(cnipa_announcement_fetcher.iter_dates("2024-04-19", "2024-04-21")),
            [date(2024, 4, 19), date(2024, 4, 20), date(2024, 4, 21)],
        )

    def test_resolve_buckets_splits_large_count_and_returns_nonzero_child_buckets(self):
        client = FakeBucketClient(
            counts={
                "1": 1000,
                "10": 0,
                "11": 5,
                "12": 9,
                "13": 0,
                "14": 0,
                "15": 0,
                "16": 0,
                "17": 0,
                "18": 0,
                "19": 0,
                "2": 3,
            }
        )

        fetchable, capped = cnipa_announcement_fetcher.resolve_buckets(
            client,
            date(2024, 4, 19),
            3,
            initial_buckets=["1", "2"],
            split_threshold=10,
            max_prefix_length=2,
        )

        self.assertEqual(fetchable, [("11", 5), ("12", 9), ("2", 3)])
        self.assertEqual(capped, [])
        self.assertEqual(client.count_calls, ["1", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "2"])

    def test_resolve_buckets_marks_capped_at_max_depth(self):
        client = FakeBucketClient(counts={"99": 20})

        fetchable, capped = cnipa_announcement_fetcher.resolve_buckets(
            client,
            date(2024, 4, 19),
            6,
            initial_buckets=["99"],
            split_threshold=10,
            max_prefix_length=2,
        )

        self.assertEqual(fetchable, [("99", 20)])
        self.assertEqual(
            capped,
            [{"date": "2024-04-19", "pubtype": 6, "bucket": "99", "count": 20}],
        )

    def test_fetch_bucket_records_deduplicates_patent_id_across_pages_and_within_page(self):
        client = FakeBucketClient(
            pages={
                ("1", 0, 2): [
                    {"pn": "CN117000001A", "pd": "20240419", "pubtype": 3},
                    {"pn": "CN117000001A", "pd": "20240419", "pubtype": 3},
                ],
                ("1", 2, 2): [
                    {"pn": "CN117000002A", "pd": "20240419", "pubtype": 3},
                    {"pn": "CN117000001A", "pd": "20240419", "pubtype": 3},
                ],
            }
        )
        seen = {"cnipa_announcement:publication:CN116999999A"}

        records, deduped_count = cnipa_announcement_fetcher.fetch_bucket_records(
            client,
            date(2024, 4, 19),
            3,
            "1",
            total_count=4,
            page_size=2,
            max_results=4,
            seen_patent_ids=seen,
            log_file="",
        )

        self.assertEqual([record["publication_number"] for record in records], ["CN117000001A", "CN117000002A"])
        self.assertEqual(deduped_count, 2)
        self.assertEqual(
            seen,
            {
                "cnipa_announcement:publication:CN116999999A",
                "cnipa_announcement:publication:CN117000001A",
                "cnipa_announcement:publication:CN117000002A",
            },
        )

    def test_insert_records_uses_existing_cn_patent_pipeline(self):
        records = [
            {"publication_number": "CN117000001A"},
            {"publication_number": "CN117000002A"},
        ]
        expanded_rows = [
            {
                "patents": [{"patent_id": "p1"}],
                "applications": [{"patent_id": "p1"}],
                "inventors": [],
                "assignees": [],
                "abstracts": [{"patent_id": "p1"}],
                "ipc": [{"patent_id": "p1"}],
            },
            {
                "patents": [{"patent_id": "p2"}],
                "applications": [],
                "inventors": [{"patent_id": "p2"}],
                "assignees": [{"patent_id": "p2"}],
                "abstracts": [],
                "ipc": [],
            },
        ]
        ch_client = object()

        with mock.patch.object(cnipa_announcement_fetcher.cn_patent_fetcher, "parse_cn_patent_record") as parse_mock:
            with mock.patch.object(cnipa_announcement_fetcher.cn_patent_fetcher, "expand_patent_rows") as expand_mock:
                with mock.patch.object(cnipa_announcement_fetcher.cn_patent_fetcher, "insert_import_result") as insert_mock:
                    parse_mock.side_effect = [{"parsed": 1}, {"parsed": 2}]
                    expand_mock.side_effect = expanded_rows
                    insert_mock.side_effect = [2, 1, 1, 1, 1, 1]

                    inserted = cnipa_announcement_fetcher.insert_records(ch_client, records, batch_size=50)

        self.assertEqual(inserted, 2)
        parse_mock.assert_has_calls([mock.call(records[0]), mock.call(records[1])])
        expand_mock.assert_has_calls([mock.call({"parsed": 1}), mock.call({"parsed": 2})])
        insert_mock.assert_has_calls(
            [
                mock.call(
                    ch_client,
                    cn_patent_fetcher.CH_TABLE,
                    [{"patent_id": "p1"}, {"patent_id": "p2"}],
                    cn_patent_fetcher.PATENT_COLUMNS,
                    batch_size=50,
                ),
                mock.call(
                    ch_client,
                    cn_patent_fetcher.CH_APPLICATIONS_TABLE,
                    [{"patent_id": "p1"}],
                    cn_patent_fetcher.APPLICATION_COLUMNS,
                    batch_size=50,
                ),
                mock.call(
                    ch_client,
                    cn_patent_fetcher.CH_INVENTORS_TABLE,
                    [{"patent_id": "p2"}],
                    cn_patent_fetcher.INVENTOR_COLUMNS,
                    batch_size=50,
                ),
                mock.call(
                    ch_client,
                    cn_patent_fetcher.CH_ASSIGNEES_TABLE,
                    [{"patent_id": "p2"}],
                    cn_patent_fetcher.ASSIGNEE_COLUMNS,
                    batch_size=50,
                ),
                mock.call(
                    ch_client,
                    cn_patent_fetcher.CH_ABSTRACTS_TABLE,
                    [{"patent_id": "p1"}],
                    cn_patent_fetcher.ABSTRACT_COLUMNS,
                    batch_size=50,
                ),
                mock.call(
                    ch_client,
                    cn_patent_fetcher.CH_IPC_TABLE,
                    [{"patent_id": "p1"}],
                    cn_patent_fetcher.IPC_COLUMNS,
                    batch_size=50,
                ),
            ]
        )

    def test_direct_script_help_imports_dependencies(self):
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "src",
            "cnipa_announcement_fetcher.py",
        )

        result = subprocess.run(
            [sys.executable, script_path, "--help"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Fetch CNIPA patent announcements", result.stdout)

    def test_parse_args_uses_task4_defaults(self):
        args = cnipa_announcement_fetcher.parse_args(
            [
                "--start-date",
                "2024-04-19",
                "--end-date",
                "2024-04-20",
            ]
        )

        self.assertEqual(args.start_date, "2024-04-19")
        self.assertEqual(args.end_date, "2024-04-20")
        self.assertEqual(args.batch_size, cnipa_announcement_fetcher.DEFAULT_BATCH_SIZE)
        self.assertEqual(args.page_size, cnipa_announcement_fetcher.DEFAULT_PAGE_SIZE)
        self.assertEqual(args.request_delay, cnipa_announcement_fetcher.DEFAULT_REQUEST_DELAY)
        self.assertEqual(args.split_threshold, cnipa_announcement_fetcher.DEFAULT_SPLIT_THRESHOLD)
        self.assertEqual(args.max_prefix_length, cnipa_announcement_fetcher.DEFAULT_MAX_PREFIX_LENGTH)
        self.assertEqual(args.max_results_per_bucket, cnipa_announcement_fetcher.DEFAULT_MAX_RESULTS_PER_BUCKET)
        self.assertEqual(args.pubtypes, "all")
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.limit_dates)
        self.assertEqual(args.progress_file, cnipa_announcement_fetcher.DEFAULT_PROGRESS_FILE)
        self.assertTrue(args.progress_file.endswith("cnipa_announcement_progress.json"))
        self.assertEqual(args.log_file, cnipa_announcement_fetcher.DEFAULT_LOG_FILE)

    def test_run_dry_run_writes_progress_and_does_not_create_clickhouse_client(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            log_file = os.path.join(tmpdir, "events.jsonl")
            client = object()
            records = [{"publication_number": "CN117000001A"}]

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=client,
            ) as client_cls, mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "create_clickhouse_client",
            ) as create_ch, mock.patch.object(
                cnipa_announcement_fetcher,
                "resolve_buckets",
                return_value=([("1", 1)], []),
            ) as resolve_mock, mock.patch.object(
                cnipa_announcement_fetcher,
                "fetch_bucket_records",
                return_value=(records, 0),
            ) as fetch_mock, mock.patch.object(
                cnipa_announcement_fetcher,
                "insert_records",
            ) as insert_mock:
                exit_code = cnipa_announcement_fetcher.run(
                    [
                        "--start-date",
                        "2024-04-19",
                        "--end-date",
                        "2024-04-19",
                        "--pubtypes",
                        "3",
                        "--dry-run",
                        "--progress-file",
                        progress_file,
                        "--log-file",
                        log_file,
                    ]
                )

            with open(progress_file, "r", encoding="utf-8") as handle:
                progress = json.load(handle)
            with open(log_file, "r", encoding="utf-8") as handle:
                events = [json.loads(line)["event"] for line in handle]

        self.assertEqual(exit_code, 0)
        client_cls.assert_called_once_with(request_delay=cnipa_announcement_fetcher.DEFAULT_REQUEST_DELAY, log_file=log_file)
        create_ch.assert_not_called()
        resolve_mock.assert_called_once_with(
            client,
            date(2024, 4, 19),
            3,
            split_threshold=cnipa_announcement_fetcher.DEFAULT_SPLIT_THRESHOLD,
            max_prefix_length=cnipa_announcement_fetcher.DEFAULT_MAX_PREFIX_LENGTH,
            log_file=log_file,
        )
        fetch_mock.assert_called_once()
        insert_mock.assert_not_called()
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["source"], cnipa_announcement_fetcher.SOURCE_NAME)
        self.assertTrue(progress["dry_run"])
        self.assertEqual(progress["completed_dates"], ["2024-04-19"])
        self.assertEqual(progress["fetched_records"], 1)
        self.assertEqual(progress["inserted_patents"], 0)
        self.assertEqual(progress["deduped_records"], 0)
        self.assertEqual(progress["capped_tasks"], [])
        self.assertEqual(progress["current_bucket"], "")

        self.assertIn("dry_run_batch", events)

    def test_run_marks_progress_failed_when_orchestration_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            log_file = os.path.join(tmpdir, "events.jsonl")
            client = object()

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=client,
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "resolve_buckets",
                side_effect=RuntimeError("bad endpoint payload"),
            ):
                with self.assertRaisesRegex(RuntimeError, "bad endpoint payload"):
                    cnipa_announcement_fetcher.run(
                        [
                            "--start-date",
                            "2024-04-19",
                            "--end-date",
                            "2024-04-19",
                            "--pubtypes",
                            "3",
                            "--dry-run",
                            "--progress-file",
                            progress_file,
                            "--log-file",
                            log_file,
                        ]
                    )

            with open(progress_file, "r", encoding="utf-8") as handle:
                progress = json.load(handle)

        self.assertEqual(progress["status"], "failed")
        self.assertEqual(progress["error_type"], "RuntimeError")
        self.assertIn("bad endpoint payload", progress["error"])

    def test_run_marks_failed_count_bucket_with_current_bucket(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            log_file = os.path.join(tmpdir, "events.jsonl")

            class FailingCountClient:
                def count_bucket(self, keyword, announcement_date, pubtype):
                    raise RuntimeError(f"bad count bucket {keyword}")

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=FailingCountClient(),
            ):
                with self.assertRaisesRegex(RuntimeError, "bad count bucket 0"):
                    cnipa_announcement_fetcher.run(
                        [
                            "--start-date",
                            "2024-04-19",
                            "--end-date",
                            "2024-04-19",
                            "--pubtypes",
                            "3",
                            "--dry-run",
                            "--progress-file",
                            progress_file,
                            "--log-file",
                            log_file,
                        ]
                    )

            with open(progress_file, "r", encoding="utf-8") as handle:
                progress = json.load(handle)

        self.assertEqual(progress["status"], "failed")
        self.assertEqual(progress["current_date"], "2024-04-19")
        self.assertEqual(progress["current_pubtype"], 3)
        self.assertEqual(progress["current_bucket"], "0")
        self.assertIn("bad count bucket 0", progress["error"])

    def test_run_real_import_after_dry_run_same_progress_still_inserts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            log_file = os.path.join(tmpdir, "events.jsonl")
            client = object()
            bootstrap_client = object()
            ch_client = object()
            records = [{"publication_number": "CN117000001A"}]

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=client,
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "create_bootstrap_clickhouse_client",
                return_value=bootstrap_client,
            ), mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "create_clickhouse_client",
                return_value=ch_client,
            ), mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "ensure_database",
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "resolve_buckets",
                return_value=([("1", 1)], []),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "fetch_bucket_records",
                return_value=(records, 0),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "insert_records",
                return_value=1,
            ) as insert_mock:
                dry_exit_code = cnipa_announcement_fetcher.run(
                    [
                        "--start-date",
                        "2024-04-19",
                        "--end-date",
                        "2024-04-19",
                        "--pubtypes",
                        "3",
                        "--dry-run",
                        "--progress-file",
                        progress_file,
                        "--log-file",
                        log_file,
                    ]
                )
                real_exit_code = cnipa_announcement_fetcher.run(
                    [
                        "--start-date",
                        "2024-04-19",
                        "--end-date",
                        "2024-04-19",
                        "--pubtypes",
                        "3",
                        "--progress-file",
                        progress_file,
                        "--log-file",
                        log_file,
                    ]
                )

        self.assertEqual(dry_exit_code, 0)
        self.assertEqual(real_exit_code, 0)
        insert_mock.assert_called_once_with(ch_client, records, batch_size=cnipa_announcement_fetcher.DEFAULT_BATCH_SIZE)

    def test_run_real_import_creates_clickhouse_client_inserts_and_marks_completed_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            log_file = os.path.join(tmpdir, "events.jsonl")
            client = object()
            bootstrap_client = object()
            ch_client = object()
            records = [{"publication_number": "CN117000001A"}]

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=client,
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "create_bootstrap_clickhouse_client",
                return_value=bootstrap_client,
            ), mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "create_clickhouse_client",
                return_value=ch_client,
            ) as create_ch, mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "ensure_database",
            ) as ensure_database, mock.patch.object(
                cnipa_announcement_fetcher,
                "resolve_buckets",
                return_value=([("1", 1)], []),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "fetch_bucket_records",
                return_value=(records, 0),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "insert_records",
                return_value=1,
            ) as insert_mock:
                exit_code = cnipa_announcement_fetcher.run(
                    [
                        "--start-date",
                        "2024-04-19",
                        "--end-date",
                        "2024-04-19",
                        "--pubtypes",
                        "3",
                        "--batch-size",
                        "25",
                        "--progress-file",
                        progress_file,
                        "--log-file",
                        log_file,
                    ]
                )

            with open(progress_file, "r", encoding="utf-8") as handle:
                progress = json.load(handle)

        self.assertEqual(exit_code, 0)
        create_ch.assert_called_once_with()
        ensure_database.assert_called_once_with(bootstrap_client)
        insert_mock.assert_called_once_with(ch_client, records, batch_size=25)
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["completed_dates"], ["2024-04-19"])
        self.assertEqual(progress["fetched_records"], 1)
        self.assertEqual(progress["inserted_patents"], 1)

    def test_run_bootstraps_database_before_creating_database_scoped_client(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            log_file = os.path.join(tmpdir, "events.jsonl")
            client = object()
            bootstrap_client = object()
            database_client = object()
            records = [{"publication_number": "CN117000001A"}]
            call_order = []

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=client,
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "create_bootstrap_clickhouse_client",
                side_effect=lambda: call_order.append("bootstrap") or bootstrap_client,
            ) as create_bootstrap, mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "ensure_database",
                side_effect=lambda ch: call_order.append(("ensure", ch)),
            ) as ensure_database, mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "create_clickhouse_client",
                side_effect=lambda: call_order.append("database") or database_client,
            ) as create_database_client, mock.patch.object(
                cnipa_announcement_fetcher,
                "resolve_buckets",
                return_value=([("1", 1)], []),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "fetch_bucket_records",
                return_value=(records, 0),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "insert_records",
                return_value=1,
            ) as insert_mock:
                exit_code = cnipa_announcement_fetcher.run(
                    [
                        "--start-date",
                        "2024-04-19",
                        "--end-date",
                        "2024-04-19",
                        "--pubtypes",
                        "3",
                        "--progress-file",
                        progress_file,
                        "--log-file",
                        log_file,
                    ]
                )

        self.assertEqual(exit_code, 0)
        create_bootstrap.assert_called_once_with()
        ensure_database.assert_called_once_with(bootstrap_client)
        create_database_client.assert_called_once_with()
        insert_mock.assert_called_once_with(database_client, records, batch_size=cnipa_announcement_fetcher.DEFAULT_BATCH_SIZE)
        self.assertEqual(call_order, ["bootstrap", ("ensure", bootstrap_client), "database"])

    def test_run_skips_completed_bucket_tasks_and_keeps_capped_tasks_stable_on_rerun(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = os.path.join(tmpdir, "progress.json")
            log_file = os.path.join(tmpdir, "events.jsonl")
            client = object()
            ch_client = object()
            normal_records = [{"publication_number": "CN117000001A"}]
            capped_records = [{"publication_number": "CN117000099A"}]
            capped = [{"date": "2024-04-19", "pubtype": 3, "bucket": "99", "count": 20}]

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=client,
            ), mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "create_clickhouse_client",
                return_value=ch_client,
            ), mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "ensure_database",
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "resolve_buckets",
                return_value=([("1", 1), ("99", 20)], capped),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "fetch_bucket_records",
                side_effect=[(normal_records, 0), (capped_records, 0)],
            ) as fetch_mock, mock.patch.object(
                cnipa_announcement_fetcher,
                "insert_records",
                return_value=1,
            ) as insert_mock:
                first_exit_code = cnipa_announcement_fetcher.run(
                    [
                        "--start-date",
                        "2024-04-19",
                        "--end-date",
                        "2024-04-19",
                        "--pubtypes",
                        "3",
                        "--progress-file",
                        progress_file,
                        "--log-file",
                        log_file,
                    ]
                )

            with open(progress_file, "r", encoding="utf-8") as handle:
                first_progress = json.load(handle)

            with mock.patch.object(
                cnipa_announcement_fetcher,
                "CnipaAnnouncementClient",
                return_value=client,
            ), mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "create_clickhouse_client",
                return_value=ch_client,
            ), mock.patch.object(
                cnipa_announcement_fetcher.cn_patent_fetcher,
                "ensure_database",
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "resolve_buckets",
                return_value=([("1", 1), ("99", 20)], capped),
            ), mock.patch.object(
                cnipa_announcement_fetcher,
                "fetch_bucket_records",
            ) as rerun_fetch_mock, mock.patch.object(
                cnipa_announcement_fetcher,
                "insert_records",
            ) as rerun_insert_mock:
                second_exit_code = cnipa_announcement_fetcher.run(
                    [
                        "--start-date",
                        "2024-04-19",
                        "--end-date",
                        "2024-04-19",
                        "--pubtypes",
                        "3",
                        "--progress-file",
                        progress_file,
                        "--log-file",
                        log_file,
                    ]
                )

            with open(progress_file, "r", encoding="utf-8") as handle:
                second_progress = json.load(handle)

        self.assertEqual(first_exit_code, 0)
        self.assertEqual(second_exit_code, 0)
        self.assertEqual(fetch_mock.call_count, 2)
        self.assertEqual(insert_mock.call_count, 2)
        rerun_fetch_mock.assert_not_called()
        rerun_insert_mock.assert_not_called()
        self.assertEqual(first_progress["completed_dates"], [])
        self.assertEqual(second_progress["completed_dates"], [])
        self.assertEqual(first_progress["status"], "completed_with_capped_tasks")
        self.assertEqual(second_progress["status"], "completed_with_capped_tasks")
        self.assertEqual(len(first_progress["capped_tasks"]), 1)
        self.assertEqual(len(second_progress["capped_tasks"]), 1)
        self.assertEqual(
            second_progress["completed_tasks"],
            [
                {"date": "2024-04-19", "pubtype": 3, "bucket": "1"},
                {"date": "2024-04-19", "pubtype": 3, "bucket": "99"},
            ],
        )


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SequenceClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


class FakeBucketClient:
    def __init__(self, counts=None, pages=None):
        self.counts = counts or {}
        self.pages = pages or {}
        self.count_calls = []
        self.search_calls = []

    def count_bucket(self, keyword, announcement_date, pubtype):
        self.count_calls.append(keyword)
        return self.counts[keyword]

    def search_bucket(self, keyword, announcement_date, pubtype, offset=0, size=100):
        self.search_calls.append((keyword, offset, size))
        return self.pages.get((keyword, offset, size), [])


if __name__ == "__main__":
    unittest.main()
