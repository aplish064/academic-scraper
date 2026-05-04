#!/usr/bin/env python3
"""
Incremental U.S. granted patent fetcher.

Fetches granted patent records from a PatentsView-compatible API and stores one
patent per row in ClickHouse.
"""

import json
import os
import csv
import zipfile
import time
from datetime import date, datetime, timedelta
from io import TextIOWrapper
from typing import Any, Dict, Iterable, List, Optional, Tuple

import clickhouse_connect
import httpx


PATENT_API_URL = "https://search.patentsview.org/api/v1/patent/"
PATENT_API_KEY_ENV = "PATENTSVIEW_API_KEY"
SOURCE_NAME = "patentsview"
BULK_SOURCE_NAME = "patentsview_bulk"
BULK_BASE_URL = "https://s3.amazonaws.com/data.patentsview.org/download"
BULK_DATA_DIR = "/home/hkustgz/Us/academic-scraper/data/patentsview"
G_PATENT_ZIP_URL = f"{BULK_BASE_URL}/g_patent.tsv.zip"
G_PATENT_ZIP_PATH = os.path.join(BULK_DATA_DIR, "g_patent.tsv.zip")

CH_HOST = "localhost"
CH_PORT = 8123
CH_DATABASE = "patent_db"
CH_TABLE = "patents"
CH_USERNAME = "default"
CH_PASSWORD = ""

START_DATE = "2025-10-01"
END_DATE = None
WINDOW_DAYS = 7
PER_PAGE = 1000
BATCH_SIZE = 5000
MAX_RETRIES = 3
REQUEST_TIMEOUT = 60.0
DOWNLOAD_TIMEOUT = 300.0

LOG_DIR = "/home/hkustgz/Us/academic-scraper/log"
LOG_FILE = os.path.join(LOG_DIR, "patent_fetcher.log")
PROGRESS_FILE = os.path.join(LOG_DIR, "patent_fetch_progress.json")

PATENT_FIELDS = [
    "patent_id",
    "patent_number",
    "patent_title",
    "patent_abstract",
    "patent_date",
    "patent_type",
    "patent_kind",
    "app_date",
    "app_number",
    "inventor_id",
    "inventor_first_name",
    "inventor_last_name",
    "assignee_id",
    "assignee_organization",
    "assignee_first_name",
    "assignee_last_name",
    "assignee_type",
    "cpc_subgroup_id",
    "cpc_subsection_id",
    "ipc_class",
    "ipc_subclass",
    "uspc_mainclass_id",
    "cited_patent_number",
    "citedby_patent_number",
    "application.filing_date",
    "application.application_id",
    "inventors.inventor_id",
    "inventors.inventor_name_first",
    "inventors.inventor_name_last",
    "assignees.assignee_id",
    "assignees.assignee_organization",
    "assignees.assignee_individual_name_first",
    "assignees.assignee_individual_name_last",
    "assignees.assignee_type",
    "cpc_current.cpc_group_id",
    "cpc_current.cpc_subclass_id",
    "cpc_at_issue.cpc_group_id",
    "cpc_at_issue.cpc_subclass_id",
    "ipcr.ipc_class",
    "ipcr.ipc_subclass",
    "ipcr.ipc_subgroup",
    "uspc_at_issue.uspc_mainclass_id",
    "patent_num_times_cited_by_us_patents",
    "patent_num_total_documents_cited",
]


CREATE_DATABASE_SQL = f"CREATE DATABASE IF NOT EXISTS {CH_DATABASE}"

