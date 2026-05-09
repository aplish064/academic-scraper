import csv
import os
import sys
import tempfile
import types
import unittest
import zipfile
from datetime import date
from unittest import mock


if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)

from src import cn_patent_fetcher


class ChinaPatentParserTests(unittest.TestCase):
    def test_parse_cn_patent_record_maps_common_chinese_fields(self):
        record = {
            "申请号": "CN202410000001.2",
            "公开号": "CN117000001A",
            "专利名称": "一种学术数据处理方法",
            "摘要": "用于测试的中国专利摘要。",
            "申请日": "2024-01-15",
            "公开日": "2024-04-19",
            "申请人": "示例大学; 北京样例科技有限公司",
            "发明人": "张三; 李四",
            "IPC分类号": "G06F16/00; G06F40/00",
            "法律状态": "公开",
        }

        row = cn_patent_fetcher.parse_cn_patent_record(record)

        self.assertEqual(row["source"], "cnipa")
        self.assertEqual(row["country"], "CN")
        self.assertEqual(row["patent_id"], "cnipa:publication:CN117000001A")
        self.assertEqual(row["patent_title"], "一种学术数据处理方法")
        self.assertEqual(row["patent_abstract"], "用于测试的中国专利摘要。")
        self.assertEqual(row["application_date"], date(2024, 1, 15))
        self.assertEqual(row["publication_date"], date(2024, 4, 19))
        self.assertEqual(row["grant_date"], date(1970, 1, 1))
        self.assertEqual(row["status"], "公开")
        self.assertEqual(row["application_number"], "CN202410000001.2")
        self.assertEqual(row["publication_number"], "CN117000001A")
        self.assertEqual(row["inventors"], ["张三", "李四"])
        self.assertEqual(row["assignees"], ["示例大学", "北京样例科技有限公司"])
        self.assertEqual(row["ipc_codes"], ["G06F16/00", "G06F40/00"])
        self.assertEqual(row["cpc_codes"], [])
        self.assertIn('"申请号": "CN202410000001.2"', row["raw_json"])
        self.assertEqual(row["source_url"], "https://pss-system.cponline.cnipa.gov.cn/")

    def test_parse_cn_patent_record_uses_application_number_when_publication_missing(self):
        row = cn_patent_fetcher.parse_cn_patent_record({
            "申请号": "202310123456.7",
            "名称": "一种测试装置",
            "申请日": "2023.05.01",
        })

        self.assertEqual(row["patent_id"], "cnipa:application:CN202310123456.7")
        self.assertEqual(row["application_number"], "CN202310123456.7")
        self.assertEqual(row["patent_title"], "一种测试装置")
        self.assertEqual(row["num_claims"], 0)
        self.assertEqual(row["num_cited_by"], 0)
        self.assertEqual(row["num_citations"], 0)
        self.assertEqual(row["family_id"], "")

    def test_parse_cn_patent_record_preserves_record_source(self):
        row = cn_patent_fetcher.parse_cn_patent_record(
            {
                "source": "google_patents",
                "publication_number": "CN111915025B",
                "title": "test",
            }
        )

        self.assertEqual(row["source"], "google_patents")
        self.assertEqual(row["patent_id"], "google_patents:publication:CN111915025B")
        self.assertEqual(row["source_url"], "https://patents.google.com/patent/CN111915025B")

    def test_parse_cn_patent_record_preserves_google_source_url_when_provided(self):
        row = cn_patent_fetcher.parse_cn_patent_record(
            {
                "source": "google_patents",
                "publication_number": "CN111915025B",
                "title": "test",
                "source_url": "https://example.test/patent/CN111915025B",
            }
        )

        self.assertEqual(row["source_url"], "https://example.test/patent/CN111915025B")

    def test_parse_cn_patent_record_defaults_to_cnipa_source(self):
        row = cn_patent_fetcher.parse_cn_patent_record(
            {
                "publication_number": "CN111915025B",
                "title": "test",
            }
        )

        self.assertEqual(row["source"], "cnipa")
        self.assertEqual(row["patent_id"], "cnipa:publication:CN111915025B")

    def test_parse_cn_patent_record_defaults_blank_source_to_cnipa(self):
        row = cn_patent_fetcher.parse_cn_patent_record(
            {
                "source": "   ",
                "publication_number": "CN111915025B",
                "title": "test",
            }
        )

        self.assertEqual(row["source"], "cnipa")
        self.assertEqual(row["patent_id"], "cnipa:publication:CN111915025B")

    def test_parse_cn_patent_record_uses_google_patents_application_id(self):
        row = cn_patent_fetcher.parse_cn_patent_record(
            {
                "source": "google_patents",
                "application_number": "CN202310123456.7",
                "title": "test",
            }
        )

        self.assertEqual(row["source"], "google_patents")
        self.assertEqual(row["patent_id"], "google_patents:application:CN202310123456.7")
        self.assertEqual(row["application_number"], "CN202310123456.7")
        self.assertEqual(row["publication_number"], "")

    def test_parse_cn_patent_record_parses_cpc_codes_when_present(self):
        row = cn_patent_fetcher.parse_cn_patent_record(
            {
                "申请号": "CN202410000001.2",
                "IPC分类号": "G06F16/00; G06F40/00",
                "CPC分类号": "H04L67/10; G06F17/30",
            }
        )

        self.assertEqual(row["ipc_codes"], ["G06F16/00", "G06F40/00"])
        self.assertEqual(row["cpc_codes"], ["H04L67/10", "G06F17/30"])
        self.assertEqual(row["uspc_codes"], [])
        self.assertEqual(row["source_url"], "https://pss-system.cponline.cnipa.gov.cn/")

    def test_parse_cn_patent_record_logs_warning_and_hash_id_for_missing_identifiers(self):
        record = {
            "专利名称": "无公开号无申请号测试",
            "申请日": "2024-01-15",
            "公开日": "2024-04-19",
            "发明人": "张三",
            "申请人": "示例大学",
        }

        with mock.patch("src.cn_patent_fetcher.log_message") as log_message:
            row = cn_patent_fetcher.parse_cn_patent_record(record)

        self.assertTrue(row["patent_id"].startswith("cnipa:hash:"))
        log_message.assert_called_once()
        args, kwargs = log_message.call_args
        self.assertIn("record_id_fallback source=cnipa reason=missing_identifier", args[0])
        self.assertEqual(args[1], "WARNING")
        self.assertEqual(kwargs, {})

    def test_parse_cn_patent_record_uses_google_patents_hash_id_and_warning(self):
        record = {
            "source": "google_patents",
            "title": "test",
        }

        with mock.patch("src.cn_patent_fetcher.log_message") as log_message:
            row = cn_patent_fetcher.parse_cn_patent_record(record)

        self.assertEqual(row["source"], "google_patents")
        self.assertTrue(row["patent_id"].startswith("google_patents:hash:"))
        log_message.assert_called_once()
        args, kwargs = log_message.call_args
        self.assertIn("record_id_fallback source=google_patents reason=missing_identifier", args[0])
        self.assertEqual(args[1], "WARNING")
        self.assertEqual(kwargs, {})

    def test_parse_ipc_rows_fallback_logs_and_decomposes_malformed_code(self):
        with mock.patch("src.cn_patent_fetcher.log_message") as log_message:
            patent = cn_patent_fetcher.parse_cn_patent_record({
                "申请号": "CN202410000001.2",
                "IPC": "G06F16",
            })
            rows = cn_patent_fetcher.parse_ipc_rows(patent)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ipc_section"], "G")
        self.assertEqual(rows[0]["ipc_class"], "06")
        self.assertEqual(rows[0]["ipc_subclass"], "F")
        self.assertEqual(rows[0]["ipc_group"], "16")
        self.assertEqual(rows[0]["is_primary"], 1)
        self.assertTrue(any("parse_ipc_fallback" in str(call.args[0]) for call in log_message.call_args_list))

    def test_parse_ipc_rows_decomposes_ipc_codes(self):
        patent = cn_patent_fetcher.parse_cn_patent_record({
            "申请号": "CN202410000001.2",
            "公开号": "CN117000001A",
            "IPC": "G06F16/00; H04L67/00",
        })

        rows = cn_patent_fetcher.parse_ipc_rows(patent)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ipc_section"], "G")
        self.assertEqual(rows[0]["ipc_class"], "06")
        self.assertEqual(rows[0]["ipc_subclass"], "F")
        self.assertEqual(rows[0]["ipc_group"], "16/00")
        self.assertEqual(rows[0]["is_primary"], 1)
        self.assertEqual(rows[1]["is_primary"], 0)

    def test_parse_ipc_rows_uses_record_source(self):
        patent = cn_patent_fetcher.parse_cn_patent_record(
            {
                "source": "google_patents",
                "publication_number": "CN111915025B",
                "title": "test",
                "ipc_codes": "G06F16/00",
            }
        )

        rows = cn_patent_fetcher.parse_ipc_rows(patent)

        self.assertEqual(rows[0]["source"], "google_patents")

    def test_expand_patent_rows_preserves_record_source(self):
        patent = cn_patent_fetcher.parse_cn_patent_record(
            {
                "source": "google_patents",
                "publication_number": "CN111915025B",
                "title": "test",
                "ipc_codes": "G06F16/00",
            }
        )

        expanded = cn_patent_fetcher.expand_patent_rows(patent)

        self.assertEqual(expanded["patents"][0]["source"], "google_patents")
        self.assertEqual(expanded["ipc"][0]["source"], "google_patents")

    def test_expand_patent_rows_defaults_blank_source_to_cnipa(self):
        patent = {
            "patent_id": "cnipa:publication:CN111915025B",
            "source": "   ",
            "publication_number": "CN111915025B",
            "patent_title": "test",
        }

        expanded = cn_patent_fetcher.expand_patent_rows(patent)

        self.assertEqual(expanded["patents"][0]["source"], "cnipa")

    def test_expand_patent_rows_preserves_country(self):
        patent = {
            "patent_id": "google_patents:publication:US123B",
            "source": "google_patents",
            "country": "US",
            "publication_number": "US123B",
            "patent_title": "test",
        }

        expanded = cn_patent_fetcher.expand_patent_rows(patent)

        self.assertEqual(expanded["patents"][0]["country"], "US")


