import os
import tempfile
import unittest
import zipfile
from datetime import date

from src import patent_fetcher


class PatentFetcherParserTests(unittest.TestCase):
    def test_normalize_date_accepts_iso_date(self):
        self.assertEqual(patent_fetcher.normalize_date("2025-10-07"), date(2025, 10, 7))

    def test_normalize_date_accepts_patentsview_bulk_date(self):
        self.assertEqual(patent_fetcher.normalize_date("1/6/1976"), date(1976, 1, 6))

    def test_normalize_date_returns_none_for_empty_values(self):
        self.assertIsNone(patent_fetcher.normalize_date(""))
        self.assertIsNone(patent_fetcher.normalize_date(None))

    def test_unique_clean_strings_removes_empty_and_duplicates(self):
        values = ["Acme Corp", "", None, "Acme Corp", "Beta LLC"]
        self.assertEqual(patent_fetcher.unique_clean_strings(values), ["Acme Corp", "Beta LLC"])

    def test_parse_patent_record_normalizes_flat_and_nested_fields(self):
        record = {
            "patent_number": "12345678",
            "patent_title": "System for academic patent analysis",
            "patent_abstract": "A test abstract.",
            "patent_date": "2025-10-07",
            "app_date": "2024-01-15",
            "patent_type": "utility",
            "inventors": [
                {"inventor_id": "inv-1", "inventor_first_name": "Ada", "inventor_last_name": "Lovelace"},
                {"inventor_id": "inv-2", "inventor_first_name": "Grace", "inventor_last_name": "Hopper"},
            ],
            "assignees": [
                {"assignee_id": "asg-1", "assignee_organization": "Example University", "assignee_type": "2"}
            ],
            "cpcs": [
                {"cpc_subgroup_id": "G06F17/00"},
                {"cpc_subsection_id": "G06F"},
            ],
            "uspcs": [{"uspc_mainclass_id": "705"}],
            "citedby_patents": [{"citedby_patent_number": "9999999"}],
            "cited_patents": [{"cited_patent_number": "8888888"}, {"cited_patent_number": "7777777"}],
        }

        row = patent_fetcher.parse_patent_record(record)

        self.assertEqual(row["source"], "patentsview")
        self.assertEqual(row["patent_id"], "US-12345678")
        self.assertEqual(row["patent_number"], "12345678")
        self.assertEqual(row["patent_title"], "System for academic patent analysis")
        self.assertEqual(row["grant_date"], date(2025, 10, 7))
        self.assertEqual(row["application_date"], date(2024, 1, 15))
        self.assertEqual(row["inventors"], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(row["inventor_ids"], ["inv-1", "inv-2"])
        self.assertEqual(row["assignees"], ["Example University"])
        self.assertEqual(row["assignee_ids"], ["asg-1"])
        self.assertEqual(row["assignee_types"], ["2"])
        self.assertEqual(row["cpc_codes"], ["G06F17/00", "G06F"])
        self.assertEqual(row["uspc_codes"], ["705"])
        self.assertEqual(row["num_cited_by"], 1)
        self.assertEqual(row["num_citations"], 2)
        self.assertIn('"patent_number": "12345678"', row["raw_json"])

    def test_row_to_insert_values_matches_insert_columns(self):
        row = patent_fetcher.parse_patent_record({"patent_number": "123", "patent_date": "2025-10-07"})

        values = patent_fetcher.row_to_insert_values(row)

        self.assertEqual(len(values), len(patent_fetcher.INSERT_COLUMNS))
        self.assertEqual(values[patent_fetcher.INSERT_COLUMNS.index("patent_id")], "US-123")


class PatentFetcherProgressTests(unittest.TestCase):
    def test_load_progress_returns_default_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_path = os.path.join(tmpdir, "missing.json")
            progress = patent_fetcher.load_progress(progress_path)

        self.assertEqual(progress["current_window_start"], None)
        self.assertEqual(progress["current_window_end"], None)
        self.assertEqual(progress["current_page"], 1)
        self.assertEqual(progress["completed_windows"], [])

    def test_save_and_load_progress_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_path = os.path.join(tmpdir, "progress.json")
            progress = {
                "current_window_start": "2025-10-01",
                "current_window_end": "2025-10-07",
                "current_page": 3,
                "completed_windows": [["2025-09-24", "2025-09-30"]],
                "last_update": "2026-05-04 15:30:00",
            }

            patent_fetcher.save_progress(progress, progress_path)
            loaded = patent_fetcher.load_progress(progress_path)

        self.assertEqual(loaded["current_window_start"], "2025-10-01")
        self.assertEqual(loaded["current_page"], 3)
        self.assertEqual(loaded["completed_windows"], [["2025-09-24", "2025-09-30"]])


class PatentFetcherQueryTests(unittest.TestCase):
    def test_build_patents_query_payload_uses_grant_date_window_and_page(self):
        payload = patent_fetcher.build_patents_query_payload("2025-10-01", "2025-10-07", page=2, per_page=100)

        self.assertEqual(payload["o"]["page"], 2)
        self.assertEqual(payload["o"]["per_page"], 100)
        self.assertIn({"_gte": {"patent_date": "2025-10-01"}}, payload["q"]["_and"])
        self.assertIn({"_lte": {"patent_date": "2025-10-07"}}, payload["q"]["_and"])
        self.assertIn("patent_number", payload["f"])
        self.assertIn("patent_title", payload["f"])
        self.assertIn("assignee_organization", payload["f"])

    def test_parse_bulk_table_keys_defaults_to_patents_table(self):
        self.assertEqual(patent_fetcher.parse_bulk_table_keys(""), ["patents"])

    def test_parse_bulk_table_keys_expands_all_tables(self):
        self.assertEqual(patent_fetcher.parse_bulk_table_keys("all"), patent_fetcher.ALL_BULK_TABLE_KEYS)


class PatentFetcherWindowTests(unittest.TestCase):
    def test_iter_date_windows_splits_range_inclusive(self):
        windows = list(patent_fetcher.iter_date_windows("2025-10-01", "2025-10-10", window_days=7))

        self.assertEqual(windows, [("2025-10-01", "2025-10-07"), ("2025-10-08", "2025-10-10")])

    def test_extract_patent_records_accepts_patents_key(self):
        response = {"patents": [{"patent_number": "1"}, {"patent_number": "2"}]}

        self.assertEqual(patent_fetcher.extract_patent_records(response), [{"patent_number": "1"}, {"patent_number": "2"}])

    def test_extract_total_pages_uses_count_and_per_page(self):
        response = {"count": 2501}

        self.assertEqual(patent_fetcher.extract_total_pages(response, per_page=1000), 3)


class PatentFetcherBulkTests(unittest.TestCase):
    def test_iter_tsv_zip_rows_reads_patentsview_bulk_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "g_patent.tsv.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "g_patent.tsv",
                    "patent_id\tpatent_type\tpatent_date\tpatent_title\tnum_claims\twithdrawn\tfilename\n"
                    "3930271\tutility\t1/6/1976\tGolf glove\t4\t0\tpftaps19760106_wk01.zip\n",
                )

            rows = list(patent_fetcher.iter_tsv_zip_rows(zip_path))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["patent_id"], "3930271")
        self.assertEqual(rows[0]["patent_title"], "Golf glove")

    def test_parse_bulk_patent_row_maps_g_patent_fields(self):
        row = patent_fetcher.parse_bulk_patent_row({
            "patent_id": "3930271",
            "patent_type": "utility",
            "patent_date": "1/6/1976",
            "patent_title": "Golf glove",
            "num_claims": "4",
            "withdrawn": "0",
            "filename": "pftaps19760106_wk01.zip",
        })

        self.assertEqual(row["patent_id"], "US-3930271")
        self.assertEqual(row["patent_number"], "3930271")
        self.assertEqual(row["patent_title"], "Golf glove")
        self.assertEqual(row["grant_date"], date(1976, 1, 6))
        self.assertEqual(row["patent_type"], "utility")
        self.assertEqual(row["num_claims"], 4)
        self.assertEqual(row["source"], "patentsview_bulk")
        self.assertEqual(row["raw_json"], '{"filename": "pftaps19760106_wk01.zip", "num_claims": "4", "patent_date": "1/6/1976", "patent_id": "3930271", "patent_title": "Golf glove", "patent_type": "utility", "withdrawn": "0"}')

    def test_parse_application_row_nulls_dates_outside_clickhouse_date_range(self):
        row = patent_fetcher.parse_application_row({
            "patent_id": "3930271",
            "application_id": "06160932",
            "filing_date": "1074-08-14",
            "series_code": "06",
        })

        self.assertEqual(row["patent_id"], "US-3930271")
        self.assertEqual(row["application_id"], "06160932")
        self.assertIsNone(row["application_date"])
        self.assertEqual(row["series_code"], "06")

    def test_parse_application_row_nulls_dates_above_clickhouse_date_range(self):
        row = patent_fetcher.parse_application_row({
            "patent_id": "3943504",
            "application_id": "05552832",
            "filing_date": "2975-02-25",
            "series_code": "05",
        })

        self.assertEqual(row["patent_id"], "US-3943504")
        self.assertIsNone(row["application_date"])

    def test_parse_inventor_row_maps_disambiguated_bulk_fields(self):
        row = patent_fetcher.parse_inventor_row({
            "patent_id": "D1006496",
            "inventor_id": "fl:ji_ln:jiang-1219",
            "disambig_inventor_name_first": "Wenjing",
            "disambig_inventor_name_last": "Jiang",
            "gender_code": "F",
            "location_id": "abcd1234",
        })

        self.assertEqual(row["patent_id"], "US-D1006496")
        self.assertEqual(row["inventor_id"], "fl:ji_ln:jiang-1219")
        self.assertEqual(row["inventor_name"], "Wenjing Jiang")
        self.assertEqual(row["inventor_first_name"], "Wenjing")
        self.assertEqual(row["inventor_last_name"], "Jiang")
        self.assertEqual(row["location_id"], "abcd1234")

    def test_parse_assignee_row_prefers_disambiguated_organization(self):
        row = patent_fetcher.parse_assignee_row({
            "patent_id": "3930271",
            "assignee_id": "org-metal-works",
            "disambig_assignee_individual_name_first": "",
            "disambig_assignee_individual_name_last": "",
            "disambig_assignee_organization": "Metal Works Ramat David",
            "assignee_type": "2",
            "location_id": "loc-1",
        })

        self.assertEqual(row["patent_id"], "US-3930271")
        self.assertEqual(row["assignee_id"], "org-metal-works")
        self.assertEqual(row["assignee_name"], "Metal Works Ramat David")
        self.assertEqual(row["assignee_type"], "2")
        self.assertEqual(row["location_id"], "loc-1")

    def test_parse_cpc_row_maps_current_cpc_fields(self):
        row = patent_fetcher.parse_cpc_row({
            "patent_id": "3930271",
            "cpc_sequence": "0",
            "cpc_section": "A",
            "cpc_class": "63",
            "cpc_subclass": "C",
            "cpc_group": "A63C9/001",
            "cpc_type": "inventive",
        })

        self.assertEqual(row["patent_id"], "US-3930271")
        self.assertEqual(row["cpc_sequence"], "0")
        self.assertEqual(row["cpc_section"], "A")
        self.assertEqual(row["cpc_class"], "63")
        self.assertEqual(row["cpc_subclass"], "C")
        self.assertEqual(row["cpc_group"], "A63C9/001")
        self.assertEqual(row["cpc_type"], "inventive")


if __name__ == "__main__":
    unittest.main()
