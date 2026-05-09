import json
import tempfile
import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

if "clickhouse_connect" not in sys.modules:
    sys.modules["clickhouse_connect"] = types.SimpleNamespace(get_client=lambda **_kwargs: None)

from src import cn_patent_fetcher
from src import google_patent_fetcher


class FakeRow:
    def __init__(self, **items):
        self._items = items

    def items(self):
        return self._items.items()

    def get(self, key, default=None):
        return self._items.get(key, default)


class FakeQueryJob:
    def __init__(self):
        self.page_size = None
        self.rows = ["row"]
        self.job_id = "fake-job-id"

    def result(self, page_size=None):
        self.page_size = page_size
        return self.rows


class FakeBigQueryClient:
    def __init__(self):
        self.sql = None
        self.job_config = None
        self.job = FakeQueryJob()
        self.dataset_created = None

    def query(self, sql, job_config=None):
        self.sql = sql
        self.job_config = job_config
        return self.job

    def dataset(self, dataset_id):
        return f"dataset:{dataset_id}"

    def create_dataset(self, dataset, exists_ok=False):
        self.dataset_created = (dataset, exists_ok)
        return dataset


class FakeScalarQueryParameter:
    def __init__(self, name, type_, value):
        self.name = name
        self.type_ = type_
        self.value = value


class FakeDryRunJobConfig:
    def __init__(self, **kwargs):
        self.dry_run = kwargs.get("dry_run")
        self.use_query_cache = kwargs.get("use_query_cache")
        self.query_parameters = kwargs.get("query_parameters")
        self.maximum_bytes_billed = kwargs.get("maximum_bytes_billed")


class FakeDryRunBigQuery:
    ScalarQueryParameter = FakeScalarQueryParameter
    QueryJobConfig = FakeDryRunJobConfig


