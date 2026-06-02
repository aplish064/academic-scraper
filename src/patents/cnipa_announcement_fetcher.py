#!/usr/bin/env python3
"""Pure helpers for CNIPA announcement records."""

import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import requests

try:
    from . import cnipa_importer as cn_patent_fetcher
except ImportError:  # pragma: no cover - supports direct script execution from src/
    import cnipa_importer as cn_patent_fetcher  # type: ignore


SOURCE_NAME = "cnipa_announcement"
ENDPOINT = "https://app.gjzwfw.gov.cn/jimps/link.do"
REFERER = "https://app.gjzwfw.gov.cn/jmopen/webapp/html5/zlgbggcx/index.html"
ANNOUNCEMENT_KEY = "6f0c5ce612ba4471acce875dd7e6f6a2"
SIGN_PREFIX = "zscqgbgg"
PUBTYPE_NAMES = {
    1: "发布公告",
    2: "发明公布更正",
    3: "发明授权",
    4: "发明授权更正",
    5: "发明解密",
    6: "实用新型",
    7: "实用新型更正",
    8: "实用新型解密",
    9: "外观设计",
    10: "外观设计更正",
}
GRANT_PUBTYPES = {3, 4, 6, 7, 9, 10}
INITIAL_BUCKETS = list("0123456789")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
LOG_DIR = os.path.join(PROJECT_ROOT, "log", "patents", "cnipa_announcement")
LOG_DIR_LEGACY = os.path.join(PROJECT_ROOT, "log")
DEFAULT_BATCH_SIZE = cn_patent_fetcher.DEFAULT_BATCH_SIZE
DEFAULT_PAGE_SIZE = 100
DEFAULT_REQUEST_DELAY = 1.0
DEFAULT_SPLIT_THRESHOLD = 9000
DEFAULT_MAX_PREFIX_LENGTH = 8
DEFAULT_MAX_RESULTS_PER_BUCKET = 10000
DEFAULT_PROGRESS_FILE = os.path.join(PROJECT_ROOT, "log", "patents", "cnipa_announcement", "cnipa_announcement_progress.json")
DEFAULT_LOG_FILE = os.path.join(PROJECT_ROOT, "log", "patents", "cnipa_announcement", "cnipa_announcement_fetcher.log")
LEGACY_PROGRESS_FILE = os.path.join(LOG_DIR_LEGACY, "cnipa_announcement_progress.json")
LEGACY_LOG_FILE = os.path.join(LOG_DIR_LEGACY, "cnipa_announcement_fetcher.log")
DEFAULT_MAX_RETRIES = 5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": REFERER,
    "Origin": "https://app.gjzwfw.gov.cn",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def build_signature(request_time: Any) -> str:
    payload = f"{SIGN_PREFIX}{request_time}".encode("utf-8")
    return hashlib.md5(payload).hexdigest()


def yyyymmdd(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")

    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return text

    parsed = datetime.strptime(text, "%Y-%m-%d")
    return parsed.strftime("%Y%m%d")


def _request_time_ms() -> str:
    return str(int(time.time() * 1000))


def build_search_payload(
    keyword: str,
    announcement_date: Any,
    pubtype: int,
    offset: int,
    size: int,
    request_time: Any = None,
) -> Dict[str, Any]:
    request_time = _request_time_ms() if request_time is None else str(request_time)
    announcement_day = yyyymmdd(announcement_date)
    raw = {
        "searchStr": keyword,
        "ggr_begin": announcement_day,
        "ggr_end": announcement_day,
        "from": offset,
        "size": size,
        "pubtypeList": [pubtype],
    }
    condition = {
        "from": "1",
        "key": ANNOUNCEMENT_KEY,
        "sign": build_signature(request_time),
        "requestTime": request_time,
        "raw": raw,
    }

    return {
        "param": json.dumps(condition, ensure_ascii=False, separators=(",", ":")),
    }


def log_event(log_file: str, level: str, event: str, **fields: Any) -> None:
    if not log_file:
        return

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "event": event,
    }
    record.update({key: to_jsonable(value) for key, value in fields.items()})
    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str))
        handle.write("\n")