CREATE_PATENTS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.patents (
    patent_id String,
    source String,
    patent_number String,
    patent_title String,
    patent_abstract String,
    grant_date Date,
    application_date Nullable(Date),
    publication_date Nullable(Date),
    patent_type String,
    status String,
    country String,
    inventors Array(String),
    inventor_ids Array(String),
    assignees Array(String),
    assignee_ids Array(String),
    assignee_types Array(String),
    cpc_codes Array(String),
    ipc_codes Array(String),
    uspc_codes Array(String),
    num_claims UInt32,
    num_cited_by UInt32,
    num_citations UInt32,
    family_id String,
    application_number String,
    publication_number String,
    source_url String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY (source, patent_id)
"""

CREATE_PATENT_APPLICATIONS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.patent_applications (
    patent_id String,
    application_id String,
    application_date Nullable(Date),
    series_code String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY (patent_id, application_id)
"""

CREATE_PATENT_INVENTORS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.patent_inventors (
    patent_id String,
    inventor_id String,
    inventor_name String,
    inventor_first_name String,
    inventor_last_name String,
    location_id String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY (patent_id, inventor_id, inventor_name)
"""

CREATE_PATENT_ASSIGNEES_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.patent_assignees (
    patent_id String,
    assignee_id String,
    assignee_name String,
    assignee_type String,
    location_id String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY (patent_id, assignee_id, assignee_name)
"""

CREATE_PATENT_CPC_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.patent_cpc (
    patent_id String,
    cpc_sequence String,
    cpc_section String,
    cpc_class String,
    cpc_subclass String,
    cpc_group String,
    cpc_type String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY (patent_id, cpc_sequence, cpc_group)
"""

CREATE_PATENT_ABSTRACTS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.patent_abstracts (
    patent_id String,
    patent_abstract String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY patent_id
"""

CREATE_PATENT_CITATIONS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.patent_citations (
    patent_id String,
    cited_patent_id String,
    citation_sequence String,
    citation_category String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY (patent_id, cited_patent_id, citation_sequence)
"""

CREATE_TABLE_SQL = CREATE_PATENTS_TABLE_SQL


INSERT_COLUMNS = [
    "patent_id",
    "source",
    "patent_number",
    "patent_title",
    "patent_abstract",
    "grant_date",
    "application_date",
    "publication_date",
    "patent_type",
    "status",
    "country",
    "inventors",
    "inventor_ids",
    "assignees",
    "assignee_ids",
    "assignee_types",
    "cpc_codes",
    "ipc_codes",
    "uspc_codes",
    "num_claims",
    "num_cited_by",
    "num_citations",
    "family_id",
    "application_number",
    "publication_number",
    "source_url",
    "raw_json",
    "import_time",
]

APPLICATION_COLUMNS = ["patent_id", "application_id", "application_date", "series_code", "raw_json", "import_time"]
INVENTOR_COLUMNS = [
    "patent_id",
    "inventor_id",
    "inventor_name",
    "inventor_first_name",
    "inventor_last_name",
    "location_id",
    "raw_json",
    "import_time",
]
ASSIGNEE_COLUMNS = [
    "patent_id",
    "assignee_id",
    "assignee_name",
    "assignee_type",
    "location_id",
    "raw_json",
    "import_time",
]
CPC_COLUMNS = [
    "patent_id",
    "cpc_sequence",
    "cpc_section",
    "cpc_class",
    "cpc_subclass",
    "cpc_group",
    "cpc_type",
    "raw_json",
    "import_time",
]
ABSTRACT_COLUMNS = ["patent_id", "patent_abstract", "raw_json", "import_time"]
CITATION_COLUMNS = ["patent_id", "cited_patent_id", "citation_sequence", "citation_category", "raw_json", "import_time"]


BULK_TABLES = {
    "patents": {
        "file": "g_patent.tsv.zip",
        "table": "patents",
        "parser_name": "parse_bulk_patent_row",
        "columns": INSERT_COLUMNS,
    },
    "applications": {
        "file": "g_application.tsv.zip",
        "table": "patent_applications",
        "parser_name": "parse_application_row",
        "columns": APPLICATION_COLUMNS,
    },
    "inventors": {
        "file": "g_inventor_disambiguated.tsv.zip",
        "table": "patent_inventors",
        "parser_name": "parse_inventor_row",
        "columns": INVENTOR_COLUMNS,
    },
    "assignees": {
        "file": "g_assignee_disambiguated.tsv.zip",
        "table": "patent_assignees",
        "parser_name": "parse_assignee_row",
        "columns": ASSIGNEE_COLUMNS,
    },
    "cpc": {
        "file": "g_cpc_current.tsv.zip",
        "table": "patent_cpc",
        "parser_name": "parse_cpc_row",
        "columns": CPC_COLUMNS,
    },
    "abstracts": {
        "file": "g_patent_abstract.tsv.zip",
        "table": "patent_abstracts",
        "parser_name": "parse_abstract_row",
        "columns": ABSTRACT_COLUMNS,
    },
    "citations": {
        "file": "g_us_patent_citation.tsv.zip",
        "table": "patent_citations",
        "parser_name": "parse_citation_row",
        "columns": CITATION_COLUMNS,
    },
}

DEFAULT_BULK_TABLE_KEYS = ["patents"]
ALL_BULK_TABLE_KEYS = list(BULK_TABLES.keys())


def normalize_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {text}")


def normalize_clickhouse_nullable_date(value: Any) -> Optional[date]:
    parsed = normalize_date(value)
    if parsed is None or parsed.year < 1970:
        return None
    return parsed


def unique_clean_strings(values: Iterable[Any]) -> List[str]:
    cleaned = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _nested_list(record: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = record.get(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _person_name(item: Dict[str, Any], first_key: str, last_key: str, org_key: Optional[str] = None) -> str:
    if org_key:
        org = str(item.get(org_key) or "").strip()
        if org:
            return org
    first = str(item.get(first_key) or "").strip()
    last = str(item.get(last_key) or "").strip()
    return " ".join(part for part in [first, last] if part)


def _flat_value_list(record: Dict[str, Any], key: str) -> List[str]:
    value = record.get(key)
    if isinstance(value, list):
        return unique_clean_strings(value)
    return unique_clean_strings([value])


def extract_inventors(record: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    nested = _nested_list(record, "inventors")
    if nested:
        names = [
            _person_name(
                item,
                "inventor_first_name" if "inventor_first_name" in item else "inventor_name_first",
                "inventor_last_name" if "inventor_last_name" in item else "inventor_name_last",
            )
            for item in nested
        ]
        ids = [item.get("inventor_id") for item in nested]
        return unique_clean_strings(names), unique_clean_strings(ids)
    first_names = _flat_value_list(record, "inventor_first_name")
    last_names = _flat_value_list(record, "inventor_last_name")
    names = [" ".join(part for part in pair if part) for pair in zip(first_names, last_names)]
    return unique_clean_strings(names), _flat_value_list(record, "inventor_id")


def extract_assignees(record: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    nested = _nested_list(record, "assignees")
    if nested:
        names = [
            _person_name(
                item,
                "assignee_first_name" if "assignee_first_name" in item else "assignee_individual_name_first",
                "assignee_last_name" if "assignee_last_name" in item else "assignee_individual_name_last",
                "assignee_organization",
            )
            for item in nested
        ]
        ids = [item.get("assignee_id") for item in nested]
        types = [item.get("assignee_type") for item in nested]
        return unique_clean_strings(names), unique_clean_strings(ids), unique_clean_strings(types)
    names = _flat_value_list(record, "assignee_organization")
    if not names:
        first_names = _flat_value_list(record, "assignee_first_name")
        last_names = _flat_value_list(record, "assignee_last_name")
        names = [" ".join(part for part in pair if part) for pair in zip(first_names, last_names)]
    return unique_clean_strings(names), _flat_value_list(record, "assignee_id"), _flat_value_list(record, "assignee_type")


def extract_classification_codes(record: Dict[str, Any], nested_key: str, candidate_keys: List[str]) -> List[str]:
    values = []
    for item in _nested_list(record, nested_key):
        for key in candidate_keys:
            if item.get(key):
                values.append(item[key])
    for key in candidate_keys:
        values.extend(_flat_value_list(record, key))
    return unique_clean_strings(values)


def normalize_patent_id(patent_number: str) -> str:
    text = str(patent_number or "").strip()
    if not text:
        return ""
    if text.upper().startswith("US-"):
        return text.upper()
    return f"US-{text}"


def parse_patent_record(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_number") or record.get("patent_id") or "").strip()
    inventors, inventor_ids = extract_inventors(record)
    assignees, assignee_ids, assignee_types = extract_assignees(record)
    cpc_codes = (
        extract_classification_codes(record, "cpcs", ["cpc_subgroup_id", "cpc_subsection_id", "cpc_group_id"])
        or extract_classification_codes(record, "cpc_current", ["cpc_group_id", "cpc_subclass_id", "cpc_class_id"])
        or extract_classification_codes(record, "cpc_at_issue", ["cpc_group_id", "cpc_subclass_id", "cpc_class_id"])
    )
    ipc_codes = (
        extract_classification_codes(record, "ipcs", ["ipc_class", "ipc_subclass", "ipc_group"])
        or extract_classification_codes(record, "ipcr", ["ipc_class", "ipc_subclass", "ipc_subgroup"])
    )
    uspc_codes = (
        extract_classification_codes(record, "uspcs", ["uspc_mainclass_id", "uspc_subclass_id"])
        or extract_classification_codes(record, "uspc_at_issue", ["uspc_mainclass_id", "uspc_subclass_id"])
    )
    cited_by = _nested_list(record, "citedby_patents") or [
        {"value": value} for value in _flat_value_list(record, "citedby_patent_number")
    ]
    cited = _nested_list(record, "cited_patents") or [
        {"value": value} for value in _flat_value_list(record, "cited_patent_number")
    ]
    applications = _nested_list(record, "application")
    application = applications[0] if applications else record.get("application", {})
    if not isinstance(application, dict):
        application = {}

    return {
        "patent_id": normalize_patent_id(patent_number),
        "source": SOURCE_NAME,
        "patent_number": patent_number,
        "patent_title": str(record.get("patent_title") or "").strip(),
        "patent_abstract": str(record.get("patent_abstract") or "").strip(),
        "grant_date": normalize_date(record.get("patent_date")) or date(1970, 1, 1),
        "application_date": normalize_date(record.get("app_date") or application.get("filing_date")),
        "publication_date": normalize_date(record.get("publication_date")),
        "patent_type": str(record.get("patent_type") or "").strip(),
        "status": "granted",
        "country": "US",
        "inventors": inventors,
        "inventor_ids": inventor_ids,
        "assignees": assignees,
        "assignee_ids": assignee_ids,
        "assignee_types": assignee_types,
        "cpc_codes": cpc_codes,
        "ipc_codes": ipc_codes,
        "uspc_codes": uspc_codes,
        "num_claims": int(record.get("num_claims") or record.get("claim_count") or 0),
        "num_cited_by": int(record.get("patent_num_times_cited_by_us_patents") or len(cited_by)),
        "num_citations": int(record.get("patent_num_total_documents_cited") or len(cited)),
        "family_id": str(record.get("family_id") or "").strip(),
        "application_number": str(record.get("app_number") or application.get("application_id") or "").strip(),
        "publication_number": str(record.get("publication_number") or "").strip(),
        "source_url": f"https://patents.google.com/patent/US{patent_number}" if patent_number else "",
        "raw_json": json.dumps(record, ensure_ascii=False, sort_keys=True),
        "import_time": datetime.now(),
    }


def safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_bulk_patent_row(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_id") or record.get("patent_number") or "").strip()
    return {
        "patent_id": normalize_patent_id(patent_number),
        "source": BULK_SOURCE_NAME,
        "patent_number": patent_number,
        "patent_title": str(record.get("patent_title") or "").strip(),
        "patent_abstract": str(record.get("patent_abstract") or "").strip(),
        "grant_date": normalize_date(record.get("patent_date")) or date(1970, 1, 1),
        "application_date": normalize_date(record.get("app_date")),
        "publication_date": normalize_date(record.get("publication_date")),
        "patent_type": str(record.get("patent_type") or "").strip(),
        "status": "granted",
        "country": "US",
        "inventors": [],
        "inventor_ids": [],
        "assignees": [],
        "assignee_ids": [],
        "assignee_types": [],
        "cpc_codes": [],
        "ipc_codes": [],
        "uspc_codes": [],
        "num_claims": safe_int(record.get("num_claims")),
        "num_cited_by": 0,
        "num_citations": 0,
        "family_id": "",
        "application_number": str(record.get("application_id") or "").strip(),
        "publication_number": "",
        "source_url": f"https://patents.google.com/patent/US{patent_number}" if patent_number else "",
        "raw_json": json.dumps(record, ensure_ascii=False, sort_keys=True),
        "import_time": datetime.now(),
    }


def _raw_json(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def parse_application_row(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_id") or "").strip()
    return {
        "patent_id": normalize_patent_id(patent_number),
        "application_id": str(record.get("application_id") or record.get("app_id") or "").strip(),
        "application_date": normalize_clickhouse_nullable_date(
            record.get("filing_date") or record.get("application_date") or record.get("app_date")
        ),
        "series_code": str(record.get("series_code") or "").strip(),
        "raw_json": _raw_json(record),
        "import_time": datetime.now(),
    }


def parse_inventor_row(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_id") or "").strip()
    first_name = str(
        record.get("inventor_first_name")
        or record.get("inventor_name_first")
        or record.get("disambig_inventor_name_first")
        or ""
    ).strip()
    last_name = str(
        record.get("inventor_last_name")
        or record.get("inventor_name_last")
        or record.get("disambig_inventor_name_last")
        or ""
    ).strip()
    name = str(record.get("inventor_name") or " ".join(part for part in [first_name, last_name] if part)).strip()
    return {
        "patent_id": normalize_patent_id(patent_number),
        "inventor_id": str(record.get("inventor_id") or "").strip(),
        "inventor_name": name,
        "inventor_first_name": first_name,
        "inventor_last_name": last_name,
        "location_id": str(record.get("location_id") or "").strip(),
        "raw_json": _raw_json(record),
        "import_time": datetime.now(),
    }


def parse_assignee_row(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_id") or "").strip()
    first_name = str(
        record.get("assignee_first_name")
        or record.get("assignee_individual_name_first")
        or record.get("disambig_assignee_individual_name_first")
        or ""
    ).strip()
    last_name = str(
        record.get("assignee_last_name")
        or record.get("assignee_individual_name_last")
        or record.get("disambig_assignee_individual_name_last")
        or ""
    ).strip()
    organization = str(record.get("assignee_organization") or record.get("disambig_assignee_organization") or "").strip()
    name = str(record.get("assignee_name") or organization or " ".join(part for part in [first_name, last_name] if part)).strip()
    return {
        "patent_id": normalize_patent_id(patent_number),
        "assignee_id": str(record.get("assignee_id") or "").strip(),
        "assignee_name": name,
        "assignee_type": str(record.get("assignee_type") or "").strip(),
        "location_id": str(record.get("location_id") or "").strip(),
        "raw_json": _raw_json(record),
        "import_time": datetime.now(),
    }


def parse_cpc_row(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_id") or "").strip()
    cpc_group = str(record.get("cpc_group") or record.get("cpc_group_id") or "").strip()
    cpc_subclass = str(record.get("cpc_subclass") or record.get("cpc_subclass_id") or "").strip()
    cpc_class = str(record.get("cpc_class") or record.get("cpc_class_id") or "").strip()
    cpc_section = str(record.get("cpc_section") or record.get("cpc_section_id") or (cpc_group[:1] if cpc_group else "")).strip()
    return {
        "patent_id": normalize_patent_id(patent_number),
        "cpc_sequence": str(record.get("cpc_sequence") or record.get("sequence") or "").strip(),
        "cpc_section": cpc_section,
        "cpc_class": cpc_class,
        "cpc_subclass": cpc_subclass,
        "cpc_group": cpc_group,
        "cpc_type": str(record.get("cpc_type") or "").strip(),
        "raw_json": _raw_json(record),
        "import_time": datetime.now(),
    }


def parse_abstract_row(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_id") or "").strip()
    return {
        "patent_id": normalize_patent_id(patent_number),
        "patent_abstract": str(record.get("patent_abstract") or record.get("abstract") or "").strip(),
        "raw_json": _raw_json(record),
        "import_time": datetime.now(),
    }


def parse_citation_row(record: Dict[str, Any]) -> Dict[str, Any]:
    patent_number = str(record.get("patent_id") or "").strip()
    cited_number = str(record.get("citation_id") or record.get("cited_patent_id") or record.get("cited_patent_number") or "").strip()
    return {
        "patent_id": normalize_patent_id(patent_number),
        "cited_patent_id": normalize_patent_id(cited_number),
        "citation_sequence": str(record.get("citation_sequence") or record.get("sequence") or "").strip(),
        "citation_category": str(record.get("citation_category") or record.get("category") or "").strip(),
        "raw_json": _raw_json(record),
        "import_time": datetime.now(),
    }


def iter_tsv_zip_rows(zip_path: str, member_name: str = None, limit: int = None):
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        selected_name = member_name or next((name for name in names if name.endswith(".tsv")), None)
        if not selected_name:
            raise ValueError(f"No TSV member found in {zip_path}")
        with archive.open(selected_name) as raw:
            text_file = TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.DictReader(text_file, delimiter="\t")
            for index, row in enumerate(reader, start=1):
                if limit is not None and index > limit:
                    break
                yield row


def default_progress() -> Dict[str, Any]:
    return {
        "current_window_start": None,
        "current_window_end": None,
        "current_page": 1,
        "completed_windows": [],
        "last_update": None,
    }


def load_progress(progress_file: str = PROGRESS_FILE) -> Dict[str, Any]:
    if not os.path.exists(progress_file):
        return default_progress()
    with open(progress_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    progress = default_progress()
    progress.update(loaded)
    return progress


def save_progress(progress: Dict[str, Any], progress_file: str = PROGRESS_FILE) -> None:
    os.makedirs(os.path.dirname(progress_file), exist_ok=True)
    progress["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def build_patents_query_payload(start_date: str, end_date: str, page: int, per_page: int = PER_PAGE) -> Dict[str, Any]:
    return {
        "q": {
            "_and": [
                {"_gte": {"patent_date": start_date}},
                {"_lte": {"patent_date": end_date}},
            ]
        },
        "f": PATENT_FIELDS,
        "o": {
            "page": page,
            "per_page": per_page,
            "include_subentity_total_counts": False,
        },
        "s": [{"patent_date": "asc"}, {"patent_number": "asc"}],
    }


def log_message(message: str, level: str = "INFO") -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def iter_date_windows(start_date: str, end_date: str, window_days: int = WINDOW_DAYS):
    current = normalize_date(start_date)
    final = normalize_date(end_date)
    if current is None or final is None:
        raise ValueError("start_date and end_date must be YYYY-MM-DD strings")
    while current <= final:
        window_end = min(current + timedelta(days=window_days - 1), final)
        yield current.isoformat(), window_end.isoformat()
        current = window_end + timedelta(days=1)


def extract_patent_records(response_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = response_json.get("patents")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    return []


def extract_total_pages(response_json: Dict[str, Any], per_page: int = PER_PAGE) -> int:
    count = int(response_json.get("total_hits") or response_json.get("count") or 0)
    if count <= 0:
        return 1
    return (count + per_page - 1) // per_page


def post_with_retries(client: httpx.Client, payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.environ.get(PATENT_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{PATENT_API_KEY_ENV} is required for the current PatentSearch API")
    headers = {"X-Api-Key": api_key}
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.post(PATENT_API_URL, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code in (429, 500, 502, 503, 504):
                wait_seconds = min(60, 2 ** attempt)
                log_message(f"HTTP {response.status_code}; retrying in {wait_seconds}s", "WARNING")
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            wait_seconds = min(60, 2 ** attempt)
            log_message(f"Request attempt {attempt} failed: {exc}; retrying in {wait_seconds}s", "WARNING")
            time.sleep(wait_seconds)
    raise RuntimeError(f"PatentsView request failed after {MAX_RETRIES} attempts: {last_error}")


def fetch_patents_page(client: httpx.Client, window_start: str, window_end: str, page: int) -> Tuple[List[Dict[str, Any]], int]:
    payload = build_patents_query_payload(window_start, window_end, page=page, per_page=PER_PAGE)
    response_json = post_with_retries(client, payload)
    records = extract_patent_records(response_json)
    total_pages = extract_total_pages(response_json, per_page=PER_PAGE)
    return records, total_pages


def create_clickhouse_client():
    return clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        username=CH_USERNAME,
        password=CH_PASSWORD,
        database="default",
    )


def ensure_patents_table(client) -> None:
    client.command(CREATE_DATABASE_SQL)
    client.command(CREATE_PATENTS_TABLE_SQL)


def ensure_patent_database(client) -> None:
    client.command(CREATE_DATABASE_SQL)
    for sql in [
        CREATE_PATENTS_TABLE_SQL,
        CREATE_PATENT_APPLICATIONS_TABLE_SQL,
        CREATE_PATENT_INVENTORS_TABLE_SQL,
        CREATE_PATENT_ASSIGNEES_TABLE_SQL,
        CREATE_PATENT_CPC_TABLE_SQL,
        CREATE_PATENT_ABSTRACTS_TABLE_SQL,
        CREATE_PATENT_CITATIONS_TABLE_SQL,
    ]:
        client.command(sql)


def row_to_insert_values(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row.get(column) for column in INSERT_COLUMNS)


def batch_insert_clickhouse(client, rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return True
    values = [row_to_insert_values(row) for row in rows]
    try:
        client.insert(f"{CH_DATABASE}.{CH_TABLE}", values, column_names=INSERT_COLUMNS)
        log_message(f"Inserted {len(rows)} patent rows into {CH_DATABASE}.{CH_TABLE}")
        return True
    except Exception as exc:
        log_message(f"ClickHouse insert failed: {exc}", "ERROR")
        return False


def row_values(row: Dict[str, Any], columns: List[str]) -> Tuple[Any, ...]:
    return tuple(row.get(column) for column in columns)


def batch_insert_table(client, table: str, rows: List[Dict[str, Any]], columns: List[str]) -> bool:
    if not rows:
        return True
    values = [row_values(row, columns) for row in rows]
    try:
        client.insert(f"{CH_DATABASE}.{table}", values, column_names=columns)
        log_message(f"Inserted {len(rows)} rows into {CH_DATABASE}.{table}")
        return True
    except Exception as exc:
        log_message(f"ClickHouse insert into {table} failed: {exc}", "ERROR")
        return False


def get_remote_file_size(url: str) -> Optional[int]:
    with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
        response = client.head(url)
        response.raise_for_status()
        length = response.headers.get("content-length")
        return int(length) if length else None


def download_bulk_file(url: str = G_PATENT_ZIP_URL, destination: str = G_PATENT_ZIP_PATH) -> str:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    remote_size = get_remote_file_size(url)
    if os.path.exists(destination) and remote_size and os.path.getsize(destination) == remote_size:
        log_message(f"Bulk file already downloaded: {destination}")
        return destination

    temp_destination = f"{destination}.part"
    downloaded = os.path.getsize(temp_destination) if os.path.exists(temp_destination) else 0
    headers = {"Range": f"bytes={downloaded}-"} if downloaded else {}
    mode = "ab" if downloaded else "wb"

    log_message(f"Downloading {url} to {destination}")
    with httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as client:
        with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            with open(temp_destination, mode) as f:
                for chunk in response.iter_bytes():
                    if chunk:
                        f.write(chunk)

    if remote_size and os.path.getsize(temp_destination) != remote_size:
        raise RuntimeError(
            f"Incomplete download for {destination}: got {os.path.getsize(temp_destination)}, expected {remote_size}"
        )
    os.replace(temp_destination, destination)
    log_message(f"Downloaded bulk file: {destination}")
    return destination


def bulk_file_path(file_name: str) -> str:
    return os.path.join(BULK_DATA_DIR, file_name)


def download_bulk_table(table_key: str) -> str:
    config = BULK_TABLES[table_key]
    file_name = config["file"]
    return download_bulk_file(f"{BULK_BASE_URL}/{file_name}", bulk_file_path(file_name))


def import_g_patent_zip(ch_client, zip_path: str = G_PATENT_ZIP_PATH, limit: int = None) -> int:
    ensure_patent_database(ch_client)
    batch = []
    inserted = 0
    started_at = time.time()

    for raw_row in iter_tsv_zip_rows(zip_path, limit=limit):
        try:
            row = parse_bulk_patent_row(raw_row)
        except Exception as exc:
            log_message(f"Skipping malformed bulk patent row: {exc}", "WARNING")
            continue
        if not row["patent_id"]:
            continue
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            if not batch_insert_clickhouse(ch_client, batch):
                raise RuntimeError("ClickHouse insert failed during g_patent import")
            inserted += len(batch)
            batch = []

    if batch:
        if not batch_insert_clickhouse(ch_client, batch):
            raise RuntimeError("ClickHouse insert failed during final g_patent import")
        inserted += len(batch)

    elapsed = time.time() - started_at
    log_message(f"Imported {inserted} g_patent rows from {zip_path} in {elapsed:.1f}s")
    return inserted


def import_bulk_table(ch_client, table_key: str, zip_path: str = None, limit: int = None) -> int:
    ensure_patent_database(ch_client)
    config = BULK_TABLES[table_key]
    file_name = config["file"]
    destination = zip_path or bulk_file_path(file_name)
    parser = globals()[config["parser_name"]]
    table = config["table"]
    columns = config["columns"]
    batch = []
    inserted = 0
    started_at = time.time()

    for raw_row in iter_tsv_zip_rows(destination, limit=limit):
        try:
            row = parser(raw_row)
        except Exception as exc:
            log_message(f"Skipping malformed {table_key} row: {exc}", "WARNING")
            continue
        if not row.get("patent_id"):
            continue
        batch.append(row)
        if len(batch) >= BATCH_SIZE:
            if not batch_insert_table(ch_client, table, batch, columns):
                raise RuntimeError(f"ClickHouse insert failed during {table_key} import")
            inserted += len(batch)
            batch = []

    if batch:
        if not batch_insert_table(ch_client, table, batch, columns):
            raise RuntimeError(f"ClickHouse insert failed during final {table_key} import")
        inserted += len(batch)

    elapsed = time.time() - started_at
    log_message(f"Imported {inserted} {table_key} rows from {destination} in {elapsed:.1f}s")
    return inserted


def parse_import_limit(value: str = None) -> Optional[int]:
    text = value if value is not None else os.environ.get("PATENT_IMPORT_LIMIT")
    if text in (None, ""):
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def parse_bulk_table_keys(value: str = None) -> List[str]:
    text = value if value is not None else os.environ.get("PATENT_BULK_TABLES")
    if text in (None, ""):
        return DEFAULT_BULK_TABLE_KEYS
    keys = unique_clean_strings(text.split(","))
    if len(keys) == 1 and keys[0].lower() == "all":
        return ALL_BULK_TABLE_KEYS
    unknown = [key for key in keys if key not in BULK_TABLES]
    if unknown:
        raise ValueError(
            f"Unknown bulk table key(s): {', '.join(unknown)}. "
            f"Available: all, {', '.join(ALL_BULK_TABLE_KEYS)}"
        )
    return keys


def today_iso() -> str:
    return date.today().isoformat()


def mark_current_window(progress: Dict[str, Any], window_start: str, window_end: str, page: int) -> None:
    progress["current_window_start"] = window_start
    progress["current_window_end"] = window_end
    progress["current_page"] = page


def mark_window_complete(progress: Dict[str, Any], window_start: str, window_end: str) -> None:
    completed = progress.setdefault("completed_windows", [])
    marker = [window_start, window_end]
    if marker not in completed:
        completed.append(marker)
    progress["current_window_start"] = None
    progress["current_window_end"] = None
    progress["current_page"] = 1


def is_window_completed(progress: Dict[str, Any], window_start: str, window_end: str) -> bool:
    return [window_start, window_end] in progress.get("completed_windows", [])


def process_window(
    http_client: httpx.Client,
    ch_client,
    progress: Dict[str, Any],
    window_start: str,
    window_end: str,
) -> bool:
    page = int(progress.get("current_page") or 1)
    total_pages = page
    total_records = 0
    inserted_records = 0
    batch = []
    started_at = time.time()

    while page <= total_pages:
        mark_current_window(progress, window_start, window_end, page)
        save_progress(progress)
        records, total_pages = fetch_patents_page(http_client, window_start, window_end, page)
        total_records += len(records)

        for record in records:
            try:
                row = parse_patent_record(record)
            except Exception as exc:
                log_message(f"Skipping malformed patent record on page {page}: {exc}", "WARNING")
                continue
            if not row["patent_id"]:
                log_message(f"Skipping patent record without patent number on page {page}", "WARNING")
                continue
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                if not batch_insert_clickhouse(ch_client, batch):
                    return False
                inserted_records += len(batch)
                batch = []

        page += 1

    if batch:
        if not batch_insert_clickhouse(ch_client, batch):
            return False
        inserted_records += len(batch)

    mark_window_complete(progress, window_start, window_end)
    save_progress(progress)
    elapsed = time.time() - started_at
    log_message(
        f"{window_start}..{window_end} | patents: {total_records} | inserted: {inserted_records} | "
        f"pages: {total_pages} | elapsed: {elapsed:.1f}s"
    )
    return True


def run() -> int:
    ch_client = create_clickhouse_client()
    ensure_patent_database(ch_client)
    limit = parse_import_limit()
    if limit:
        log_message(f"Running limited bulk import: first {limit} rows")
    tables = parse_bulk_table_keys()
    for table_key in tables:
        zip_path = download_bulk_table(table_key)
        import_bulk_table(ch_client, table_key, zip_path=zip_path, limit=limit)
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