class GooglePatentFetcherTests(unittest.TestCase):
    def test_parse_args_defaults(self):
        args = google_patent_fetcher.parse_args([])

        self.assertEqual(args.country, "CN")
        self.assertIsNone(args.start_date)
        self.assertIsNone(args.end_date)
        self.assertIsNone(args.limit)
        self.assertEqual(args.batch_size, 5000)
        self.assertEqual(args.page_size, 10000)
        self.assertFalse(args.dry_run)
        self.assertFalse(args.estimate_only)
        self.assertEqual(args.credentials, "data/patent-494208-e330c3351d40.json")
        self.assertEqual(args.log_file, "log/google_patent_fetcher.log")
        self.assertEqual(args.progress_file, "log/google_patent_fetch_progress.json")
        self.assertFalse(args.create_staging)
        self.assertEqual(args.staging_dataset, "google_patents_staging")
        self.assertEqual(args.staging_table, "cn_publications")
        self.assertIsNone(args.source_table)
        self.assertIsNone(args.max_bytes_billed)
        self.assertFalse(args.windowed)
        self.assertEqual(args.window_days, 7)
        self.assertTrue(args.resume_windowed)
        self.assertFalse(args.windowed_staging)
        self.assertFalse(args.keep_window_staging)
        self.assertEqual(args.temp_staging_prefix, "cn_publications_window")

    def test_build_source_table_id_defaults_to_publications_table(self):
        args = google_patent_fetcher.parse_args([])

        self.assertEqual(
            google_patent_fetcher.build_source_table_id(args),
            "patents-public-data.patents.publications",
        )

    def test_build_source_table_id_uses_source_table_override(self):
        args = google_patent_fetcher.parse_args(["--source-table", "project.dataset.table"])

        self.assertEqual(google_patent_fetcher.build_source_table_id(args), "project.dataset.table")

    def test_build_staging_table_id_uses_client_project(self):
        args = google_patent_fetcher.parse_args(
            ["--staging-dataset", "stage_ds", "--staging-table", "cn_stage"]
        )
        client = types.SimpleNamespace(project="patent-project")

        self.assertEqual(
            google_patent_fetcher.build_staging_table_id(client, args),
            "patent-project.stage_ds.cn_stage",
        )

    def test_build_publications_query_accepts_custom_source_table(self):
        query = google_patent_fetcher.build_publications_query(
            country="CN",
            start_date=None,
            end_date=None,
            limit=10,
            source_table="project.dataset.cn_publications",
        )

        self.assertIn("`project.dataset.cn_publications`", query)
        self.assertNotIn("`patents-public-data.patents.publications`", query)

    def test_build_create_staging_query_writes_filtered_cn_rows(self):
        query = google_patent_fetcher.build_create_staging_query(
            target_table="project.stage.cn_publications",
            country="CN",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        self.assertIn("CREATE OR REPLACE TABLE `project.stage.cn_publications` AS", query)
        self.assertIn("FROM `patents-public-data.patents.publications`", query)
        self.assertIn("country_code = @country", query)
        self.assertIn("publication_date >= @start_date", query)
        self.assertIn("publication_date <= @end_date", query)

    def test_create_staging_table_creates_dataset_and_runs_query(self):
        client = FakeBigQueryClient()

        target_table = google_patent_fetcher.create_staging_table(
            client,
            dataset_id="google_patents_staging",
            table_id="cn_publications",
            country="CN",
            start_date="2024-01-01",
            end_date=None,
            max_bytes_billed=123456,
        )

        self.assertEqual(target_table, "google_patents_staging.cn_publications")
        self.assertEqual(client.dataset_created, ("dataset:google_patents_staging", True))
        self.assertIn("CREATE OR REPLACE TABLE `google_patents_staging.cn_publications` AS", client.sql)
        self.assertEqual(client.job.page_size, None)
        self.assertEqual(client.job_config.maximum_bytes_billed, 123456)

    def test_estimate_query_bytes_builds_dry_run_config_and_params(self):
        client = FakeBigQueryClient()
        client.job.total_bytes_processed = 123456

        with mock.patch.object(google_patent_fetcher, "_load_bigquery", return_value=FakeDryRunBigQuery):
            total_bytes = google_patent_fetcher.estimate_query_bytes(
                client,
                "SELECT * FROM publications",
                country="CN",
                start_date="2024-01-02",
                end_date="2024-02-03",
            )

        params = {param.name: param for param in client.job_config.query_parameters}
        self.assertEqual(total_bytes, 123456)
        self.assertEqual(client.sql, "SELECT * FROM publications")
        self.assertTrue(client.job_config.dry_run)
        self.assertFalse(client.job_config.use_query_cache)
        self.assertEqual(params["country"].value, "CN")
        self.assertEqual(params["start_date"].value, 20240102)
        self.assertEqual(params["end_date"].value, 20240203)

    def test_iter_date_windows_splits_inclusive_ranges(self):
        windows = list(google_patent_fetcher.iter_date_windows("2024-01-01", "2024-01-05", 2))

        self.assertEqual(
            windows,
            [
                ("2024-01-01", "2024-01-02"),
                ("2024-01-03", "2024-01-04"),
                ("2024-01-05", "2024-01-05"),
            ],
        )

    def test_stream_query_rows_passes_maximum_bytes_billed(self):
        client = FakeBigQueryClient()

        google_patent_fetcher.stream_query_rows(
            client,
            "SELECT * FROM publications",
            country="CN",
            page_size=250,
            max_bytes_billed=123456,
        )

        self.assertEqual(client.job_config.maximum_bytes_billed, 123456)

    def test_build_temp_staging_table_id_uses_safe_window_name(self):
        client = types.SimpleNamespace(project="patent-project")
        args = google_patent_fetcher.parse_args(
            ["--staging-dataset", "stage_ds", "--temp-staging-prefix", "cn_tmp"]
        )

        table_id = google_patent_fetcher.build_temp_staging_table_id(
            client,
            args,
            "2024-01-01",
            "2024-01-02",
        )

        self.assertEqual(table_id, "patent-project.stage_ds.cn_tmp_20240101_20240102")

    def test_run_windowed_skips_completed_windows_and_records_progress(self):
        rows = ["row-1", "row-2"]
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = f"{tmpdir}/progress.json"
            google_patent_fetcher.write_progress(
                progress_file,
                completed_windows={
                    "2024-01-01:2024-01-02": {
                        "inserted_patents": 10,
                        "estimated_bytes": 99,
                    }
                },
            )

            with mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value="bq-client"), \
                mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=42) as estimate, \
                mock.patch.object(google_patent_fetcher, "stream_query_rows", return_value=rows) as stream_rows, \
                mock.patch.object(cn_patent_fetcher, "create_clickhouse_client", return_value="ch-client"), \
                mock.patch.object(cn_patent_fetcher, "ensure_database"), \
                mock.patch.object(google_patent_fetcher, "process_bigquery_batch", side_effect=lambda *_args: len(_args[1])):
                stdout = StringIO()
                with redirect_stdout(stdout):
                    result = google_patent_fetcher.run(
                        [
                            "--windowed",
                            "--start-date",
                            "2024-01-01",
                            "--end-date",
                            "2024-01-03",
                            "--window-days",
                            "2",
                            "--batch-size",
                            "2",
                            "--log-file",
                            "",
                            "--progress-file",
                            progress_file,
                        ]
                    )

            progress = json.loads(open(progress_file, encoding="utf-8").read())

        self.assertEqual(result, 0)
        self.assertEqual(estimate.call_count, 1)
        self.assertEqual(stream_rows.call_args.kwargs["start_date"], "2024-01-03")
        self.assertEqual(stream_rows.call_args.kwargs["end_date"], "2024-01-03")
        self.assertIn("window_skipped=2024-01-01:2024-01-02", stdout.getvalue())
        self.assertEqual(progress["phase"], "windowed_import")
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["inserted_patents_total"], 12)
        self.assertIn("2024-01-03:2024-01-03", progress["completed_windows"])

    def test_run_windowed_estimate_only_does_not_connect_clickhouse(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
            mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value="bq-client"), \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=42) as estimate, \
            mock.patch.object(cn_patent_fetcher, "create_clickhouse_client") as create_ch:
            progress_file = f"{tmpdir}/progress.json"
            result = google_patent_fetcher.run(
                [
                    "--windowed",
                    "--estimate-only",
                    "--start-date",
                    "2024-01-01",
                    "--end-date",
                    "2024-01-03",
                    "--window-days",
                    "2",
                    "--log-file",
                    "",
                    "--progress-file",
                    progress_file,
                ]
            )
            progress = json.loads(open(progress_file, encoding="utf-8").read())

        self.assertEqual(result, 0)
        self.assertEqual(estimate.call_count, 2)
        create_ch.assert_not_called()
        self.assertEqual(progress["phase"], "windowed_import")
        self.assertEqual(progress["status"], "estimated")
        self.assertEqual(progress["estimated_bytes_total"], 84)

    def test_run_windowed_staging_creates_reads_and_drops_temp_table(self):
        rows = ["row-1", "row-2"]
        created_tables = []
        dropped_tables = []

        def fake_create_staging(client, dataset_id, table_id, country, start_date=None, end_date=None, **_kwargs):
            table = f"project.{dataset_id}.{table_id}"
            created_tables.append((table, start_date, end_date))
            return table

        with tempfile.TemporaryDirectory() as tmpdir, \
            mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value=types.SimpleNamespace(project="project")), \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=42), \
            mock.patch.object(google_patent_fetcher, "create_staging_table", side_effect=fake_create_staging) as create_staging, \
            mock.patch.object(google_patent_fetcher, "stream_query_rows", return_value=rows) as stream_rows, \
            mock.patch.object(google_patent_fetcher, "delete_bigquery_table", side_effect=lambda _client, table_id: dropped_tables.append(table_id)), \
            mock.patch.object(cn_patent_fetcher, "create_clickhouse_client", return_value="ch-client"), \
            mock.patch.object(cn_patent_fetcher, "ensure_database"), \
            mock.patch.object(google_patent_fetcher, "process_bigquery_batch", side_effect=lambda *_args: len(_args[1])):
            progress_file = f"{tmpdir}/progress.json"
            result = google_patent_fetcher.run(
                [
                    "--windowed",
                    "--windowed-staging",
                    "--start-date",
                    "2024-01-01",
                    "--end-date",
                    "2024-01-01",
                    "--window-days",
                    "1",
                    "--batch-size",
                    "2",
                    "--log-file",
                    "",
                    "--progress-file",
                    progress_file,
                ]
            )
            progress = json.loads(open(progress_file, encoding="utf-8").read())

        self.assertEqual(result, 0)
        create_staging.assert_called_once()
        self.assertEqual(created_tables, [("project.google_patents_staging.cn_publications_window_20240101_20240101", "2024-01-01", "2024-01-01")])
        sql = stream_rows.call_args.args[1]
        self.assertIn("`project.google_patents_staging.cn_publications_window_20240101_20240101`", sql)
        self.assertEqual(dropped_tables, ["project.google_patents_staging.cn_publications_window_20240101_20240101"])
        self.assertEqual(progress["status"], "completed")
        self.assertTrue(progress["completed_windows"]["2024-01-01:2024-01-01"]["temp_staging_deleted"])

    def test_create_bigquery_client_uses_service_account_project(self):
        credentials = types.SimpleNamespace(project_id="patent-project")
        fake_service_account = types.SimpleNamespace(
            Credentials=types.SimpleNamespace(
                from_service_account_file=mock.Mock(return_value=credentials)
            )
        )
        fake_bigquery = types.SimpleNamespace(Client=mock.Mock(return_value="client"))

        with mock.patch.object(google_patent_fetcher, "require_bigquery", return_value=fake_bigquery), \
            mock.patch.dict(sys.modules, {"google.oauth2": types.SimpleNamespace(service_account=fake_service_account)}):
            client = google_patent_fetcher.create_bigquery_client("credentials.json")

        self.assertEqual(client, "client")
        fake_service_account.Credentials.from_service_account_file.assert_called_once_with("credentials.json")
        fake_bigquery.Client.assert_called_once_with(credentials=credentials, project="patent-project")

    def test_run_estimate_only_does_not_stream_rows(self):
        with mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value=object()), \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=42), \
            mock.patch.object(google_patent_fetcher, "stream_query_rows") as stream_rows:
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = google_patent_fetcher.run(["--estimate-only", "--log-file", ""])

        self.assertEqual(result, 0)
        self.assertIn("estimated_bytes=42", stdout.getvalue())
        stream_rows.assert_not_called()

    def test_run_create_staging_returns_after_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
            mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value="client"), \
            mock.patch.object(google_patent_fetcher, "create_staging_table", return_value="project.stage.cn") as create_staging, \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=123) as estimate:
            progress_file = f"{tmpdir}/progress.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = google_patent_fetcher.run(
                    [
                        "--create-staging",
                        "--staging-dataset",
                        "stage",
                        "--staging-table",
                        "cn",
                        "--max-bytes-billed",
                        "456",
                        "--log-file",
                        "",
                        "--progress-file",
                        progress_file,
                    ]
                )

            progress = json.loads(open(progress_file, encoding="utf-8").read())
        self.assertEqual(result, 0)
        create_staging.assert_called_once()
        estimate.assert_called_once()
        self.assertEqual(create_staging.call_args.kwargs["max_bytes_billed"], 456)
        self.assertEqual(create_staging.call_args.kwargs["progress_file"], progress_file)
        self.assertEqual(progress["phase"], "create_staging")
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["staging_table"], "project.stage.cn")
        self.assertEqual(progress["estimated_bytes"], 123)
        self.assertIn("staging_estimated_bytes=123", stdout.getvalue())
        self.assertIn("staging_table=project.stage.cn", stdout.getvalue())

    def test_run_create_staging_estimate_only_does_not_create_table(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
            mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value="client"), \
            mock.patch.object(google_patent_fetcher, "create_staging_table") as create_staging, \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=789):
            progress_file = f"{tmpdir}/progress.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = google_patent_fetcher.run(
                    [
                        "--create-staging",
                        "--estimate-only",
                        "--staging-dataset",
                        "stage",
                        "--staging-table",
                        "cn",
                        "--log-file",
                        "",
                        "--progress-file",
                        progress_file,
                    ]
                )

            progress = json.loads(open(progress_file, encoding="utf-8").read())
        self.assertEqual(result, 0)
        create_staging.assert_not_called()
        self.assertEqual(progress["phase"], "create_staging")
        self.assertEqual(progress["status"], "estimated")
        self.assertEqual(progress["estimated_bytes"], 789)
        self.assertIn("staging_estimated_bytes=789", stdout.getvalue())

    def test_create_staging_table_records_running_bigquery_job(self):
        client = FakeBigQueryClient()
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = f"{tmpdir}/progress.json"

            google_patent_fetcher.create_staging_table(
                client,
                dataset_id="google_patents_staging",
                table_id="cn_publications",
                country="CN",
                progress_file=progress_file,
            )

            progress = json.loads(open(progress_file, encoding="utf-8").read())

        self.assertEqual(progress["phase"], "create_staging")
        self.assertEqual(progress["status"], "running")
        self.assertEqual(progress["bigquery_job_id"], "fake-job-id")

    def test_run_non_dry_run_records_insert_progress(self):
        rows = ["row-1", "row-2", "row-3"]

        with tempfile.TemporaryDirectory() as tmpdir, \
            mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value=object()), \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=42), \
            mock.patch.object(google_patent_fetcher, "stream_query_rows", return_value=rows), \
            mock.patch.object(cn_patent_fetcher, "create_clickhouse_client", return_value="ch-client"), \
            mock.patch.object(cn_patent_fetcher, "ensure_database"), \
            mock.patch.object(google_patent_fetcher, "process_bigquery_batch", side_effect=lambda *_args: len(_args[1])):
            progress_file = f"{tmpdir}/progress.json"
            result = google_patent_fetcher.run(
                ["--batch-size", "2", "--log-file", "", "--progress-file", progress_file]
            )

            progress = json.loads(open(progress_file, encoding="utf-8").read())

        self.assertEqual(result, 0)
        self.assertEqual(progress["phase"], "import_clickhouse")
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["inserted_patents"], 3)
        self.assertEqual(progress["last_batch_size"], 1)

    def test_run_source_table_uses_override_for_query(self):
        with mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value="client"), \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=42), \
            mock.patch.object(google_patent_fetcher, "stream_query_rows", return_value=[]) as stream_rows:
            google_patent_fetcher.run(
                ["--source-table", "project.stage.cn", "--dry-run", "--log-file", "", "--progress-file", ""]
            )

        sql = stream_rows.call_args.args[1]
        self.assertIn("`project.stage.cn`", sql)

    def test_run_dry_run_counts_mapped_rows_in_batches(self):
        rows = [
            {"publication_number": "CN-1-A"},
            {"publication_number": "CN-2-A"},
            {"publication_number": "CN-3-A"},
        ]

        with mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value="client"), \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=99), \
            mock.patch.object(google_patent_fetcher, "stream_query_rows", return_value=rows) as stream_rows, \
            mock.patch.object(google_patent_fetcher, "map_bigquery_row", wraps=google_patent_fetcher.map_bigquery_row) as mapper:
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = google_patent_fetcher.run(
                    ["--dry-run", "--batch-size", "2", "--page-size", "7", "--log-file", ""]
                )

        self.assertEqual(result, 0)
        self.assertIn("dry_run_records=3", stdout.getvalue())
        stream_rows.assert_called_once()
        self.assertEqual(stream_rows.call_args.kwargs["page_size"], 7)
        self.assertEqual(mapper.call_count, 3)

    def test_process_bigquery_batch_inserts_expanded_patent_tables(self):
        rows = [
            {
                "publication_number": "CN-111915025-B",
                "application_number": "CN-202010777888-A",
                "country_code": "CN",
                "family_id": "12345",
                "title_localized": [{"text": "中文标题", "language": "zh"}],
                "abstract_localized": [{"text": "中文摘要", "language": "zh"}],
                "publication_date": 20240430,
                "filing_date": 20240115,
                "grant_date": 20240501,
                "inventor": ["张三", "李四"],
                "assignee": ["某公司"],
                "ipc": [{"code": "G06F16/00"}, {"code": "G06F40/00"}],
            }
        ]
        calls = []

        def fake_insert_table(client, table_name, inserted_rows, columns, batch_size):
            calls.append((client, table_name, list(inserted_rows), columns, batch_size))
            return len(inserted_rows)

        with mock.patch.object(cn_patent_fetcher, "insert_table", side_effect=fake_insert_table):
            processed = google_patent_fetcher.process_bigquery_batch("ch-client", rows, batch_size=17)

        self.assertEqual(processed, 1)
        table_names = [call[1] for call in calls]
        self.assertEqual(
            table_names,
            [
                cn_patent_fetcher.CH_TABLE,
                cn_patent_fetcher.CH_APPLICATIONS_TABLE,
                cn_patent_fetcher.CH_INVENTORS_TABLE,
                cn_patent_fetcher.CH_ASSIGNEES_TABLE,
                cn_patent_fetcher.CH_ABSTRACTS_TABLE,
                cn_patent_fetcher.CH_IPC_TABLE,
            ],
        )
        self.assertEqual([call[4] for call in calls], [17, 17, 17, 17, 17, 17])
        self.assertEqual(len(calls[0][2]), 1)
        self.assertEqual(len(calls[1][2]), 1)
        self.assertEqual(len(calls[2][2]), 2)
        self.assertEqual(len(calls[3][2]), 1)
        self.assertEqual(len(calls[4][2]), 1)
        self.assertEqual(len(calls[5][2]), 2)
        self.assertEqual(calls[0][3], cn_patent_fetcher.PATENT_COLUMNS)
        self.assertEqual(calls[1][3], cn_patent_fetcher.APPLICATION_COLUMNS)
        self.assertEqual(calls[2][3], cn_patent_fetcher.INVENTOR_COLUMNS)
        self.assertEqual(calls[3][3], cn_patent_fetcher.ASSIGNEE_COLUMNS)
        self.assertEqual(calls[4][3], cn_patent_fetcher.ABSTRACT_COLUMNS)
        self.assertEqual(calls[5][3], cn_patent_fetcher.IPC_COLUMNS)

    def test_process_bigquery_batch_skips_empty_child_tables_and_counts_patents(self):
        rows = [
            {
                "publication_number": "CN-111915025-B",
                "country_code": "CN",
                "title_localized": [{"text": "中文标题", "language": "zh"}],
            }
        ]
        calls = []

        with mock.patch.object(
            cn_patent_fetcher,
            "insert_table",
            side_effect=lambda client, table_name, inserted_rows, columns, batch_size: calls.append(table_name) or len(inserted_rows),
        ):
            processed = google_patent_fetcher.process_bigquery_batch("ch-client", rows, batch_size=5)

        self.assertEqual(processed, 1)
        self.assertEqual(calls, [cn_patent_fetcher.CH_TABLE])

    def test_run_non_dry_run_streams_batches_to_clickhouse(self):
        rows = ["row-1", "row-2", "row-3"]
        processed_batches = []

        def fake_process_batch(ch_client, batch, batch_size):
            processed_batches.append((ch_client, list(batch), batch_size))
            return len(batch)

        with mock.patch.object(google_patent_fetcher, "create_bigquery_client", return_value=object()), \
            mock.patch.object(google_patent_fetcher, "estimate_query_bytes", return_value=42), \
            mock.patch.object(google_patent_fetcher, "stream_query_rows", return_value=rows) as stream_rows, \
            mock.patch.object(cn_patent_fetcher, "create_clickhouse_client", return_value="ch-client") as create_ch, \
            mock.patch.object(cn_patent_fetcher, "ensure_database") as ensure_database, \
            mock.patch.object(google_patent_fetcher, "process_bigquery_batch", side_effect=fake_process_batch):
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = google_patent_fetcher.run(
                    ["--batch-size", "2", "--page-size", "7", "--log-file", ""]
                )

        self.assertEqual(result, 0)
        create_ch.assert_called_once_with()
        ensure_database.assert_called_once_with("ch-client")
        stream_rows.assert_called_once()
        self.assertEqual(stream_rows.call_args.kwargs["page_size"], 7)
        self.assertEqual(processed_batches, [("ch-client", ["row-1", "row-2"], 2), ("ch-client", ["row-3"], 2)])
        self.assertIn("inserted_patents=2", stdout.getvalue())
        self.assertIn("inserted_patents=3", stdout.getvalue())

    def test_iter_batches_keeps_batches_bounded(self):
        batches = list(google_patent_fetcher.iter_batches(range(5), batch_size=2))

        self.assertEqual([len(batch) for batch in batches], [2, 2, 1])
        self.assertEqual(batches, [[0, 1], [2, 3], [4]])

    def test_iter_batches_rejects_non_positive_batch_size(self):
        for batch_size in (0, -1):
            with self.assertRaises(ValueError):
                list(google_patent_fetcher.iter_batches([1, 2, 3], batch_size=batch_size))

    def test_stream_query_rows_passes_query_parameters(self):
        client = FakeBigQueryClient()

        rows = google_patent_fetcher.stream_query_rows(
            client,
            "SELECT * FROM publications",
            country="CN",
            start_date="2024-01-02",
            end_date="2024-02-03",
            page_size=250,
        )

        params = {param.name: param for param in client.job_config.query_parameters}
        self.assertEqual(rows, ["row"])
        self.assertEqual(client.sql, "SELECT * FROM publications")
        self.assertEqual(client.job.page_size, 250)
        self.assertEqual(params["country"].value, "CN")
        self.assertEqual(params["start_date"].value, 20240102)
        self.assertEqual(params["end_date"].value, 20240203)

    def test_stream_query_rows_omits_blank_date_parameters(self):
        client = FakeBigQueryClient()

        google_patent_fetcher.stream_query_rows(
            client,
            "SELECT * FROM publications",
            country="CN",
            start_date=None,
            end_date="",
            page_size=100,
        )

        params = client.job_config.query_parameters
        self.assertEqual([param.name for param in params], ["country"])
        self.assertEqual(params[0].value, "CN")

    def test_build_publications_query_filters_country_dates_and_limit(self):
        query = google_patent_fetcher.build_publications_query(
            country="CN",
            start_date=20240101,
            end_date=20240430,
            limit=100,
        )

        self.assertIn("`patents-public-data.patents.publications`", query)
        self.assertIn("country_code = @country", query)
        self.assertIn("publication_date >= @start_date", query)
        self.assertIn("publication_date <= @end_date", query)
        self.assertTrue(query.rstrip().endswith("LIMIT 100"))

    def test_yyyymmdd_to_iso_converts_valid_integer_date(self):
        self.assertEqual(google_patent_fetcher.yyyymmdd_to_iso(20240430), "2024-04-30")
        self.assertEqual(google_patent_fetcher.yyyymmdd_to_iso("20240430"), "2024-04-30")

    def test_yyyymmdd_to_iso_returns_blank_for_missing_or_malformed_values(self):
        for value in (None, "", "   ", 0, "20241301", "not-a-date"):
            self.assertEqual(google_patent_fetcher.yyyymmdd_to_iso(value), "")

    def test_localized_text_prefers_zh_then_first_non_empty_text(self):
        localized = [
            {"text": "English", "language": "en"},
            {"text": "中文标题", "language": "zh"},
        ]

        self.assertEqual(google_patent_fetcher.localized_text(localized), "中文标题")
        self.assertEqual(google_patent_fetcher.localized_text([{"text": ""}, {"text": "First"}]), "First")

    def test_names_from_list_handles_strings_and_dict_variants(self):
        self.assertEqual(google_patent_fetcher.names_from_list(["张三", "李四"]), ["张三", "李四"])
        self.assertEqual(
            google_patent_fetcher.names_from_list([{"name": "张三"}, {"text": "李四"}]),
            ["张三", "李四"],
        )

    def test_codes_from_list_handles_dicts_and_strings(self):
        self.assertEqual(
            google_patent_fetcher.codes_from_list([{"code": "G06F16/00"}, "H04L67/10"]),
            ["G06F16/00", "H04L67/10"],
        )

    def test_map_bigquery_row_maps_publication_fields_for_cn_parser(self):
        row = {
            "publication_number": "CN-111915025-B",
            "application_number": "CN-202010777888-A",
            "country_code": "CN",
            "family_id": "12345",
            "title_localized": [
                {"text": "English", "language": "en"},
                {"text": "中文标题", "language": "zh"},
            ],
            "abstract_localized": [{"text": "中文摘要", "language": "zh"}],
            "publication_date": 20240430,
            "filing_date": 20240115,
            "grant_date": 20240501,
            "inventor": ["张三", "李四"],
            "assignee": ["某公司"],
            "ipc": [{"code": "G06F16/00"}],
            "cpc": [{"code": "H04L67/10"}],
        }

        mapped = google_patent_fetcher.map_bigquery_row(row)

        self.assertEqual(mapped["source"], "google_patents")
        self.assertEqual(mapped["publication_number"], "CN111915025B")
        self.assertEqual(mapped["application_number"], "CN202010777888A")
        self.assertEqual(mapped["title"], "中文标题")
        self.assertEqual(mapped["abstract"], "中文摘要")
        self.assertEqual(mapped["publication_date"], "2024-04-30")
        self.assertEqual(mapped["application_date"], "2024-01-15")
        self.assertEqual(mapped["grant_date"], "2024-05-01")
        self.assertEqual(mapped["inventors"], ["张三", "李四"])
        self.assertEqual(mapped["assignees"], ["某公司"])
        self.assertEqual(mapped["ipc_codes"], ["G06F16/00"])
        self.assertEqual(mapped["cpc_codes"], ["H04L67/10"])
        self.assertEqual(mapped["family_id"], "12345")
        self.assertEqual(mapped["country"], "CN")
        self.assertEqual(mapped["source_url"], "https://patents.google.com/patent/CN111915025B")
        self.assertEqual(json.loads(mapped["raw_json"])["publication_number"], "CN-111915025-B")

    def test_mapped_row_is_compatible_with_cn_patent_parser_lists(self):
        mapped = google_patent_fetcher.map_bigquery_row(
            {
                "publication_number": "CN-111915025-B",
                "title_localized": [{"text": "中文标题", "language": "zh"}],
                "inventor": ["张三", "李四"],
                "assignee": ["某公司"],
                "ipc": [{"code": "G06F16/00"}, {"code": "G06F40/00"}],
                "cpc": [{"code": "H04L67/10"}],
            }
        )

        parsed = cn_patent_fetcher.parse_cn_patent_record(mapped)

        self.assertEqual(parsed["source"], "google_patents")
        self.assertEqual(parsed["publication_number"], "CN111915025B")
        self.assertEqual(parsed["patent_title"], "中文标题")
        self.assertEqual(parsed["inventors"], ["张三", "李四"])
        self.assertEqual(parsed["assignees"], ["某公司"])
        self.assertEqual(parsed["ipc_codes"], ["G06F16/00", "G06F40/00"])
        self.assertEqual(parsed["cpc_codes"], ["H04L67/10"])

    def test_map_bigquery_row_preserves_nested_row_shape_in_raw_json(self):
        mapped = google_patent_fetcher.map_bigquery_row(
            FakeRow(
                publication_number="CN-111915025-B",
                country_code="CN",
                title_localized=[
                    FakeRow(text="中文标题", language="zh", truncated=False),
                ],
                ipc=[
                    FakeRow(code="G06F16/00", inventive=True, first=True, tree=["G", "G06"]),
                ],
            )
        )

        raw = json.loads(mapped["raw_json"])

        self.assertEqual(raw["title_localized"][0]["text"], "中文标题")
        self.assertEqual(raw["ipc"][0]["code"], "G06F16/00")
        self.assertEqual(raw["ipc"][0]["tree"], ["G", "G06"])


if __name__ == "__main__":
    unittest.main()
