#!/usr/bin/env python3
"""CNIPA patent importer for patent_db.

The importer parses local files (CSV/JSONL/JSON/XML and zip archives), normalizes
records into the shared patent schema, and stores rows into ClickHouse tables.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from io import BytesIO, StringIO
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

import clickhouse_connect


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

CH_HOST = "localhost"
CH_PORT = 8123
CH_DATABASE = "patent_db"
CH_TABLE = "patents"
CH_APPLICATIONS_TABLE = "patent_applications"
CH_INVENTORS_TABLE = "patent_inventors"
CH_ASSIGNEES_TABLE = "patent_assignees"
CH_ABSTRACTS_TABLE = "patent_abstracts"
CH_IPC_TABLE = "patent_ipc"
CH_USERNAME = "default"
CH_PASSWORD = ""

CH_TABLE_COLUMNS = [
    CH_TABLE,
    CH_APPLICATIONS_TABLE,
    CH_INVENTORS_TABLE,
    CH_ASSIGNEES_TABLE,
    CH_ABSTRACTS_TABLE,
    CH_IPC_TABLE,
]

SOURCE_NAME = "cnipa"
DEFAULT_COUNTRY = "CN"

LOG_DIR = os.path.join(PROJECT_ROOT, "log")
LOG_FILE = os.path.join(LOG_DIR, "cn_patent_fetcher.log")
PROGRESS_FILE = os.path.join(LOG_DIR, "cn_patent_fetch_progress.json")

PATENT_COLUMNS = [
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

APPLICATION_COLUMNS = [
    "patent_id",
    "application_id",
    "application_date",
    "series_code",
    "raw_json",
    "import_time",
]

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

ABSTRACT_COLUMNS = [
    "patent_id",
    "patent_abstract",
    "raw_json",
    "import_time",
]

IPC_COLUMNS = [
    "source",
    "patent_id",
    "ipc_code",
    "ipc_section",
    "ipc_class",
    "ipc_subclass",
    "ipc_group",
    "is_primary",
    "raw_value",
    "import_time",
]

ROW_SPLIT_PATTERN = re.compile(r"[;；,，|]")

FIELD_ALIASES = {
    "application_number": ["申请号", "申请编号", "申请号码", "application_number", "applicationNo"],
    "publication_number": [
        "公开号",
        "公布号",
        "公开公告号",
        "申请公布号",
        "publication_number",
        "publicationNo",
        "publication_id",
    ],
    "patent_number": ["专利号", "授权公告号", "授权号", "patent_number", "patentNo"],
    "patent_title": ["专利名称", "名称", "发明名称", "title", "patent_title"],
    "patent_abstract": ["摘要", "摘要文本", "abstract", "patent_abstract"],
    "application_date": ["申请日", "申请日期", "application_date", "filed", "app_date"],
    "publication_date": ["公开日", "公布日", "publication_date", "public_date", "announcement_date"],
    "grant_date": ["授权公告日", "授权日", "授权日期", "grant_date", "grantDate"],
    "patent_type": ["专利类型", "类型", "专利种类", "patent_type", "type"],
    "status": ["法律状态", "当前法律状态", "状态", "status"],
    "inventors": ["发明人", "设计人", "inventors", "inventor", "inventor_name"],
    "inventor_ids": ["发明人ID", "inventor_id", "inventorId", "inventors_id"],
    "assignees": ["申请人", "专利权人", "当前权利人", "assignees", "assignee", "权利人", "申请人名称"],
    "assignee_ids": ["申请人ID", "assignee_id", "assigneeId", "assignees_id"],
    "assignee_types": ["权利人类型", "assignee_type", "assigneeType"],
    "ipc_codes": ["IPC", "IPC分类号", "国际分类号", "国际分类", "ipc", "ipc_codes", "ipc_code"],
    "cpc_codes": ["CPC", "CPC分类号", "cpc", "cpc_codes", "cpc_code"],
    "uspc_codes": ["USPC", "USPC分类号", "uspc", "uspc_codes", "uspc_code"],
}

DEFAULT_GRANT_DATE = date(1970, 1, 1)
DEFAULT_BATCH_SIZE = 5000

CREATE_DATABASE_SQL = f"CREATE DATABASE IF NOT EXISTS {CH_DATABASE}"

CREATE_PATENTS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_TABLE} (
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
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_APPLICATIONS_TABLE} (
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
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_INVENTORS_TABLE} (
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
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_ASSIGNEES_TABLE} (
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

CREATE_PATENT_ABSTRACTS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_ABSTRACTS_TABLE} (
    patent_id String,
    patent_abstract String,
    raw_json String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY patent_id
"""