class ChinaPatentInputTests(unittest.TestCase):
    def test_iter_input_records_reads_csv_and_zip_members(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "cn.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["申请号", "专利名称"])
                writer.writeheader()
                writer.writerow({"申请号": "CN1", "专利名称": "CSV专利"})

            zip_path = os.path.join(tmpdir, "cn.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("nested/cn.csv", "申请号,专利名称\nCN2,ZIP专利\n")

            records = list(cn_patent_fetcher.iter_input_records(tmpdir))

        titles = [record["专利名称"] for record in records]
        self.assertEqual(titles, ["CSV专利", "ZIP专利"])

    def test_row_to_insert_values_matches_patent_columns(self):
        row = cn_patent_fetcher.parse_cn_patent_record({"申请号": "CN202410000001.2", "名称": "测试"})

        values = cn_patent_fetcher.row_to_insert_values(row, cn_patent_fetcher.PATENT_COLUMNS)

        self.assertEqual(len(values), len(cn_patent_fetcher.PATENT_COLUMNS))
        self.assertEqual(values[cn_patent_fetcher.PATENT_COLUMNS.index("source")], "cnipa")

    def test_create_ipc_table_sql_targets_patent_db(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS patent_db.patent_ipc", cn_patent_fetcher.CREATE_PATENT_IPC_TABLE_SQL)
        self.assertIn("ORDER BY (source, patent_id, ipc_code)", cn_patent_fetcher.CREATE_PATENT_IPC_TABLE_SQL)


class ChinaPatentProgressAndRunTests(unittest.TestCase):
    def test_run_dry_run_does_not_persist_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "cn.csv")
            log_path = os.path.join(tmpdir, "cn.log")
            progress_path = os.path.join(tmpdir, "progress.json")

            with open(input_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["申请号", "专利名称"])
                writer.writeheader()
                writer.writerow({"申请号": "CN1", "专利名称": "A"})
                writer.writerow({"申请号": "CN2", "专利名称": "B"})

            exit_code = cn_patent_fetcher.run(
                [
                    "--input",
                    input_path,
                    "--dry-run",
                    "--log-file",
                    log_path,
                    "--progress-file",
                    progress_path,
                ]
            )

            self.assertEqual(exit_code, 0)
            progress = cn_patent_fetcher.load_progress(progress_path)
            self.assertEqual(progress.get("completed_files", []), [])

            log_payload = open(log_path, "r", encoding="utf-8").read()
            self.assertIn("run completed:", log_payload)
            self.assertIn("raw_records=2", log_payload)
            self.assertIn("patents=2", log_payload)

    def test_run_dry_run_does_not_mark_completed_when_limit_stops_file_early(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "cn.csv")
            log_path = os.path.join(tmpdir, "cn.log")
            progress_path = os.path.join(tmpdir, "progress.json")

            with open(input_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["申请号", "专利名称"])
                writer.writeheader()
                writer.writerow({"申请号": "CN1", "专利名称": "A"})
                writer.writerow({"申请号": "CN2", "专利名称": "B"})

            exit_code = cn_patent_fetcher.run(
                [
                    "--input",
                    input_path,
                    "--dry-run",
                    "--limit",
                    "1",
                    "--log-file",
                    log_path,
                    "--progress-file",
                    progress_path,
                ]
            )

            self.assertEqual(exit_code, 0)
            progress = cn_patent_fetcher.load_progress(progress_path)
            self.assertEqual(progress.get("completed_files", []), [])

    def test_run_dry_run_logs_missing_identifier_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "cn.csv")
            log_path = os.path.join(tmpdir, "cn.log")
            progress_path = os.path.join(tmpdir, "progress.json")

            with open(input_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["专利名称"])
                writer.writeheader()
                writer.writerow({"专利名称": "仅有标题专利"})

            exit_code = cn_patent_fetcher.run(
                [
                    "--input",
                    input_path,
                    "--dry-run",
                    "--log-file",
                    log_path,
                    "--progress-file",
                    progress_path,
                ]
            )

            self.assertEqual(exit_code, 0)
            log_payload = open(log_path, "r", encoding="utf-8").read()
            self.assertIn("record_id_fallback", log_payload)
            self.assertIn("missing_identifier", log_payload)

    def test_iter_input_records_skips_bad_json_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "cn.jsonl")
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write("{\"申请号\": \"CN1\", \"专利名称\": \"ok1\"}\n")
                handle.write("{bad json}\n")
                handle.write("not-json\n")
                handle.write("{\"申请号\": \"CN2\", \"专利名称\": \"ok2\"}\n")

            records = list(cn_patent_fetcher.iter_input_records(input_path))
            titles = [record["专利名称"] for record in records]
            self.assertEqual(titles, ["ok1", "ok2"])


if __name__ == "__main__":
    unittest.main()
