#!/usr/bin/env python3
"""
OpenAlex paper fetcher (ClickHouse).

核心能力：
1. 按天抓取，支持断点续传；
2. 多 API key 自动轮换；
3. 所有 key 额度耗尽后，再用匿名模式补抓一轮；
4. 匿名也限额后，等待到次日 09:00 自动重试；
5. 批量写入 ClickHouse，使用反连接去重，避免重复入库。
"""

import asyncio
import gc
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import clickhouse_connect
import httpx
import pandas as pd
from tqdm.asyncio import tqdm


OPENALEX_API_BASE = "https://api.openalex.org"

# OpenAlex 轮换凭据（按顺序使用）
DEFAULT_OPENALEX_CREDENTIALS: List[Tuple[str, str]] = [
    ("20228132063@m.scnu.edu.cn", "L9vCNGOe2ILsen4OQP3aPg"),
    ("29364625666@qq.com", "toZBE5tNglH7oDydLefrKc"),
    ("13360197039@163.com", "zF5B0bERxfXCZsPF1P5TiY"),
    ("apl064@outlook.com", "1KyA5m5gjQxBgFetDtko9Q"),
    ("17818151056@163.com", "2ZiX5542GoZp9VYwHv2jPj"),
    ("1509901785@qq.com", "Q5QcudPogcFTfvV7vFOH1r"),
]

# 所有 key 用完后，是否追加一轮匿名抓取
ENABLE_ANONYMOUS_FALLBACK = True
RESTART_HOUR = 9

# ClickHouse 配置
CH_HOST = "localhost"
CH_PORT = 8123
CH_DATABASE = "academic_db"
CH_TABLE = "OpenAlex"
CH_USERNAME = "default"
CH_PASSWORD = ""

# 日期范围配置
START_DATE = "20260410"
END_YEAR = 1936
SKIP_FIRST_DAY_OF_MONTH = False

# 并发与重试配置
MAX_CONCURRENT_DAYS = 16
PER_PAGE = 200
REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 3
PAGE_REQUEST_INTERVAL = 0.05
BATCH_WRITE_THRESHOLD = 9000

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
LOG_DIR = PROJECT_ROOT / "log"
LOG_FILE = LOG_DIR / "openalex_fetch_fast.log"
PROGRESS_FILE = LOG_DIR / "openalex_fetch_progress.json"

OPENALEX_TABLE_COLUMNS = [
    "author_id",
    "author",
    "uid",
    "doi",
    "title",
    "rank",
    "journal",
    "citation_count",
    "tag",
    "state",
    "institution_id",
    "institution_name",
    "institution_country",
    "institution_type",
    "raw_affiliation",
    "fwci",
    "citation_percentile",
    "primary_topic",
    "is_retracted",
    "publication_date",
    "import_time",
]
DEDUP_KEY_COLUMNS = [column for column in OPENALEX_TABLE_COLUMNS if column != "import_time"]
ROW_INT_FIELDS = {"rank", "citation_count", "citation_percentile"}
ROW_FLOAT_FIELDS = {"fwci"}
ROW_BOOL_FIELDS = {"is_retracted"}

RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class Credential:
    email: str
    api_key: str
    source: str

    @property
    def is_anonymous(self) -> bool:
        return not self.email and not self.api_key

    @property
    def display(self) -> str:
        if self.is_anonymous:
            return "anonymous"
        email_display = self.email if self.email else "no-email"
        key_suffix = self.api_key[-6:] if self.api_key else "no-key"
        return f"{email_display}/*{key_suffix}"


def build_credentials() -> List[Credential]:
    credentials: List[Credential] = []
    for email, api_key in DEFAULT_OPENALEX_CREDENTIALS:
        email_value = (email or "").strip()
        api_key_value = (api_key or "").strip()
        if not email_value and not api_key_value:
            continue
        credentials.append(Credential(email=email_value, api_key=api_key_value, source="configured"))

    if ENABLE_ANONYMOUS_FALLBACK:
        credentials.append(Credential(email="", api_key="", source="anonymous"))
    return credentials


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    header = (
        f"\n{'=' * 84}\n"
        f"start_time={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"scope={START_DATE} -> {END_YEAR}\n"
        f"concurrency={MAX_CONCURRENT_DAYS}\n"
        f"{'=' * 84}\n"
    )
    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(header)