CREATE_PATENT_IPC_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_IPC_TABLE} (
    source String,
    patent_id String,
    ipc_code String,
    ipc_section String,
    ipc_class String,
    ipc_subclass String,
    ipc_group String,
    is_primary UInt8,
    raw_value String,
    import_time DateTime
)
ENGINE = ReplacingMergeTree(import_time)
ORDER BY (source, patent_id, ipc_code)
"""


def _strip(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()

    text = _strip(value)
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue

    return None


def split_people(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = [str(item).strip() for item in value]
    else:
        text = _strip(value)
        if not text:
            return []
        values = [part.strip() for part in ROW_SPLIT_PATTERN.split(text) if part.strip()]

    ordered: List[str] = []
    seen = set()
    for item in values:
        clean = _strip(item)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)

    return ordered


def normalize_cn_number(value: Any) -> str:
    text = _strip(value).replace(" ", "").upper()
    if not text:
        return ""
    if text.startswith("CN-"):
        return f"CN{text[3:]}"
    if text.startswith("CN"):
        return text
    return f"CN{text}"


def normalize_source(value: Any) -> str:
    return _strip(value) or SOURCE_NAME


def default_source_url(source: str, publication_number: str) -> str:
    normalized_source = normalize_source(source)
    if normalized_source == SOURCE_NAME:
        return "https://pss-system.cponline.cnipa.gov.cn/"
    if normalized_source == "google_patents" and publication_number:
        return f"https://patents.google.com/patent/{publication_number}"
    return ""


def safe_int(value: Any) -> int:
    if value in (None, "", []):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def first_value(record: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in record:
            value = record.get(key)
            if isinstance(value, str):
                if value.strip():
                    return _strip(value)
            elif isinstance(value, (list, tuple)):
                normalized = [item for item in value if _strip(item)]
                if normalized:
                    return normalized[0]
            elif value not in (None, ""):
                return value
    return ""


def build_patent_id(
    publication_number: str,
    application_number: str,
    fallback_seed: Optional[str] = None,
    source: Any = SOURCE_NAME,
) -> str:
    normalized_source = normalize_source(source)
    if publication_number:
        return f"{normalized_source}:publication:{publication_number}"
    if application_number:
        return f"{normalized_source}:application:{application_number}"
    normalized_seed = _strip(fallback_seed)
    if not normalized_seed:
        return ""
    digest = hashlib.sha1(normalized_seed.encode("utf-8")).hexdigest()
    return f"{normalized_source}:hash:{digest}"


def parse_cn_patent_record(record: Dict[str, Any]) -> Dict[str, Any]:
    raw_record = record if isinstance(record, dict) else {}
    source = normalize_source(raw_record.get("source"))

    application_raw = _strip(first_value(raw_record, FIELD_ALIASES["application_number"]))
    publication_raw = _strip(first_value(raw_record, FIELD_ALIASES["publication_number"]))
    patent_number_raw = _strip(first_value(raw_record, FIELD_ALIASES["patent_number"]))
    patent_title = _strip(first_value(raw_record, FIELD_ALIASES["patent_title"]))
    patent_abstract = _strip(first_value(raw_record, FIELD_ALIASES["patent_abstract"]))

    application_number = normalize_cn_number(application_raw)
    publication_number = normalize_cn_number(publication_raw)
    patent_number = normalize_cn_number(patent_number_raw)

    app_date = normalize_date(first_value(raw_record, FIELD_ALIASES["application_date"]))
    pub_date = normalize_date(first_value(raw_record, FIELD_ALIASES["publication_date"]))
    raw_grant_date = normalize_date(first_value(raw_record, FIELD_ALIASES["grant_date"]))
    grant_date = raw_grant_date or DEFAULT_GRANT_DATE

    inventors = split_people(first_value(raw_record, FIELD_ALIASES["inventors"]))
    assignees = split_people(first_value(raw_record, FIELD_ALIASES["assignees"]))
    inventor_ids = split_people(first_value(raw_record, FIELD_ALIASES["inventor_ids"]))
    assignee_ids = split_people(first_value(raw_record, FIELD_ALIASES["assignee_ids"]))
    assignee_types = split_people(first_value(raw_record, FIELD_ALIASES["assignee_types"]))

    ipc_raw = first_value(raw_record, FIELD_ALIASES["ipc_codes"])
    if isinstance(ipc_raw, (list, tuple, set)):
        ipc_codes = split_people(list(ipc_raw))
    else:
        ipc_codes = split_people(ipc_raw)

    cpc_raw = first_value(raw_record, FIELD_ALIASES["cpc_codes"])
    if isinstance(cpc_raw, (list, tuple, set)):
        cpc_codes = split_people(list(cpc_raw))
    else:
        cpc_codes = split_people(cpc_raw)

    uspc_raw = first_value(raw_record, FIELD_ALIASES["uspc_codes"])
    if isinstance(uspc_raw, (list, tuple, set)):
        uspc_codes = split_people(list(uspc_raw))
    else:
        uspc_codes = split_people(uspc_raw)

    num_claims = safe_int(first_value(raw_record, ["num_claims", "claim_count", "claims"]))
    num_cited_by = safe_int(
        first_value(raw_record, ["num_cited_by", "patent_num_times_cited_by_us_patents"])
    )
    num_citations = safe_int(
        first_value(
            raw_record,
            ["num_citations", "patent_num_total_documents_cited", "num_documents_cited"],
        )
    )
    family_id = _strip(first_value(raw_record, ["family_id", "familyId", "patent_family_id"]))
    source_url = _strip(
        first_value(
            raw_record,
            ["source_url", "patent_url", "url", "link_url", "link", "sourceLink"],
        )
    )
    if not source_url:
        source_url = default_source_url(source, publication_number)

    fallback_values = [
        patent_title,
        str(app_date or ""),
        assignees[0] if assignees else "",
        inventors[0] if inventors else "",
    ]
    fallback_seed = "|".join(fallback_values) if any(_strip(item) for item in fallback_values) else ""
    source_number = build_patent_id(publication_number, application_number, fallback_seed, source)
    if source_number.startswith(f"{source}:hash:") and publication_number == "" and application_number == "":
        log_message(
            f"record_id_fallback source={source} reason=missing_identifier seed={_strip(fallback_seed)}",
            "WARNING",
        )
    if not source_number:
        log_message(
            "record_id_missing reason=no_identifier title="
            f"{_strip(patent_title)[:64]} source={source}",
            "WARNING",
        )

    status = _strip(first_value(raw_record, FIELD_ALIASES["status"]))
    patent_type = _strip(first_value(raw_record, FIELD_ALIASES["patent_type"]))

    return {
        "patent_id": source_number,
        "source": source,
        "patent_number": patent_number,
        "patent_title": patent_title,
        "patent_abstract": patent_abstract,
        "grant_date": grant_date,
        "application_date": app_date,
        "publication_date": pub_date,
        "patent_type": patent_type,
        "status": status,
        "country": _strip(raw_record.get("country")) or DEFAULT_COUNTRY,
        "inventors": inventors,
        "inventor_ids": inventor_ids,
        "assignees": assignees,
        "assignee_ids": assignee_ids,
        "assignee_types": assignee_types,
        "cpc_codes": cpc_codes,
        "ipc_codes": ipc_codes,
        "uspc_codes": uspc_codes,
        "num_claims": num_claims,
        "num_cited_by": num_cited_by,
        "num_citations": num_citations,
        "family_id": family_id,
        "application_number": application_number,
        "publication_number": publication_number,
        "source_url": source_url,
        "raw_json": json.dumps(raw_record, ensure_ascii=False, sort_keys=True),
        "import_time": datetime.now(),
    }


def _decompose_ipc(code: Any) -> Tuple[str, str, str, str, str]:
    normalized = _strip(code).replace(" ", "").upper()
    if not normalized:
        return "", "", "", "", ""

    parts = normalized.split("/")
    if len(parts) == 1:
        prefix = parts[0]
        suffix = ""
        log_message(f"parse_ipc_fallback reason=no_slash code={normalized}", "WARNING")
    elif len(parts) == 2:
        prefix = parts[0]
        suffix = parts[1]
    else:
        prefix = parts[0]
        suffix = "/".join(parts[1:])
        log_message(
            f"parse_ipc_fallback reason=multi_part_split code={normalized} parts={len(parts)}",
            "WARNING",
        )

    match = re.match(r"^([A-HY])(\d{2})([A-Z])(.*)$", prefix)
    if not match:
        log_message(f"parse_ipc_fallback reason=invalid_structure code={normalized}", "WARNING")
        return "", "", "", "", normalized

    ipc_section, ipc_class, ipc_subclass, tail = match.groups()
    ipc_group = f"{tail}/{suffix}" if suffix else tail
    return ipc_section, ipc_class, ipc_subclass, ipc_group, normalized


def parse_ipc_rows(patent_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_codes = patent_row.get("ipc_codes") or []
    if isinstance(raw_codes, (str, int, float)):
        raw_codes = [raw_codes]
    elif not isinstance(raw_codes, (list, tuple, set)):
        raw_codes = []

    patent_id = patent_row.get("patent_id", "")
    source = normalize_source(patent_row.get("source"))
    import_time = patent_row.get("import_time") or datetime.now()

    rows: List[Dict[str, Any]] = []
    valid_index = 0
    for raw_code in raw_codes:
        code = _strip(raw_code).replace(" ", "").upper()
        if not code:
            continue

        ipc_section = ""
        ipc_class = ""
        ipc_subclass = ""
        ipc_group = ""
        ipc_section, ipc_class, ipc_subclass, ipc_group, raw_value = _decompose_ipc(code)

        rows.append(
            {
                "source": source,
                "patent_id": patent_id,
                "ipc_code": code,
                "ipc_section": ipc_section,
                "ipc_class": ipc_class,
                "ipc_subclass": ipc_subclass,
                "ipc_group": ipc_group,
                "is_primary": 1 if valid_index == 0 else 0,
                "raw_value": raw_value or code,
                "import_time": import_time,
            }
        )
        valid_index += 1

    return rows


def _iter_csv_records(handle) -> Iterator[Dict[str, Any]]:
    reader = csv.DictReader(handle)
    for row in reader:
        if not row:
            continue
        yield {str(key).strip(): (value if value is not None else "") for key, value in row.items()}


def _iter_json_records(payload: Union[str, bytes]) -> Iterator[Dict[str, Any]]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        log_message("json_records_invalid payload", "WARNING")
        return

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
            else:
                log_message(f"json_records_skipped_non_dict value={type(item).__name__}", "WARNING")
        return

    if not isinstance(data, dict):
        log_message(f"json_records_unsupported_root value={type(data).__name__}", "WARNING")
        return

    for key in ("records", "patents", "data", "results"):
        value = data.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item
                else:
                    log_message(
                        f"json_records_skipped_non_dict_in_{key} value={type(item).__name__}",
                        "WARNING",
                    )
            return

    yield data


def _iter_xml_records(payload: Union[str, bytes]) -> Iterator[Dict[str, Any]]:
    if isinstance(payload, bytes):
        payload_text = payload.decode("utf-8", errors="replace")
    else:
        payload_text = payload

    root = ET.fromstring(payload_text)

    def node_to_dict(node: ET.Element) -> Dict[str, Any]:
        item = {}
        children = list(node)
        if children:
            for child in children:
                key = child.tag.split("}")[-1]
                if list(child):
                    child_value = node_to_dict(child)
                    if key in item:
                        existing = item[key]
                        if isinstance(existing, list):
                            existing.append(child_value)
                        else:
                            item[key] = [existing, child_value]
                    else:
                        item[key] = child_value
                else:
                    child_text = (child.text or "").strip()
                    if key in item:
                        existing = item[key]
                        if isinstance(existing, list):
                            existing.append(child_text)
                        else:
                            item[key] = [existing, child_text]
                    else:
                        item[key] = child_text
        elif node.text:
            item[node.tag.split("}")[-1]] = node.text.strip()
        else:
            item[node.tag.split("}")[-1]] = ""
        return item

    child_candidates = [
        element
        for element in list(root)
        if element.tag.split("}")[-1].split("]")[-1] in {"record", "patent", "item", "row"}
    ]

    if child_candidates:
        for item in child_candidates:
            payload = node_to_dict(item)
            if payload:
                yield payload
        return

    payload = node_to_dict(root)
    if payload:
        yield payload


def _iter_zip_records(binary_data: bytes) -> Iterator[Dict[str, Any]]:
    with zipfile.ZipFile(BytesIO(binary_data)) as archive:
        for member_name in sorted(archive.namelist()):
            if member_name.endswith("/"):
                continue
            lower = member_name.lower()
            member_data = archive.read(member_name)
            if lower.endswith(".zip"):
                yield from _iter_zip_records(member_data)
                continue
            if lower.endswith(".csv"):
                with StringIO(member_data.decode("utf-8-sig", errors="replace")) as handle:
                    yield from _iter_csv_records(handle)
            elif lower.endswith(".jsonl"):
                text = member_data.decode("utf-8-sig", errors="replace")
                for raw in text.splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    record = _safe_json_obj(line)
                    if record:
                        yield record
            elif lower.endswith(".json"):
                yield from _iter_json_records(member_data.decode("utf-8-sig", errors="replace"))
            elif lower.endswith(".xml"):
                yield from _iter_xml_records(member_data)


def _safe_json_obj(line: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        log_message(f"json_line_invalid line={line[:80]}", "WARNING")
        return None
    if isinstance(data, dict):
        return data
    log_message(f"json_line_non_dict value={type(data).__name__}", "WARNING")
    return None


def iter_input_records(input_path: str) -> Iterator[Dict[str, Any]]:
    path = os.path.abspath(input_path)
    if os.path.isfile(path):
        yield from _iter_file_records(path)
        return

    if not os.path.isdir(path):
        return

    for root, _dirs, filenames in os.walk(path):
        for filename in sorted(filenames):
            full_path = os.path.join(root, filename)
            if os.path.isfile(full_path):
                yield from _iter_file_records(full_path)


def _iter_file_records(file_path: str) -> Iterator[Dict[str, Any]]:
    lower = file_path.lower()
    if lower.endswith(".csv"):
        with open(file_path, "r", encoding="utf-8-sig", newline="") as handle:
            yield from _iter_csv_records(handle)
        return

    if lower.endswith(".jsonl"):
        with open(file_path, "r", encoding="utf-8-sig", newline="") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                record = _safe_json_obj(line)
                if record:
                    yield record
        return

    if lower.endswith(".json"):
        with open(file_path, "r", encoding="utf-8-sig") as handle:
            for item in _iter_json_records(handle.read()):
                yield item
        return

    if lower.endswith(".xml"):
        with open(file_path, "r", encoding="utf-8-sig") as handle:
            yield from _iter_xml_records(handle.read())
        return

    if lower.endswith(".zip"):
        with open(file_path, "rb") as handle:
            archive_data = handle.read()
        yield from _iter_zip_records(archive_data)
        return

    return


def row_to_insert_values(row: Dict[str, Any], columns: Sequence[str]) -> List[Any]:
    return [row.get(column) for column in columns]


def _stable_id(seed: str, name: str, index: int) -> str:
    payload = f"{seed}|{index}|{_strip(name)}"
    hashed = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{seed}:{hashed}"


def _split_name(name: str) -> Tuple[str, str]:
    text = _strip(name)
    if not text:
        return "", ""
    if " " in text:
        parts = text.split(" ", 1)
        return parts[0], parts[1]
    return text, ""


def expand_patent_rows(patent_row: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    import_time = patent_row.get("import_time") or datetime.now()
    patent_id = _strip(patent_row.get("patent_id"))
    source = normalize_source(patent_row.get("source"))

    applications = []
    application_id = _strip(patent_row.get("application_number"))
    application_date = patent_row.get("application_date")
    if application_id or application_date:
        applications.append(
            {
                "patent_id": patent_id,
                "application_id": application_id,
                "application_date": application_date,
                "series_code": "",
                "raw_json": patent_row.get("raw_json", "{}"),
                "import_time": import_time,
            }
        )

    inventors = []
    inventor_ids = patent_row.get("inventor_ids", []) or []
    inventor_types = split_people(patent_row.get("inventor_types", []))
    for index, name in enumerate(patent_row.get("inventors", []) or []):
        first_name, last_name = _split_name(name)
        inventor_id = _strip(inventor_ids[index]) if index < len(inventor_ids) else ""
        if not inventor_id:
            inventor_id = _stable_id("inventor", f"{patent_id}|{name}", index)
        inventors.append(
            {
                "patent_id": patent_id,
                "inventor_id": inventor_id,
                "inventor_name": _strip(name),
                "inventor_first_name": first_name,
                "inventor_last_name": last_name,
                "location_id": "",
                "raw_json": patent_row.get("raw_json", "{}"),
                "import_time": import_time,
            }
        )

    assignees = []
    assignee_ids = patent_row.get("assignee_ids", []) or []
    assignee_types = patent_row.get("assignee_types", []) or []
    for index, name in enumerate(patent_row.get("assignees", []) or []):
        assignee_id = _strip(assignee_ids[index]) if index < len(assignee_ids) else ""
        if not assignee_id:
            assignee_id = _stable_id("assignee", f"{patent_id}|{name}", index)
        assignee_type = assignee_types[index] if index < len(assignee_types) else ""
        assignees.append(
            {
                "patent_id": patent_id,
                "assignee_id": assignee_id,
                "assignee_name": _strip(name),
                "assignee_type": _strip(assignee_type),
                "location_id": "",
                "raw_json": patent_row.get("raw_json", "{}"),
                "import_time": import_time,
            }
        )

    abstracts = []
    patent_abstract = _strip(patent_row.get("patent_abstract", ""))
    if patent_abstract:
        abstracts.append(
            {
                "patent_id": patent_id,
                "patent_abstract": patent_abstract,
                "raw_json": patent_row.get("raw_json", "{}"),
                "import_time": import_time,
            }
        )

    return {
        "patents": [
            {
                "patent_id": patent_id,
                "source": source,
                "patent_number": _strip(patent_row.get("patent_number", "")),
                "patent_title": _strip(patent_row.get("patent_title", "")),
                "patent_abstract": patent_abstract,
                "grant_date": patent_row.get("grant_date", DEFAULT_GRANT_DATE) or DEFAULT_GRANT_DATE,
                "application_date": patent_row.get("application_date"),
                "publication_date": patent_row.get("publication_date"),
                "patent_type": _strip(patent_row.get("patent_type", "")),
                "status": _strip(patent_row.get("status", "")),
                "country": _strip(patent_row.get("country")) or DEFAULT_COUNTRY,
                "inventors": patent_row.get("inventors", []),
                "inventor_ids": patent_row.get("inventor_ids", []),
                "assignees": patent_row.get("assignees", []),
                "assignee_ids": patent_row.get("assignee_ids", []),
                "assignee_types": patent_row.get("assignee_types", []),
                "cpc_codes": patent_row.get("cpc_codes", []),
                "ipc_codes": patent_row.get("ipc_codes", []),
                "uspc_codes": patent_row.get("uspc_codes", []),
                "num_claims": patent_row.get("num_claims", 0),
                "num_cited_by": patent_row.get("num_cited_by", 0),
                "num_citations": patent_row.get("num_citations", 0),
                "family_id": _strip(patent_row.get("family_id", "")),
                "application_number": patent_row.get("application_number", ""),
                "publication_number": patent_row.get("publication_number", ""),
                "source_url": _strip(patent_row.get("source_url", "")),
                "raw_json": patent_row.get("raw_json", "{}"),
                "import_time": import_time,
            }
        ],
        "applications": applications,
        "inventors": inventors,
        "assignees": assignees,
        "abstracts": abstracts,
        "ipc": parse_ipc_rows(patent_row),
    }


def build_import_batches(rows: Sequence[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
    if batch_size <= 0:
        batch_size = 1
    return [list(rows[i : i + batch_size]) for i in range(0, len(rows), batch_size)]


def create_clickhouse_client():
    return clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        username=CH_USERNAME,
        password=CH_PASSWORD,
        database=CH_DATABASE,
    )


def ensure_database(client):
    client.command(CREATE_DATABASE_SQL)
    client.command(CREATE_PATENTS_TABLE_SQL)
    client.command(CREATE_PATENT_APPLICATIONS_TABLE_SQL)
    client.command(CREATE_PATENT_INVENTORS_TABLE_SQL)
    client.command(CREATE_PATENT_ASSIGNEES_TABLE_SQL)
    client.command(CREATE_PATENT_ABSTRACTS_TABLE_SQL)
    client.command(CREATE_PATENT_IPC_TABLE_SQL)


def insert_table(
    client,
    table_name: str,
    rows: Sequence[Dict[str, Any]],
    columns: Sequence[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    if not rows:
        return 0

    inserted = 0
    for batch in build_import_batches(rows, batch_size):
        values = [row_to_insert_values(row, columns) for row in batch]
        client.insert(f"{CH_DATABASE}.{table_name}", values, column_names=columns)
        inserted += len(values)
    return inserted


def insert_import_result(
    client,
    table_name: str,
    rows: Sequence[Dict[str, Any]],
    columns: Sequence[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    return insert_table(client, table_name, rows, columns, batch_size=batch_size)


def get_empty_progress() -> Dict[str, Any]:
    return {
        "completed_files": [],
        "last_error": "",
        "last_update": "",
    }


def load_progress(progress_file: Optional[str] = None) -> Dict[str, Any]:
    target = progress_file or PROGRESS_FILE
    if not os.path.exists(target):
        return get_empty_progress()

    try:
        with open(target, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except Exception:
        return get_empty_progress()

    if not isinstance(raw, dict):
        return get_empty_progress()

    completed_files = raw.get("completed_files")
    if not isinstance(completed_files, list):
        raw["completed_files"] = []
    return raw


def save_progress(progress: Dict[str, Any], progress_file: Optional[str] = None) -> None:
    target = progress_file or PROGRESS_FILE
    os.makedirs(os.path.dirname(target), exist_ok=True)
    progress["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(target, "w", encoding="utf-8") as file:
        json.dump(progress, file, ensure_ascii=False, indent=2)


def file_marker(file_path: str) -> Dict[str, Any]:
    absolute_path = os.path.abspath(file_path)
    return {
        "path": absolute_path,
        "size": os.path.getsize(absolute_path),
        "mtime": os.path.getmtime(absolute_path),
    }


def is_file_completed(progress: Dict[str, Any], file_path: str) -> bool:
    marker = file_marker(file_path)
    completed = progress.get("completed_files")
    if not isinstance(completed, list):
        return False

    for item in completed:
        if not isinstance(item, dict):
            continue
        if (
            item.get("path") == marker["path"]
            and item.get("size") == marker["size"]
            and float(item.get("mtime", -1)) == marker["mtime"]
        ):
            return True
    return False


def insert_import_progress(progress: Dict[str, Any], file_path: str, count: int) -> Dict[str, Any]:
    marker = file_marker(file_path)
    marker.update(
        {
            "record_count": count,
            "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

    completed = progress.setdefault("completed_files", [])
    if not isinstance(completed, list):
        progress["completed_files"] = []
        completed = progress["completed_files"]

    updated = False
    for index, item in enumerate(completed):
        if not isinstance(item, dict):
            continue
        if item.get("path") == marker["path"]:
            completed[index] = marker
            updated = True
            break

    if not updated:
        completed.append(marker)

    return progress


def log_message(message: str, level: str = "INFO") -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {level} | {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(line)


def format_stats(stats: Dict[str, int]) -> str:
    return (
        f"files={stats.get('files', 0)}, "
        f"raw_records={stats.get('raw_records', 0)}, "
        f"patents={stats.get('patents', 0)}, "
        f"skipped={stats.get('skipped', 0)}, "
        f"inventors={stats.get('inventors', 0)}, "
        f"assignees={stats.get('assignees', 0)}, "
        f"ipc={stats.get('ipc', 0)}, "
        f"inserted={stats.get('inserted', 0)}"
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CNIPA patent importer")
    parser.add_argument(
        "--input",
        default=os.path.join(PROJECT_ROOT, "data", "cnipa"),
        help="Input file or directory for CNIPA export data",
    )
    parser.add_argument("--mode", default="import", choices=["import"], help="Run mode")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Insert batch size")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of records to process")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only, do not write ClickHouse")
    parser.add_argument(
        "--progress-file",
        default=PROGRESS_FILE,
        help="Progress file path",
    )
    parser.add_argument(
        "--log-file",
        default=LOG_FILE,
        help="Log file path",
    )
    return parser.parse_args(argv)


def _iter_input_file_paths(input_path: str) -> Iterator[str]:
    path = os.path.abspath(input_path)
    if os.path.isfile(path):
        yield path
        return
    if not os.path.isdir(path):
        return
    for root, _dirs, filenames in os.walk(path):
        for filename in sorted(filenames):
            if not filename:
                continue
            yield os.path.join(root, filename)


def _supported_input(file_path: str) -> bool:
    lower = file_path.lower()
    return lower.endswith((".csv", ".jsonl", ".json", ".xml", ".zip"))


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    global LOG_FILE
    global PROGRESS_FILE
    LOG_FILE = args.log_file
    PROGRESS_FILE = args.progress_file

    os.makedirs(LOG_DIR, exist_ok=True)

    if args.mode != "import":
        log_message(f"unsupported mode: {args.mode}", "ERROR")
        return 1

    if not os.path.exists(args.input):
        log_message(f"input not found: {args.input}", "ERROR")
        return 1

    progress = load_progress(args.progress_file)
    stats = {
        "files": 0,
        "raw_records": 0,
        "patents": 0,
        "skipped": 0,
        "inventors": 0,
        "assignees": 0,
        "ipc": 0,
        "inserted": 0,
    }

    ch_client = None
    if not args.dry_run:
        ch_client = create_clickhouse_client()
        if ch_client is None:
            log_message("clickhouse client init failed", "ERROR")
            return 1
        try:
            ensure_database(ch_client)
        except Exception as exc:
            log_message(f"ensure_database failed: {exc}", "ERROR")
            return 1

    for file_path in _iter_input_file_paths(args.input):
        if not _supported_input(file_path):
            continue

        if is_file_completed(progress, file_path):
            stats["skipped"] += 1
            continue

        stats["files"] += 1
        patent_rows: List[Dict[str, Any]] = []
        application_rows: List[Dict[str, Any]] = []
        inventor_rows: List[Dict[str, Any]] = []
        assignee_rows: List[Dict[str, Any]] = []
        abstract_rows: List[Dict[str, Any]] = []
        ipc_rows: List[Dict[str, Any]] = []

        file_records = 0
        file_skipped = 0
        file_patents = 0
        file_inventors = 0
        file_assignees = 0
        file_ipc = 0
        file_reached_limit = False

        for raw_record in iter_input_records(file_path):
            stats["raw_records"] += 1
            file_records += 1

            if not isinstance(raw_record, dict):
                file_skipped += 1
                stats["skipped"] += 1
                log_message(
                    f"record_skipped reason=unsupported_row path={file_path} raw_index={stats['raw_records']}",
                    "WARNING",
                )
                continue

            parsed = parse_cn_patent_record(raw_record)
            if not parsed.get("patent_id"):
                file_skipped += 1
                stats["skipped"] += 1
                continue

            expanded = expand_patent_rows(parsed)

            patent_rows.extend(expanded.get("patents", []))
            application_rows.extend(expanded.get("applications", []))
            inventor_rows.extend(expanded.get("inventors", []))
            assignee_rows.extend(expanded.get("assignees", []))
            abstract_rows.extend(expanded.get("abstracts", []))
            ipc_rows.extend(expanded.get("ipc", []))
            file_patents += len(expanded.get("patents", []))
            file_inventors += len(expanded.get("inventors", []))
            file_assignees += len(expanded.get("assignees", []))
            file_ipc += len(expanded.get("ipc", []))
            stats["patents"] += len(expanded.get("patents", []))
            stats["inventors"] += len(expanded.get("inventors", []))
            stats["assignees"] += len(expanded.get("assignees", []))
            stats["ipc"] += len(expanded.get("ipc", []))

            if args.limit is not None and stats["raw_records"] >= args.limit:
                file_reached_limit = True
                break

        reached_limit = args.limit is not None and (
            stats["raw_records"] >= args.limit or file_reached_limit
        )
        if args.dry_run:
            log_message(
                f"file_completed path={file_path} records={file_records} "
                f"skipped={file_skipped} patents={file_patents} inventors={file_inventors} assignees={file_assignees} ipc={file_ipc}"
            )
            continue

        inserted_total = 0
        try:
            for table_name, rows, columns in (
                (CH_TABLE, patent_rows, PATENT_COLUMNS),
                (CH_APPLICATIONS_TABLE, application_rows, APPLICATION_COLUMNS),
                (CH_INVENTORS_TABLE, inventor_rows, INVENTOR_COLUMNS),
                (CH_ASSIGNEES_TABLE, assignee_rows, ASSIGNEE_COLUMNS),
                (CH_ABSTRACTS_TABLE, abstract_rows, ABSTRACT_COLUMNS),
                (CH_IPC_TABLE, ipc_rows, IPC_COLUMNS),
            ):
                if not rows:
                    continue
                try:
                    inserted_total += insert_import_result(
                        ch_client,
                        table_name,
                        rows,
                        columns,
                        batch_size=args.batch_size,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"table={table_name} rows={len(rows)} error={exc}"
                    ) from exc

            if not reached_limit:
                insert_import_progress(progress, file_path, file_records)

            if not reached_limit:
                save_progress(progress, args.progress_file)
            stats["inserted"] += inserted_total
            log_message(
                f"file_completed path={file_path} records={file_records} skipped={file_skipped} "
                f"patents={file_patents} inventors={file_inventors} assignees={file_assignees} ipc={file_ipc}"
            )
        except Exception as exc:
            progress["last_error"] = f"{file_path}: {exc}"
            save_progress(progress, args.progress_file)
            log_message(
                f"insert_failed {exc} file={file_path}",
                "ERROR",
            )
            return 1

        if reached_limit:
            break

    if not args.dry_run:
        save_progress(progress, args.progress_file)
    log_message(f"run completed: {format_stats(stats)}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