def _response_endpoint_error(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    if payload.get("success") is False:
        return str(payload.get("message") or payload.get("errorMsg") or payload.get("error") or payload)
    if payload.get("error") or payload.get("errorMsg"):
        return str(payload.get("error") or payload.get("errorMsg"))
    if payload.get("error_code"):
        reason = payload.get("reason") or payload.get("message") or "endpoint error"
        return f"endpoint error_code {payload.get('error_code')}: {reason}"

    code = payload.get("code")
    if code not in (None, "", 0, "0", 200, "200"):
        return str(payload.get("message") or payload.get("msg") or f"endpoint code {code}")

    return None


class CnipaAnnouncementClient:
    def __init__(
        self,
        session: Any = None,
        request_delay: float = 0.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        log_file: str = "",
        timeout: int = 30,
        sleep_func: Any = None,
        now_ms_func: Any = None,
    ) -> None:
        self.session = session or requests.Session()
        self.request_delay = request_delay
        self.max_retries = max(1, int(max_retries))
        self.log_file = log_file
        self.timeout = timeout
        self.sleep_func = sleep_func or time.sleep
        self.now_ms_func = now_ms_func or _request_time_ms

    def post_search(
        self,
        keyword: str,
        announcement_date: Any,
        pubtype: int,
        offset: int = 0,
        size: int = 100,
        request_time: Any = None,
    ) -> Dict[str, Any]:
        last_error: Optional[BaseException] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                if self.request_delay:
                    self.sleep_func(self.request_delay)
                attempt_request_time = str(request_time) if request_time is not None else str(self.now_ms_func())
                payload = build_search_payload(
                    keyword=keyword,
                    announcement_date=announcement_date,
                    pubtype=pubtype,
                    offset=offset,
                    size=size,
                    request_time=attempt_request_time,
                )
                response = self.session.post(ENDPOINT, headers=HEADERS, data=payload, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                endpoint_error = _response_endpoint_error(data)
                if endpoint_error:
                    raise RuntimeError(endpoint_error)
                if not isinstance(data, dict):
                    raise RuntimeError("CNIPA endpoint returned non-object JSON")
                return data
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                log_event(
                    self.log_file,
                    "warning",
                    "cnipa_announcement_retry",
                    attempt=attempt,
                    max_retries=self.max_retries,
                    error=str(exc),
                )
                if self.request_delay:
                    self.sleep_func(min(120, self.request_delay * (2 ** (attempt - 1))))

        raise RuntimeError(f"CNIPA announcement search failed after {self.max_retries} attempts: {last_error}")

    def count_bucket(
        self,
        keyword: str,
        announcement_date: Any,
        pubtype: int,
        request_time: Any = None,
    ) -> int:
        data = self.post_search(
            keyword=keyword,
            announcement_date=announcement_date,
            pubtype=pubtype,
            offset=0,
            size=1,
            request_time=request_time,
        )
        if "allCount" not in data:
            raise RuntimeError("CNIPA announcement response missing allCount")
        try:
            return int(data["allCount"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"CNIPA announcement allCount is not an integer: {data.get('allCount')}") from exc

    def search_bucket(
        self,
        keyword: str,
        announcement_date: Any,
        pubtype: int,
        offset: int = 0,
        size: int = 100,
        request_time: Any = None,
    ) -> List[Dict[str, Any]]:
        data = self.post_search(
            keyword=keyword,
            announcement_date=announcement_date,
            pubtype=pubtype,
            offset=offset,
            size=size,
            request_time=request_time,
        )
        if "patentList" not in data:
            raise RuntimeError("CNIPA announcement response missing patentList")
        patent_list = data["patentList"]
        if not isinstance(patent_list, list):
            raise RuntimeError("CNIPA announcement patentList is not a list")
        return patent_list


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def load_progress(progress_file: str = "") -> Dict[str, Any]:
    if not progress_file:
        progress_file = DEFAULT_PROGRESS_FILE
    if not os.path.exists(progress_file) and progress_file == DEFAULT_PROGRESS_FILE and os.path.exists(LEGACY_PROGRESS_FILE):
        progress_file = LEGACY_PROGRESS_FILE
    if not os.path.exists(progress_file):
        return {}
    try:
        with open(progress_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def write_progress(progress_file: str = "", **fields: Any) -> None:
    """Merge progress fields for a single-process, single-writer checkpoint file."""
    if not progress_file:
        return

    progress = load_progress(progress_file)
    progress.update({key: to_jsonable(value) for key, value in fields.items() if value is not None})
    progress["updated_at"] = datetime.now().isoformat(timespec="seconds")

    progress_dir = os.path.dirname(progress_file)
    if progress_dir:
        os.makedirs(progress_dir, exist_ok=True)
    tmp_dir = progress_dir or "."
    basename = os.path.basename(progress_file)
    tmp_path = ""
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=tmp_dir,
        prefix=f"{basename}.",
        suffix=".tmp",
    ) as handle:
        tmp_path = handle.name
        json.dump(progress, handle, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        handle.write("\n")
    try:
        os.replace(tmp_path, progress_file)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def parse_yyyymmdd(value: Any) -> Optional[date]:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text == "00000000" or len(text) != 8:
        return None

    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def parse_pubtypes(value: Any) -> List[int]:
    if value is None:
        return []

    text = str(value).strip()
    if not text or text.lower() == "all":
        return []

    return [int(part.strip()) for part in text.split(",") if part.strip()]


def _split_people_or_codes(value: Any) -> List[str]:
    if value is None:
        return []

    text = str(value).strip()
    if not text:
        return []

    for separator in ("；", ",", "，"):
        text = text.replace(separator, ";")
    return [part.strip() for part in text.split(";") if part.strip()]


def _parse_record_pubtype(value: Any) -> Optional[int]:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return int(text)
    except ValueError:
        return None


def _record_pubtype_name(value: Any) -> str:
    pubtype = _parse_record_pubtype(value)
    if pubtype is not None:
        return PUBTYPE_NAMES.get(pubtype, str(value))

    return str(value or "").strip()


def _adapter_iso_date(value: Any) -> str:
    parsed = parse_yyyymmdd(yyyymmdd(value)) if value not in (None, "") else None
    return parsed.isoformat() if parsed else ""


def map_announcement_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt a CNIPA announcement record for cn_patent_fetcher.parse_cn_patent_record."""
    pubtype = _parse_record_pubtype(record.get("pubtype"))
    pubtype_name = _record_pubtype_name(record.get("pubtype"))
    publication_date = _adapter_iso_date(record.get("pd"))
    application_date = _adapter_iso_date(record.get("ad"))

    row = {
        "source": SOURCE_NAME,
        "country": "CN",
        "patent_number": record.get("pn", "") or "",
        "publication_number": record.get("pn", "") or "",
        "application_number": record.get("an", "") or "",
        "patent_title": record.get("ti", "") or "",
        "patent_abstract": record.get("abs", "") or "",
        "publication_date": publication_date,
        "application_date": application_date,
        "patent_type": pubtype_name,
        "status": pubtype_name,
        "inventors": "; ".join(_split_people_or_codes(record.get("e72"))),
        "assignees": "; ".join(_split_people_or_codes(record.get("e71_73"))),
        "ipc_codes": "; ".join(_split_people_or_codes(record.get("e51"))),
        "source_url": record.get("codeUrl", "") or "",
        "raw_json": json.dumps(record, ensure_ascii=False, sort_keys=True),
    }
    if publication_date and pubtype in GRANT_PUBTYPES:
        row["grant_date"] = publication_date

    return row


def parse_date_arg(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        raise ValueError("date argument is required")

    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


def iter_dates(start_date: Any, end_date: Any) -> Iterable[date]:
    current = parse_date_arg(start_date)
    end = parse_date_arg(end_date)
    if current > end:
        raise ValueError(f"start date {current.isoformat()} is after end date {end.isoformat()}")

    while current <= end:
        yield current
        current += timedelta(days=1)


def _iso_date(value: Any) -> str:
    return parse_date_arg(value).isoformat()


def resolve_buckets(
    client: Any,
    announcement_date: Any,
    pubtype: int,
    initial_buckets: Sequence[str] = INITIAL_BUCKETS,
    split_threshold: int = 10000,
    max_prefix_length: int = 6,
    log_file: str = "",
) -> Tuple[List[Tuple[str, int]], List[Dict[str, Any]]]:
    fetchable: List[Tuple[str, int]] = []
    capped: List[Dict[str, Any]] = []
    pending = list(initial_buckets)
    date_iso = _iso_date(announcement_date)

    while pending:
        bucket = pending.pop(0)
        try:
            count = int(client.count_bucket(bucket, announcement_date, pubtype))
        except Exception as exc:
            raise BucketCountError(str(exc), announcement_date, pubtype, bucket) from exc

        if count == 0:
            log_event(log_file, "info", "bucket_count", date=date_iso, pubtype=pubtype, bucket=bucket, count=count, action="skip")
            continue

        if count < split_threshold:
            fetchable.append((bucket, count))
            log_event(log_file, "info", "bucket_count", date=date_iso, pubtype=pubtype, bucket=bucket, count=count, action="fetch")
            continue

        if len(bucket) < max_prefix_length:
            children = [f"{bucket}{digit}" for digit in INITIAL_BUCKETS]
            pending = children + pending
            log_event(
                log_file,
                "info",
                "bucket_count",
                date=date_iso,
                pubtype=pubtype,
                bucket=bucket,
                count=count,
                action="split",
            )
            continue

        fetchable.append((bucket, count))
        task = {"date": date_iso, "pubtype": pubtype, "bucket": bucket, "count": count}
        capped.append(task)
        log_event(log_file, "warning", "bucket_count", action="cap", **task)

    return fetchable, capped


def patent_identity(record: Dict[str, Any]) -> str:
    return cn_patent_fetcher.parse_cn_patent_record(record)["patent_id"]


def fetch_bucket_records(
    client: Any,
    announcement_date: Any,
    pubtype: int,
    bucket: str,
    total_count: int,
    page_size: int,
    max_results: int,
    seen_patent_ids: Set[str],
    log_file: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    if page_size <= 0:
        page_size = 1

    limit = min(int(total_count), int(max_results))
    records: List[Dict[str, Any]] = []
    deduped_count = 0
    date_iso = _iso_date(announcement_date)

    for offset in range(0, limit, page_size):
        size = min(page_size, limit - offset)
        raw_records = client.search_bucket(bucket, announcement_date, pubtype, offset=offset, size=size)
        kept = 0
        page_deduped = 0

        for raw in raw_records:
            mapped = map_announcement_record(raw)
            patent_id = patent_identity(mapped)
            if patent_id and patent_id in seen_patent_ids:
                deduped_count += 1
                page_deduped += 1
                continue
            if patent_id:
                seen_patent_ids.add(patent_id)
            records.append(mapped)
            kept += 1

        log_event(
            log_file,
            "info",
            "page_fetch",
            date=date_iso,
            pubtype=pubtype,
            bucket=bucket,
            offset=offset,
            size=size,
            returned=len(raw_records),
            kept=kept,
            deduped=page_deduped,
        )

    return records, deduped_count


def insert_records(ch_client: Any, records: Sequence[Dict[str, Any]], batch_size: int) -> int:
    expanded_rows = {
        "patents": [],
        "applications": [],
        "inventors": [],
        "assignees": [],
        "abstracts": [],
        "ipc": [],
    }

    for record in records:
        parsed = cn_patent_fetcher.parse_cn_patent_record(record)
        expanded = cn_patent_fetcher.expand_patent_rows(parsed)
        for key in expanded_rows:
            expanded_rows[key].extend(expanded.get(key, []))

    inserted_patents = cn_patent_fetcher.insert_import_result(
        ch_client,
        cn_patent_fetcher.CH_TABLE,
        expanded_rows["patents"],
        cn_patent_fetcher.PATENT_COLUMNS,
        batch_size=batch_size,
    )
    cn_patent_fetcher.insert_import_result(
        ch_client,
        cn_patent_fetcher.CH_APPLICATIONS_TABLE,
        expanded_rows["applications"],
        cn_patent_fetcher.APPLICATION_COLUMNS,
        batch_size=batch_size,
    )
    cn_patent_fetcher.insert_import_result(
        ch_client,
        cn_patent_fetcher.CH_INVENTORS_TABLE,
        expanded_rows["inventors"],
        cn_patent_fetcher.INVENTOR_COLUMNS,
        batch_size=batch_size,
    )
    cn_patent_fetcher.insert_import_result(
        ch_client,
        cn_patent_fetcher.CH_ASSIGNEES_TABLE,
        expanded_rows["assignees"],
        cn_patent_fetcher.ASSIGNEE_COLUMNS,
        batch_size=batch_size,
    )
    cn_patent_fetcher.insert_import_result(
        ch_client,
        cn_patent_fetcher.CH_ABSTRACTS_TABLE,
        expanded_rows["abstracts"],
        cn_patent_fetcher.ABSTRACT_COLUMNS,
        batch_size=batch_size,
    )
    cn_patent_fetcher.insert_import_result(
        ch_client,
        cn_patent_fetcher.CH_IPC_TABLE,
        expanded_rows["ipc"],
        cn_patent_fetcher.IPC_COLUMNS,
        batch_size=batch_size,
    )

    return inserted_patents


def create_bootstrap_clickhouse_client() -> Any:
    return cn_patent_fetcher.clickhouse_connect.get_client(
        host=cn_patent_fetcher.CH_HOST,
        port=cn_patent_fetcher.CH_PORT,
        username=cn_patent_fetcher.CH_USERNAME,
        password=cn_patent_fetcher.CH_PASSWORD,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch CNIPA patent announcements")
    parser.add_argument("--start-date", required=True, help="Inclusive start announcement date, YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="Inclusive end announcement date, YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="ClickHouse insert batch size")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE, help="CNIPA search page size")
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY, help="Delay between retry attempts")
    parser.add_argument(
        "--split-threshold",
        type=int,
        default=DEFAULT_SPLIT_THRESHOLD,
        help="Bucket count threshold that triggers prefix splitting",
    )
    parser.add_argument(
        "--max-prefix-length",
        type=int,
        default=DEFAULT_MAX_PREFIX_LENGTH,
        help="Maximum bucket prefix length before a bucket is capped",
    )
    parser.add_argument(
        "--max-results-per-bucket",
        type=int,
        default=DEFAULT_MAX_RESULTS_PER_BUCKET,
        help="Maximum fetched results per resolved bucket",
    )
    parser.add_argument("--pubtypes", default="all", help="Comma-separated CNIPA pubtype IDs, or all")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Fetch and log without ClickHouse inserts")
    parser.add_argument("--limit-dates", type=int, default=None, help="Maximum number of not-yet-completed dates to process")
    parser.add_argument("--progress-file", default=DEFAULT_PROGRESS_FILE, help="Progress checkpoint path")
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE, help="JSONL event log path")
    return parser.parse_args(argv)


def _progress_list(progress: Dict[str, Any], key: str) -> List[Any]:
    value = progress.get(key, [])
    return list(value) if isinstance(value, list) else []


def _progress_int(progress: Dict[str, Any], key: str) -> int:
    try:
        return int(progress.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _selected_pubtypes(value: Any) -> List[int]:
    parsed = parse_pubtypes(value)
    return parsed or sorted(PUBTYPE_NAMES)


def _task_key(task: Dict[str, Any]) -> Tuple[str, int, str]:
    return (str(task.get("date", "")), int(task.get("pubtype", 0) or 0), str(task.get("bucket", "")))


def _task_record(announcement_date: Any, pubtype: int, bucket: str) -> Dict[str, Any]:
    return {"date": _iso_date(announcement_date), "pubtype": int(pubtype), "bucket": str(bucket)}


def _dedupe_tasks(tasks: Sequence[Any]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, int, str]] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        key = _task_key(task)
        if not key[0] or not key[2] or key in seen:
            continue
        seen.add(key)
        deduped.append(dict(task))
    return deduped


def _append_unique_task(tasks: List[Dict[str, Any]], seen: Set[Tuple[str, int, str]], task: Dict[str, Any]) -> None:
    key = _task_key(task)
    if key in seen:
        return
    seen.add(key)
    tasks.append(dict(task))


class BucketCountError(RuntimeError):
    def __init__(self, message: str, announcement_date: Any, pubtype: int, bucket: str) -> None:
        super().__init__(message)
        self.announcement_date = _iso_date(announcement_date)
        self.pubtype = int(pubtype)
        self.bucket = str(bucket)


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    start = parse_date_arg(args.start_date)
    end = parse_date_arg(args.end_date)
    pubtypes = _selected_pubtypes(args.pubtypes)

    client = CnipaAnnouncementClient(request_delay=args.request_delay, log_file=args.log_file)
    ch_client = None
    if not args.dry_run:
        bootstrap_client = create_bootstrap_clickhouse_client()
        cn_patent_fetcher.ensure_database(bootstrap_client)
        ch_client = cn_patent_fetcher.create_clickhouse_client()

    progress = load_progress(args.progress_file)
    if "dry_run" in progress and bool(progress.get("dry_run")) != bool(args.dry_run):
        progress = {
            key: value
            for key, value in progress.items()
            if key
            not in {
                "completed_dates",
                "completed_tasks",
                "capped_tasks",
                "fetched_records",
                "inserted_patents",
                "deduped_records",
            }
        }

    completed_dates = _progress_list(progress, "completed_dates")
    completed_date_set = {str(item) for item in completed_dates}
    completed_tasks = _dedupe_tasks(_progress_list(progress, "completed_tasks"))
    completed_task_set = {_task_key(task) for task in completed_tasks}
    capped_tasks = _dedupe_tasks(_progress_list(progress, "capped_tasks"))
    capped_task_set = {_task_key(task) for task in capped_tasks}
    fetched_records = _progress_int(progress, "fetched_records")
    inserted_patents = _progress_int(progress, "inserted_patents")
    deduped_records = _progress_int(progress, "deduped_records")

    write_progress(
        args.progress_file,
        status="running",
        source=SOURCE_NAME,
        start_date=start,
        end_date=end,
        dry_run=args.dry_run,
        completed_dates=completed_dates,
        completed_tasks=completed_tasks,
        fetched_records=fetched_records,
        inserted_patents=inserted_patents,
        deduped_records=deduped_records,
        capped_tasks=capped_tasks,
    )

    try:
        processed_dates = 0
        for announcement_date in iter_dates(start, end):
            date_iso = announcement_date.isoformat()
            if date_iso in completed_date_set:
                continue
            if args.limit_dates is not None and processed_dates >= args.limit_dates:
                break

            processed_dates += 1
            seen_patent_ids: Set[str] = set()
            date_has_capped_tasks = False

            for pubtype in pubtypes:
                write_progress(args.progress_file, current_date=date_iso, current_pubtype=pubtype)
                buckets, capped = resolve_buckets(
                    client,
                    announcement_date,
                    pubtype,
                    split_threshold=args.split_threshold,
                    max_prefix_length=args.max_prefix_length,
                    log_file=args.log_file,
                )
                if capped:
                    date_has_capped_tasks = True
                for capped_task in capped:
                    _append_unique_task(capped_tasks, capped_task_set, capped_task)

                for bucket, total_count in buckets:
                    task = _task_record(announcement_date, pubtype, bucket)
                    if _task_key(task) in completed_task_set:
                        continue

                    write_progress(args.progress_file, current_bucket=bucket)
                    records, deduped_count = fetch_bucket_records(
                        client,
                        announcement_date,
                        pubtype,
                        bucket,
                        total_count=total_count,
                        page_size=args.page_size,
                        max_results=args.max_results_per_bucket,
                        seen_patent_ids=seen_patent_ids,
                        log_file=args.log_file,
                    )
                    fetched_records += len(records) + deduped_count
                    deduped_records += deduped_count

                    inserted_count = 0
                    if args.dry_run:
                        log_event(
                            args.log_file,
                            "info",
                            "dry_run_batch",
                            date=date_iso,
                            pubtype=pubtype,
                            bucket=bucket,
                            records=len(records),
                        )
                    else:
                        inserted_count = insert_records(ch_client, records, batch_size=args.batch_size)
                        inserted_patents += inserted_count
                        log_event(
                            args.log_file,
                            "info",
                            "batch_insert",
                            date=date_iso,
                            pubtype=pubtype,
                            bucket=bucket,
                            records=len(records),
                            inserted_patents=inserted_count,
                        )

                    _append_unique_task(completed_tasks, completed_task_set, task)
                    write_progress(
                        args.progress_file,
                        fetched_records=fetched_records,
                        inserted_patents=inserted_patents,
                        deduped_records=deduped_records,
                        completed_tasks=completed_tasks,
                        capped_tasks=capped_tasks,
                    )

            if not date_has_capped_tasks and date_iso not in completed_date_set:
                completed_dates.append(date_iso)
                completed_date_set.add(date_iso)

            write_progress(
                args.progress_file,
                completed_dates=completed_dates,
                completed_tasks=completed_tasks,
                capped_tasks=capped_tasks,
                current_bucket="",
            )

        final_status = "completed_with_capped_tasks" if capped_tasks else "completed"
        write_progress(
            args.progress_file,
            status=final_status,
            completed_dates=completed_dates,
            fetched_records=fetched_records,
            inserted_patents=inserted_patents,
            deduped_records=deduped_records,
            completed_tasks=completed_tasks,
            capped_tasks=capped_tasks,
            current_bucket="",
        )
        return 0
    except Exception as exc:
        failure_fields = {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }
        if isinstance(exc, BucketCountError):
            failure_fields.update(
                {
                    "current_date": exc.announcement_date,
                    "current_pubtype": exc.pubtype,
                    "current_bucket": exc.bucket,
                }
            )
        write_progress(args.progress_file, **failure_fields)
        raise


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