def log_message(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(line + "\n")


def create_clickhouse_client():
    try:
        client = clickhouse_connect.get_client(
            host=CH_HOST,
            port=CH_PORT,
            username=CH_USERNAME,
            password=CH_PASSWORD,
            database=CH_DATABASE,
        )
        log_message("clickhouse_connected=true")
        return client
    except Exception as exc:
        log_message(f"clickhouse_connect_failed error={exc}", "ERROR")
        return None


def get_empty_progress() -> Dict[str, Any]:
    return {"current_date": None, "completed_dates": [], "last_update": None}


def load_progress() -> Dict[str, Any]:
    if not PROGRESS_FILE.exists():
        return get_empty_progress()
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            if not isinstance(data, dict):
                return get_empty_progress()
            data.setdefault("current_date", None)
            data.setdefault("completed_dates", [])
            data.setdefault("last_update", None)
            if not isinstance(data["completed_dates"], list):
                data["completed_dates"] = []
            return data
    except Exception:
        return get_empty_progress()


def save_progress(progress: Dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    progress["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PROGRESS_FILE, "w", encoding="utf-8") as file:
        json.dump(progress, file, ensure_ascii=False, indent=2)


def date_to_key(date_str: str) -> str:
    return date_str.replace("-", "")


def key_to_date(date_key: str) -> str:
    return f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}"


def get_all_dates_backward() -> List[str]:
    start_date_obj = datetime.strptime(START_DATE, "%Y%m%d")
    end_date_obj = datetime(END_YEAR, 12, 31)
    dates: List[str] = []

    current = start_date_obj
    while current >= end_date_obj:
        if SKIP_FIRST_DAY_OF_MONTH and current.day == 1:
            current -= timedelta(days=1)
            continue
        dates.append(current.strftime("%Y-%m-%d"))
        current -= timedelta(days=1)
    return dates


def determine_author_tag(rank: int, total_authors: int) -> str:
    if rank == 1:
        return "第一作者"
    if rank == total_authors:
        return "最后作者"
    return "其他"


def parse_openalex_work(work: Dict[str, Any]) -> Dict[str, Any]:
    paper_id = work.get("id") or ""
    title = (work.get("title") or "").replace("\n", " ")
    doi = work.get("doi") or ""

    authors: List[Dict[str, Any]] = []
    for idx, authorship in enumerate(work.get("authorships", [])):
        author_info = authorship.get("author") or {}
        author_name = author_info.get("display_name")
        if not author_name:
            continue

        author_id = author_info.get("id") or ""
        if "/A" in author_id:
            author_id = author_id.split("/A")[-1]

        institutions = authorship.get("institutions") or []
        raw_affiliations = authorship.get("raw_affiliation_strings") or []
        institution = {"id": "", "name": "", "country": "", "type": "", "raw": ""}
        if raw_affiliations:
            institution["raw"] = raw_affiliations[0]
        if institutions:
            first_inst = institutions[0]
            inst_id = first_inst.get("id") or ""
            if "/I" in inst_id:
                inst_id = inst_id.split("/I")[-1]
            institution.update(
                {
                    "id": inst_id,
                    "name": first_inst.get("display_name") or "",
                    "country": first_inst.get("country_code") or "",
                    "type": first_inst.get("type") or "",
                }
            )

        authors.append(
            {
                "id": author_id,
                "name": author_name,
                "orcid": author_info.get("orcid") or "",
                "rank": idx + 1,
                "institution": institution,
            }
        )

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    journal = source.get("display_name") or "unknown"

    citation_percentile_obj = work.get("cited_by_percentile_year") or {}
    citation_percentile = citation_percentile_obj.get("min", 0) if isinstance(citation_percentile_obj, dict) else 0

    primary_topic_obj = work.get("primary_topic") or {}
    primary_topic = primary_topic_obj.get("display_name", "") if isinstance(primary_topic_obj, dict) else ""

    return {
        "uid": str(paper_id),
        "doi": str(doi),
        "title": str(title),
        "authors": authors,
        "journal": str(journal),
        "citation_count": int(work.get("cited_by_count", 0) or 0),
        "publication_date": str(work.get("publication_date", "") or ""),
        "fwci": float(work.get("fwci", 0) or 0),
        "citation_percentile": int(citation_percentile or 0),
        "primary_topic": str(primary_topic or ""),
        "is_retracted": bool(work.get("is_retracted", False)),
    }


def expand_papers_to_rows(papers: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for paper in papers:
        authors = paper.get("authors", []) or []
        total_authors = len(authors)
        for author_info in authors:
            rank = int(author_info.get("rank", 1) or 1)
            institution = author_info.get("institution", {}) or {}
            rows.append(
                {
                    "author_id": str(author_info.get("id", "") or ""),
                    "author": str(author_info.get("name", "") or ""),
                    "uid": str(paper.get("uid", "") or ""),
                    "doi": str(paper.get("doi", "") or ""),
                    "title": str(paper.get("title", "") or ""),
                    "rank": rank,
                    "journal": str(paper.get("journal", "") or ""),
                    "publication_date": str(paper.get("publication_date", "") or ""),
                    "citation_count": int(paper.get("citation_count", 0) or 0),
                    "tag": determine_author_tag(rank, total_authors),
                    "state": "",
                    "institution_id": str(institution.get("id", "") or ""),
                    "institution_name": str(institution.get("name", "") or ""),
                    "institution_country": str(institution.get("country", "") or ""),
                    "institution_type": str(institution.get("type", "") or ""),
                    "raw_affiliation": str(institution.get("raw", "") or ""),
                    "fwci": float(paper.get("fwci", 0) or 0),
                    "citation_percentile": int(paper.get("citation_percentile", 0) or 0),
                    "primary_topic": str(paper.get("primary_topic", "") or ""),
                    "is_retracted": bool(paper.get("is_retracted", False)),
                }
            )
    return rows


def build_dedup_insert_sql(temp_table: str) -> str:
    target_columns = ", ".join(OPENALEX_TABLE_COLUMNS)
    select_columns = ", ".join([f"tmp.{column}" for column in OPENALEX_TABLE_COLUMNS])
    join_condition = " AND ".join([f"tmp.{column} = tgt.{column}" for column in DEDUP_KEY_COLUMNS])
    return f"""
        INSERT INTO {CH_DATABASE}.{CH_TABLE} ({target_columns})
        SELECT {select_columns}
        FROM {CH_DATABASE}.{temp_table} tmp
        LEFT ANTI JOIN {CH_DATABASE}.{CH_TABLE} tgt
        ON {join_condition}
    """


def batch_insert_clickhouse(client, rows: List[Dict[str, Any]]) -> bool:
    if not rows:
        return True

    try:
        import_time = datetime.now()
        cleaned_rows: List[Dict[str, Any]] = []

        for row in rows:
            normalized = {column: row.get(column) for column in OPENALEX_TABLE_COLUMNS if column != "import_time"}
            normalized["import_time"] = import_time

            for key in ROW_INT_FIELDS:
                try:
                    normalized[key] = int(normalized.get(key, 0) or 0)
                except (TypeError, ValueError):
                    normalized[key] = 0

            for key in ROW_FLOAT_FIELDS:
                try:
                    normalized[key] = float(normalized.get(key, 0) or 0)
                except (TypeError, ValueError):
                    normalized[key] = 0.0

            for key in ROW_BOOL_FIELDS:
                normalized[key] = bool(normalized.get(key, False))

            for key, value in normalized.items():
                if key in ROW_INT_FIELDS or key in ROW_FLOAT_FIELDS or key in ROW_BOOL_FIELDS or key == "import_time":
                    continue
                normalized[key] = "" if value is None else str(value)
            cleaned_rows.append(normalized)

        df = pd.DataFrame(cleaned_rows, columns=OPENALEX_TABLE_COLUMNS)
        for key in ROW_INT_FIELDS:
            df[key] = pd.to_numeric(df[key], errors="coerce").fillna(0).astype(int)
        for key in ROW_FLOAT_FIELDS:
            df[key] = pd.to_numeric(df[key], errors="coerce").fillna(0.0).astype(float)
        for key in ROW_BOOL_FIELDS:
            df[key] = df[key].astype(bool)
        df["import_time"] = pd.to_datetime(df["import_time"])

        temp_table = f"temp_openalex_insert_dedup_{os.getpid()}"
        client.command(f"DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}")
        client.command(
            f"""
            CREATE TABLE {CH_DATABASE}.{temp_table} AS {CH_DATABASE}.{CH_TABLE}
            ENGINE = Memory
            """
        )
        client.insert_df(
            f"{CH_DATABASE}.{temp_table}",
            df,
            column_names=OPENALEX_TABLE_COLUMNS,
        )
        client.command(build_dedup_insert_sql(temp_table))
        client.command(f"DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}")
        return True
    except Exception as exc:
        log_message(f"clickhouse_insert_failed error={exc}", "ERROR")
        return False


def build_request_headers(credential: Credential) -> Dict[str, str]:
    user_agent_email = credential.email if credential.email else "academic-scraper@localhost"
    headers = {
        "User-Agent": f"academic-scraper/1.0 (mailto:{user_agent_email})",
        "Accept": "application/json",
    }
    if credential.email:
        headers["Mailto"] = credential.email
    return headers


def build_request_params(date_str: str, cursor: str, credential: Credential) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "filter": f"from_publication_date:{date_str},to_publication_date:{date_str},type:article",
        "per-page": PER_PAGE,
        "cursor": cursor,
    }
    if credential.api_key:
        params["api_key"] = credential.api_key
    if credential.email:
        params["mailto"] = credential.email
    return params


def extract_retry_after_seconds(response: httpx.Response) -> Optional[int]:
    header_value = response.headers.get("Retry-After")
    if header_value:
        try:
            return max(1, int(header_value))
        except (TypeError, ValueError):
            pass
    try:
        data = response.json()
        retry_after = data.get("retryAfter")
        if retry_after is not None:
            return max(1, int(retry_after))
    except Exception:
        pass
    return None


async def probe_credential(http_client: httpx.AsyncClient, credential: Credential) -> bool:
    try:
        response = await http_client.get(
            f"{OPENALEX_API_BASE}/authors",
            params={"per-page": 1, **({"api_key": credential.api_key} if credential.api_key else {})},
            headers=build_request_headers(credential),
            timeout=10.0,
        )
    except Exception as exc:
        log_message(f"credential_probe_failed credential={credential.display} error={exc}", "WARNING")
        return True

    if response.status_code == 429:
        retry_after = extract_retry_after_seconds(response)
        retry_segment = f" retry_after={retry_after}s" if retry_after else ""
        log_message(f"credential_quota_exhausted credential={credential.display}{retry_segment}", "WARNING")
        return False

    if response.status_code >= 500:
        log_message(
            f"credential_probe_server_error credential={credential.display} status={response.status_code}",
            "WARNING",
        )
        return True

    if response.status_code != 200:
        log_message(
            f"credential_probe_non200 credential={credential.display} status={response.status_code}",
            "WARNING",
        )
        return True
    return True


async def flush_papers(
    ch_client,
    date_str: str,
    papers: List[Dict[str, Any]],
    write_count: int,
    total_rows: int,
    total_papers: int,
) -> Tuple[bool, int, int, int]:
    if not papers:
        return True, write_count, total_rows, total_papers

    rows = expand_papers_to_rows(papers)
    inserted = batch_insert_clickhouse(ch_client, rows)
    if not inserted:
        return False, write_count, total_rows, total_papers

    write_count += 1
    total_rows += len(rows)
    total_papers += len(papers)
    log_message(
        f"flush_ok date={date_str} batch={write_count} papers={len(papers)} rows={len(rows)}"
    )
    return True, write_count, total_rows, total_papers


async def fetch_openalex_day(
    http_client: httpx.AsyncClient,
    ch_client,
    date_str: str,
    credential: Credential,
    day_pbar: tqdm,
    paper_pbar: tqdm,
) -> Dict[str, Any]:
    papers_buffer: List[Dict[str, Any]] = []
    cursor = "*"
    retry_count = 0

    total_papers = 0
    total_rows = 0
    write_count = 0

    while True:
        params = build_request_params(date_str, cursor, credential)
        try:
            response = await http_client.get(
                f"{OPENALEX_API_BASE}/works",
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if retry_count >= MAX_RETRIES:
                return {"date_str": date_str, "status": "error", "error": str(exc)}
            retry_count += 1
            await asyncio.sleep(RETRY_WAIT_SECONDS)
            continue
        except Exception as exc:
            return {"date_str": date_str, "status": "error", "error": str(exc)}

        if response.status_code == 429:
            retry_after = extract_retry_after_seconds(response)
            return {
                "date_str": date_str,
                "status": RATE_LIMIT_EXCEEDED,
                "retry_after": retry_after,
                "credential": credential.display,
            }

        if response.status_code >= 500:
            if retry_count >= MAX_RETRIES:
                return {
                    "date_str": date_str,
                    "status": "error",
                    "error": f"http_{response.status_code}",
                }
            retry_count += 1
            await asyncio.sleep(RETRY_WAIT_SECONDS)
            continue

        if response.status_code != 200:
            return {
                "date_str": date_str,
                "status": "error",
                "error": f"http_{response.status_code}: {response.text[:180]}",
            }

        retry_count = 0
        try:
            data = response.json()
        except Exception as exc:
            return {"date_str": date_str, "status": "error", "error": f"invalid_json: {exc}"}

        results = data.get("results", []) or []
        if not results:
            break

        for work in results:
            papers_buffer.append(parse_openalex_work(work))
        paper_pbar.update(len(results))

        if len(papers_buffer) >= BATCH_WRITE_THRESHOLD:
            ok, write_count, total_rows, total_papers = await flush_papers(
                ch_client,
                date_str,
                papers_buffer,
                write_count,
                total_rows,
                total_papers,
            )
            if not ok:
                return {
                    "date_str": date_str,
                    "status": "error",
                    "error": "clickhouse_insert_failed",
                }
            papers_buffer = []
            gc.collect()

        meta = data.get("meta", {}) or {}
        next_cursor = meta.get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor
        await asyncio.sleep(PAGE_REQUEST_INTERVAL)

    if papers_buffer:
        ok, write_count, total_rows, total_papers = await flush_papers(
            ch_client,
            date_str,
            papers_buffer,
            write_count,
            total_rows,
            total_papers,
        )
        if not ok:
            return {"date_str": date_str, "status": "error", "error": "clickhouse_insert_failed"}

    day_pbar.update(1)
    if total_papers > 0:
        return {
            "date_str": date_str,
            "status": "ok",
            "paper_count": total_papers,
            "row_count": total_rows,
            "write_count": write_count,
        }

    return {"date_str": date_str, "status": "no_data", "paper_count": 0, "row_count": 0, "write_count": 0}


def compute_next_restart(now: Optional[datetime] = None, restart_hour: int = RESTART_HOUR) -> datetime:
    now_value = now or datetime.now()
    next_day = (now_value + timedelta(days=1)).date()
    return datetime.combine(next_day, datetime.min.time()).replace(hour=restart_hour)


async def wait_until_next_restart(restart_hour: int = RESTART_HOUR) -> None:
    target = compute_next_restart(restart_hour=restart_hour)
    while True:
        now = datetime.now()
        remain = (target - now).total_seconds()
        if remain <= 0:
            return
        sleep_seconds = min(600, max(1, int(remain)))
        log_message(f"all_credentials_exhausted wait_until={target.strftime('%Y-%m-%d %H:%M:%S')} sleep={sleep_seconds}s")
        await asyncio.sleep(sleep_seconds)


def mark_date_completed(progress: Dict[str, Any], completed_set: set, date_str: str) -> None:
    date_key = date_to_key(date_str)
    if date_key in completed_set:
        return
    completed_set.add(date_key)
    progress["current_date"] = date_key
    progress["completed_dates"].append(date_key)
    save_progress(progress)


async def run_round_for_credential(
    pending_dates: List[str],
    credential: Credential,
    ch_client,
    progress: Dict[str, Any],
    completed_set: set,
) -> Dict[str, Any]:
    if not pending_dates:
        return {"status": "done", "pending_dates": []}

    headers = build_request_headers(credential)
    limits = httpx.Limits(
        max_connections=MAX_CONCURRENT_DAYS * 2,
        max_keepalive_connections=MAX_CONCURRENT_DAYS,
    )

    queue: asyncio.Queue[str] = asyncio.Queue()
    for date_str in pending_dates:
        queue.put_nowait(date_str)

    stop_on_quota = asyncio.Event()
    result_lock = asyncio.Lock()
    pending_after_round: List[str] = []
    counters = {"ok_days": 0, "no_data_days": 0, "error_days": 0, "papers": 0, "rows": 0}
    disable_tqdm = not sys.stdout.isatty()
    day_pbar = tqdm(
        total=len(pending_dates),
        desc=f"{credential.display} 日期",
        unit="天",
        ncols=90,
        disable=disable_tqdm,
    )
    paper_pbar = tqdm(
        total=0,
        desc=f"{credential.display} 论文",
        unit="篇",
        ncols=90,
        disable=disable_tqdm,
    )

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, limits=limits, http2=True, headers=headers) as client:
        quota_ok = await probe_credential(client, credential)
        if not quota_ok:
            day_pbar.close()
            paper_pbar.close()
            return {"status": RATE_LIMIT_EXCEEDED, "pending_dates": pending_dates}

        async def worker() -> None:
            while True:
                if stop_on_quota.is_set():
                    return
                try:
                    date_str = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                result = await fetch_openalex_day(
                    http_client=client,
                    ch_client=ch_client,
                    date_str=date_str,
                    credential=credential,
                    day_pbar=day_pbar,
                    paper_pbar=paper_pbar,
                )

                async with result_lock:
                    status = result.get("status")
                    if status == "ok":
                        counters["ok_days"] += 1
                        counters["papers"] += result.get("paper_count", 0)
                        counters["rows"] += result.get("row_count", 0)
                        mark_date_completed(progress, completed_set, date_str)
                    elif status == "no_data":
                        counters["no_data_days"] += 1
                        mark_date_completed(progress, completed_set, date_str)
                    elif status == RATE_LIMIT_EXCEEDED:
                        stop_on_quota.set()
                        pending_after_round.append(date_str)
                    else:
                        counters["error_days"] += 1
                        log_message(f"day_fetch_failed date={date_str} error={result.get('error')}", "WARNING")
                        pending_after_round.append(date_str)

                queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(MAX_CONCURRENT_DAYS)]
        await asyncio.gather(*workers, return_exceptions=True)

    while not queue.empty():
        pending_after_round.append(queue.get_nowait())

    # 保序去重，避免一个日期重复入 pending
    dedup_pending: List[str] = []
    seen = set()
    for item in pending_after_round:
        if item in seen:
            continue
        dedup_pending.append(item)
        seen.add(item)

    day_pbar.close()
    paper_pbar.close()

    log_message(
        "round_summary "
        f"credential={credential.display} "
        f"ok_days={counters['ok_days']} no_data_days={counters['no_data_days']} "
        f"error_days={counters['error_days']} papers={counters['papers']} rows={counters['rows']} "
        f"pending={len(dedup_pending)}"
    )

    if stop_on_quota.is_set():
        return {"status": RATE_LIMIT_EXCEEDED, "pending_dates": dedup_pending}
    return {"status": "ok", "pending_dates": dedup_pending}


def build_pending_dates(progress: Dict[str, Any]) -> List[str]:
    all_dates = get_all_dates_backward()
    completed_set = set(progress.get("completed_dates", []))
    pending: List[str] = []
    for date_str in all_dates:
        if date_to_key(date_str) not in completed_set:
            pending.append(date_str)
    return pending


async def main_async() -> None:
    setup_logging()
    log_message("openalex_fetcher_started")

    ch_client = create_clickhouse_client()
    if not ch_client:
        log_message("exit_reason=clickhouse_unavailable", "ERROR")
        return

    progress = load_progress()
    completed_set = set(progress.get("completed_dates", []))
    credentials = build_credentials()
    if not credentials:
        log_message("exit_reason=no_credentials", "ERROR")
        return

    log_message(
        f"configuration start_date={START_DATE} end_year={END_YEAR} concurrency={MAX_CONCURRENT_DAYS} "
        f"credentials={len(credentials)} anonymous_enabled={ENABLE_ANONYMOUS_FALLBACK}"
    )

    while True:
        pending_dates = build_pending_dates(progress)
        if not pending_dates:
            log_message("all_dates_completed=true")
            return

        log_message(f"pending_dates={len(pending_dates)} latest={pending_dates[0]} oldest={pending_dates[-1]}")

        round_pending = pending_dates
        exhausted_all = True
        for credential in credentials:
            if not round_pending:
                break

            log_message(f"credential_round_start credential={credential.display} pending={len(round_pending)}")
            result = await run_round_for_credential(
                pending_dates=round_pending,
                credential=credential,
                ch_client=ch_client,
                progress=progress,
                completed_set=completed_set,
            )
            round_pending = result.get("pending_dates", round_pending)

            if result.get("status") == RATE_LIMIT_EXCEEDED:
                log_message(
                    f"credential_exhausted credential={credential.display} remaining={len(round_pending)}",
                    "WARNING",
                )
                continue

            exhausted_all = False
            if not round_pending:
                break

        if not round_pending:
            continue

        # 所有凭据都被限额（包括匿名），等到次日 09:00
        if exhausted_all:
            save_progress(progress)
            await wait_until_next_restart()
            continue

        # 非限额导致的剩余（例如网络失败）直接继续下一轮
        log_message(f"round_remaining_due_to_errors={len(round_pending)} retry_immediately=true", "WARNING")
        await asyncio.sleep(5)


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        log_message("interrupted_by_user", "WARNING")
    except Exception as exc:
        log_message(f"fatal_error={exc}", "ERROR")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
