#!/usr/bin/env python3
"""
Semantic Scholar Journal-Based Paper Fetcher
从期刊表CSV获取所有期刊的论文

Usage:
    python src/semantic_fetcher.py

Features:
    - 从CSV文件加载期刊列表
    - 验证期刊有效性（venue → query策略）
    - 批量获取所有期刊的论文
    - 支持断点续传（progress file）
    - 自动去重并插入ClickHouse
    - 实时进度显示和日志记录

Configuration:
    修改脚本顶部的配置参数：
    - CSV_PATH: 期刊表CSV文件路径
    - REQUEST_INTERVAL: API请求间隔（秒）
    - MAX_PAGES_PER_JOURNAL: 每个期刊最大页数限制
    - PAPERS_PER_REQUEST: 每次请求的论文数量

Progress Tracking:
    进度保存在 log/papers/semantic/journal_progress.json
    - journals: 每个期刊的状态（pending/valid/in_progress/completed/failed）
    - 支持中断后继续执行
    - 已完成的期刊会被跳过

Data Flow:
    1. 加载CSV → 2. 验证期刊 → 3. 获取论文 → 4. 插入数据库
    - 使用venue优先查询，无结果时尝试query
    - 过滤掉arxiv论文（与原逻辑一致）
    - 每个作者一行，包含排名和标签（第一作者/最后作者/其他）
"""

import requests
import json
import time
import os
import math
from datetime import datetime
from pathlib import Path
import clickhouse_connect
import pandas as pd
from typing import Any, Dict, List, Optional, Tuple
from tqdm import tqdm

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = Path(__file__).parent.parent.parent.absolute()

# ============ 配置参数 ============
API_KEY = "7Tts2u4jXLaebjvFPICkE7kpTJQvUaYG4byRSpBp"
BASE_URL = "https://api.semanticscholar.org/graph/v1"

# ClickHouse 配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'semantic'
CH_USERNAME = 'default'
CH_PASSWORD = ''

# CSV 配置
CSV_PATH = SCRIPT_DIR / "data/XR2026-UTF8.csv"
CSV_ENCODING = "utf-8-sig"

# 请求配置（可被环境变量覆盖）
DEFAULT_REQUEST_INTERVAL = 1.1
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60
DEFAULT_INSERT_FLUSH_ROWS = 5000

ENV_REQUEST_INTERVAL = "SEMANTIC_REQUEST_INTERVAL"
ENV_REQUEST_TIMEOUT = "SEMANTIC_REQUEST_TIMEOUT"
ENV_MAX_RETRIES = "SEMANTIC_MAX_RETRIES"
ENV_RATE_LIMIT_WAIT_SECONDS = "SEMANTIC_RATE_LIMIT_WAIT_SECONDS"
ENV_INSERT_FLUSH_ROWS = "SEMANTIC_INSERT_FLUSH_ROWS"

# 查询配置
PAPERS_PER_REQUEST = 100
MAX_PAGES_PER_JOURNAL = None  # None = 无限制
MAX_OFFSET_EXCLUSIVE = 1000   # 语义学术搜索 offset 上限（offset >= 1000 会 400）
PROGRESS_SAVE_EVERY_PAGES = 5 # 每处理 N 页落盘一次，减少进度文件 IO
INSERT_FLUSH_ROWS = DEFAULT_INSERT_FLUSH_ROWS      # 累积到 N 行后批量写入 ClickHouse

# 字段列表
FIELDS = "paperId,title,authors,year,venue,journal,publicationDate,citationCount,externalIds,url,abstract"

# 输出配置
LOG_DIR = SCRIPT_DIR / "log" / "papers" / "semantic"
LEGACY_LOG_DIR = SCRIPT_DIR / "log"
PROGRESS_FILE = LOG_DIR / "journal_progress.json"
LOG_FILE = LOG_DIR / "journal_fetch.log"
ERROR_LOG_FILE = LOG_DIR / "journal_errors.log"
LEGACY_PROGRESS_FILE = LEGACY_LOG_DIR / "journal_progress.json"

# ============ 全局变量 ============
headers = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json"
}


def _parse_int(value: Any, *, default: int, minimum: int = 1) -> int:
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return default
    return parsed


def _parse_float(value: Any, *, default: float, minimum: float = 0.0) -> float:
    if value is None:
        return default
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    if parsed < minimum:
        return default
    return parsed


def _load_runtime_config(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env_vars = env if env is not None else os.environ
    return {
        "request_interval": _parse_float(env_vars.get(ENV_REQUEST_INTERVAL), default=DEFAULT_REQUEST_INTERVAL, minimum=0.0),
        "request_timeout": _parse_float(env_vars.get(ENV_REQUEST_TIMEOUT), default=DEFAULT_REQUEST_TIMEOUT, minimum=0.1),
        "max_retries": _parse_int(env_vars.get(ENV_MAX_RETRIES), default=DEFAULT_MAX_RETRIES, minimum=0),
        "rate_limit_wait_seconds": _parse_float(
            env_vars.get(ENV_RATE_LIMIT_WAIT_SECONDS),
            default=DEFAULT_RATE_LIMIT_WAIT_SECONDS,
            minimum=0.0,
        ),
        "insert_flush_rows": _parse_int(env_vars.get(ENV_INSERT_FLUSH_ROWS), default=DEFAULT_INSERT_FLUSH_ROWS, minimum=1),
    }


_RUNTIME_CONFIG = _load_runtime_config()
REQUEST_INTERVAL = _RUNTIME_CONFIG["request_interval"]
REQUEST_TIMEOUT = _RUNTIME_CONFIG["request_timeout"]
MAX_RETRIES = _RUNTIME_CONFIG["max_retries"]
RATE_LIMIT_WAIT_SECONDS = _RUNTIME_CONFIG["rate_limit_wait_seconds"]
INSERT_FLUSH_ROWS = _RUNTIME_CONFIG["insert_flush_rows"]


def _new_session() -> requests.Session:
    new = requests.Session()
    new.headers.update(headers)
    return new


def _reset_session() -> requests.Session:
    global session
    session = _new_session()
    return session


session = _new_session()


# ============ 工具函数 ============

def setup_directories():
    """创建必要的目录"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _format_exception(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        message = "<empty>"
    return f"class={exc.__class__.__name__} message={message} repr={repr(exc)}"


def log_message(message: str, level: str = "INFO"):
    """记录日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}\n"

    print(log_line.strip())

    # 主日志
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line)

    # 错误日志
    if level in ["ERROR", "WARNING"]:
        with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line)


def make_request(url: str, params: dict) -> Tuple[Optional[dict], Optional[str]]:
    """发送 HTTP 请求，带有重试机制。"""
    for retry_count in range(MAX_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

            if response.status_code == 429:
                wait_seconds = RATE_LIMIT_WAIT_SECONDS
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_seconds = max(1, int(retry_after))
                    except (TypeError, ValueError):
                        wait_seconds = RATE_LIMIT_WAIT_SECONDS
                log_message(f"速率限制，暂停{wait_seconds}秒", "WARNING")
                if retry_count >= MAX_RETRIES:
                    log_message("速率限制重试次数已用尽，放弃本次请求", "ERROR")
                    return None, "http_429_exhausted"
                time.sleep(wait_seconds)
                continue

            if response.status_code == 400:
                # 语义学术搜索常见：offset 到达上限会直接 400，这不是瞬时错误，没必要重试。
                log_message(f"请求失败: HTTP 400 ({response.text[:120]})", "WARNING")
                return None, "http_400"

            if 500 <= response.status_code < 600:
                if retry_count >= MAX_RETRIES:
                    log_message(f"请求失败: HTTP {response.status_code}", "ERROR")
                    return None, "http_5xx_exhausted"
                wait_time = (2 ** retry_count) * 2
                log_message(f"服务器错误: HTTP {response.status_code}，重试中", "WARNING")
                time.sleep(wait_time)
                continue

            if response.status_code != 200:
                if retry_count >= MAX_RETRIES:
                    log_message(f"请求失败: HTTP {response.status_code}", "ERROR")
                    return None, f"http_{response.status_code}"
                wait_time = (2 ** retry_count) * 2
                time.sleep(wait_time)
                continue

            return response.json(), None

        except requests.exceptions.Timeout as e:
            _reset_session()
            log_message(f"请求超时: {_format_exception(e)}", "WARNING")
            if retry_count >= MAX_RETRIES:
                return None, "timeout"
            time.sleep(5)
            continue
        except requests.exceptions.RequestException as e:
            _reset_session()
            log_message(f"请求异常: {_format_exception(e)}", "WARNING")
            if retry_count >= MAX_RETRIES:
                return None, "network_error"
            time.sleep(5)
            continue
        except Exception as e:
            _reset_session()
            log_message(f"请求异常: {_format_exception(e)}", "ERROR")
            if retry_count >= MAX_RETRIES:
                return None, "exception"
            time.sleep(5)
            continue

    return None, "unknown"


def should_stop_for_offset(page_index: int, page_size: int) -> bool:
    """检查是否超过 API 可接受的 offset 范围。"""
    offset = page_index * page_size
    return offset >= MAX_OFFSET_EXCLUSIVE


def flush_buffered_rows(
    ch_client,
    buffered_rows: List[Dict[str, Any]],
    buffered_papers: int,
    journal_name: str
) -> Tuple[bool, int, int]:
    """将缓冲区数据写入数据库。"""
    if not buffered_rows:
        return True, 0, 0

    if batch_insert_clickhouse(ch_client, buffered_rows):
        log_message(f"  💾 批量写入: {journal_name} | 论文{buffered_papers}篇 | {len(buffered_rows)}行")
        return True, buffered_papers, len(buffered_rows)

    log_message(f"  ❌ 批量写入失败: {journal_name} | 论文{buffered_papers}篇 | {len(buffered_rows)}行", "ERROR")
    return False, 0, 0


# ============ ClickHouse 函数 ============

def create_clickhouse_client():
    """创建ClickHouse客户端"""
    try:
        client = clickhouse_connect.get_client(
            host=CH_HOST, port=CH_PORT, username=CH_USERNAME,
            password=CH_PASSWORD, database=CH_DATABASE
        )
        log_message("ClickHouse连接成功")
        return client
    except Exception as e:
        log_message(f"ClickHouse连接失败: {e}", "ERROR")
        return None


def batch_insert_clickhouse(client, rows: List[Dict[str, Any]]) -> bool:
    """批量插入数据到ClickHouse（带去重）"""
    if not rows:
        return True

    try:
        cleaned_rows = []
        for row in rows:
            cleaned_row = {}
            for key, value in row.items():
                if value is None:
                    if key in ['rank', 'citation_count', 'year']:
                        cleaned_row[key] = 0
                    elif key in ['import_date', 'import_time']:
                        from datetime import datetime
                        if key == 'import_date':
                            cleaned_row[key] = datetime.now().date()
                        else:
                            cleaned_row[key] = datetime.now()
                    else:
                        cleaned_row[key] = ''
                elif key in ['rank', 'citation_count', 'year']:
                    try:
                        num_value = int(value)
                        if key == 'rank':
                            cleaned_row[key] = min(255, max(0, num_value))
                        elif key == 'citation_count':
                            cleaned_row[key] = min(4294967295, max(0, num_value))
                        elif key == 'year':
                            cleaned_row[key] = min(65535, max(0, num_value))
                        else:
                            cleaned_row[key] = num_value
                    except (ValueError, TypeError):
                        cleaned_row[key] = 0
                elif key in ['import_date', 'import_time']:
                    cleaned_row[key] = value
                else:
                    cleaned_row[key] = str(value) if value is not None else ''
            cleaned_rows.append(cleaned_row)

        df = pd.DataFrame(cleaned_rows)
        df['rank'] = df['rank'].astype('uint8')
        df['citation_count'] = df['citation_count'].astype('uint32')
        df['year'] = df['year'].astype('uint16')

        # 使用临时表进行去重
        temp_table = 'temp_insert_dedup'
        client.command(f'DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}')
        client.command(f'''
            CREATE TABLE {CH_DATABASE}.{temp_table} AS {CH_DATABASE}.{CH_TABLE}
            ENGINE = Memory
        ''')
        client.insert_df(f'{CH_DATABASE}.{temp_table}', df)
        client.command(f'''
            INSERT INTO {CH_DATABASE}.{CH_TABLE}
            SELECT DISTINCT * FROM {CH_DATABASE}.{temp_table}
        ''')
        client.command(f'DROP TABLE {CH_DATABASE}.{temp_table}')

        return True

    except Exception as e:
        log_message(f"插入失败: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return False


def paper_to_rows(paper: dict) -> List[Dict[str, Any]]:
    """将论文数据转换为数据库行"""
    rows = []

    uid = paper.get("paperId", "")
    title = paper.get("title", "")
    year = paper.get("year", 0)
    pub_date = paper.get("publicationDate", "")
    venue = paper.get("venue", "")
    citation_count = paper.get("citationCount", 0)
    url = paper.get("url", "")
    abstract = paper.get("abstract", "")

    journal_obj = paper.get("journal")
    journal_name = journal_obj.get("name", "") if journal_obj else venue

    external_ids = paper.get("externalIds", {})
    doi = external_ids.get("DOI", "")
    arxiv_id = external_ids.get("ArXiv", "")
    pubmed_id = external_ids.get("PubMed", "")

    authors = paper.get("authors", [])

    from datetime import datetime
    import_date = datetime.now().date()
    import_time = datetime.now()

    if not authors:
        rows.append({
            "author_id": "", "author": "", "uid": uid, "doi": doi, "title": title,
            "rank": 0, "journal": venue, "citation_count": citation_count, "tag": "其他",
            "state": "fetched", "institution_id": "", "institution_name": "",
            "institution_country": "", "institution_type": "", "raw_affiliation": "",
            "year": year, "publication_date": pub_date, "venue": venue, "journal_name": journal_name,
            "arxiv_id": arxiv_id, "pubmed_id": pubmed_id, "url": url, "abstract": abstract,
            "import_date": import_date, "import_time": import_time
        })
    else:
        total_authors = len(authors)
        for rank, author in enumerate(authors, 1):
            tag = "第一作者" if rank == 1 else ("最后作者" if rank == total_authors else "其他")
            rows.append({
                "author_id": author.get("authorId", ""), "author": author.get("name", ""),
                "uid": uid, "doi": doi, "title": title, "rank": rank, "journal": venue,
                "citation_count": citation_count, "tag": tag, "state": "fetched",
                "institution_id": "", "institution_name": "", "institution_country": "",
                "institution_type": "", "raw_affiliation": "", "year": year,
                "publication_date": pub_date, "venue": venue, "journal_name": journal_name,
                "arxiv_id": arxiv_id, "pubmed_id": pubmed_id, "url": url, "abstract": abstract,
                "import_date": import_date, "import_time": import_time
            })

    return rows


# ============ 进度管理函数 ============

def load_progress() -> dict:
    """加载进度文件"""
    progress_file = PROGRESS_FILE
    if not progress_file.exists() and LEGACY_PROGRESS_FILE.exists():
        progress_file = LEGACY_PROGRESS_FILE
    if progress_file.exists():
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            log_message("进度文件损坏，将创建新文件", "WARNING")
            return get_empty_progress()
    return get_empty_progress()


def get_empty_progress() -> dict:
    """返回空的进度结构"""
    return {
        "csv_file": str(CSV_PATH.name),
        "csv_loaded_at": None,
        "total_journals": 0,
        "journals": {},
        "last_update": None
    }


def save_progress(progress_data: dict):
    """保存进度文件"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    progress_data['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)


def update_journal_progress(progress_data: dict, journal_name: str,
                           status: str, **kwargs) -> dict:
    """更新单个期刊的进度"""
    if journal_name not in progress_data["journals"]:
        progress_data["journals"][journal_name] = {
            "query_type": None,
            "status": "pending",
            "total_pages": None,
            "current_page": 0,
            "papers_fetched": 0,
            "last_updated": None
        }

    progress_data["journals"][journal_name]["status"] = status
    progress_data["journals"][journal_name]["last_updated"] = \
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for key, value in kwargs.items():
        progress_data["journals"][journal_name][key] = value

    return progress_data


RETRYABLE_REQUEST_ERRORS = {"timeout", "network_error", "http_429_exhausted", "http_5xx_exhausted"}


def is_retryable_request_error(last_error: Optional[str]) -> bool:
    return (last_error in RETRYABLE_REQUEST_ERRORS)


def is_legacy_retryable_failed_journal(existing: Dict[str, Any]) -> bool:
    """旧版本中失败但未触发可重试错误且未采集任何数据的期刊，允许重试。"""
    return (
        existing.get("status") == "failed" and
        not is_retryable_request_error(existing.get("last_error")) and
        existing.get("total_pages", 0) == 0 and
        existing.get("current_page", 0) == 0 and
        existing.get("papers_fetched", 0) == 0
    )

# ============ CSV 加载函数 ============

def load_journals_from_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """从CSV文件加载期刊列表"""
    log_message(f"加载CSV文件: {csv_path}")

    if not csv_path.exists():
        log_message(f"CSV文件不存在: {csv_path}", "ERROR")
        raise FileNotFoundError(f"CSV文件不存在: {csv_path}")

    try:
        # 尝试不同编码
        df = None
        for encoding in [CSV_ENCODING, "utf-8", "gbk", "latin-1"]:
            try:
                df = pd.read_csv(csv_path, encoding=encoding)
                log_message(f"成功使用编码: {encoding}")
                break
            except UnicodeDecodeError:
                continue

        if df is None:
            log_message("无法读取CSV文件，尝试了所有编码", "ERROR")
            raise ValueError("CSV编码错误")

        # 检查Journal列是否存在
        if "Journal" not in df.columns:
            log_message(f"CSV文件缺少Journal列，可用列: {list(df.columns)}", "ERROR")
            raise ValueError("CSV缺少Journal列")

        # 提取期刊列表
        journals = []
        seen_names = set()

        for idx, row in df.iterrows():
            journal_name = row.get("Journal", "")

            # 跳过空值
            if pd.isna(journal_name) or not str(journal_name).strip():
                continue

            journal_name = str(journal_name).strip()

            # 去重
            if journal_name not in seen_names:
                seen_names.add(journal_name)
                journals.append({
                    "name": journal_name,
                    "original_name": journal_name,
                    "row_number": idx + 2  # +2 because of 0-index and header row
                })

        log_message(f"发现 {len(journals)} 个唯一期刊")
        return journals

    except Exception as e:
        log_message(f"加载CSV失败: {e}", "ERROR")
        raise


# ============ 期刊验证函数 ============

def validate_journal(journal_name: str) -> Dict[str, Any]:
    """验证单个期刊是否可用

    Returns:
        dict: {
            "query_type": "venue" | "query" | None,
            "valid": True | False,
            "error": str | None
        }
    """
    log_message(f"验证期刊: {journal_name}")

    # 先尝试 venue 查询
    params = {
        "venue": journal_name,
        "limit": 1,
        "fields": "paperId"
    }

    for retry in range(MAX_RETRIES):
        data, _ = make_request(f"{BASE_URL}/paper/search", params)

        if data is None:
            log_message(f"  venue查询失败 (重试 {retry+1}/{MAX_RETRIES})", "WARNING")
            time.sleep(REQUEST_INTERVAL)
            continue

        papers = data.get("data", [])
        if papers:
            log_message(f"  ✓ 期刊有效 (venue查询)")
            return {"query_type": "venue", "valid": True, "error": None}
        else:
            break

    # venue 无结果，尝试 query 查询
    log_message(f"  venue无结果，尝试query查询")
    params = {
        "query": journal_name,
        "limit": 1,
        "fields": "paperId"
    }

    for retry in range(MAX_RETRIES):
        data, _ = make_request(f"{BASE_URL}/paper/search", params)

        if data is None:
            log_message(f"  query查询失败 (重试 {retry+1}/{MAX_RETRIES})", "WARNING")
            time.sleep(REQUEST_INTERVAL)
            continue

        papers = data.get("data", [])
        if papers:
            log_message(f"  ✓ 期刊有效 (query查询)")
            return {"query_type": "query", "valid": True, "error": None}
        else:
            break

    # 都无效
    log_message(f"  ✗ 期刊无效", "WARNING")
    return {"query_type": None, "valid": False, "error": "No results found"}


def batch_validate_journals(journal_list: List[Dict[str, Any]],
                           progress_data: dict) -> Dict[str, Dict[str, Any]]:
    """批量验证期刊（跳过API验证，直接标记为有效）

    Returns:
        dict: {journal_name: {"query_type": str, "status": str}}
    """
    log_message("跳过验证，直接标记所有期刊为有效")
    print("\n📋 标记期刊为有效...")

    validated = {}

    with tqdm(total=len(journal_list), desc="   进度",
              unit="期刊", ncols=80) as pbar:
        for journal_info in journal_list:
            journal_name = journal_info["name"]

            # 检查是否已验证
            if journal_name in progress_data["journals"]:
                existing = progress_data["journals"][journal_name]
                validated[journal_name] = {
                    "query_type": existing.get("query_type", "query"),
                    "status": existing["status"]
                }
                pbar.update(1)
                continue

            # 跳过验证，直接标记为有效，使用 query 方式
            validated[journal_name] = {
                "query_type": "query",
                "status": "valid"
            }
            update_journal_progress(
                progress_data, journal_name,
                status="valid",
                query_type="query"
            )

            pbar.update(1)

    print(f"   有效: {len(validated)} 个 | 无效: 0 个")
    log_message(f"标记完成: {len(validated)} 个期刊全部标记为有效")

    return validated

# ============ 论文获取函数 ============


# ============ 论文获取函数 ============

def fetch_papers_by_journal(journal_name: str, query_type: str,
                           start_page: int, progress_data: dict,
                           ch_client) -> Tuple[int, int]:
    """获取指定期刊的所有论文

    Args:
        journal_name: 期刊名称
        query_type: 查询类型 ("venue" or "query")
        start_page: 起始页码
        progress_data: 进度数据
        ch_client: ClickHouse客户端

    Returns:
        tuple: (论文数, 行数)
    """
    log_message(f"开始获取期刊: {journal_name} (从第{start_page}页开始)")

    seen_paper_ids = set()
    total_papers = 0
    total_rows = 0
    current_page = start_page
    pages_since_progress_save = 0
    terminated_by_error = False
    stop_reason = "completed"
    buffered_rows: List[Dict[str, Any]] = []
    buffered_papers = 0

    while True:
        # 检查页数限制
        if MAX_PAGES_PER_JOURNAL and current_page >= MAX_PAGES_PER_JOURNAL:
            log_message(f"  达到最大页数限制: {MAX_PAGES_PER_JOURNAL}")
            stop_reason = "max_pages_limit"
            break

        # 检查 API offset 限制
        if should_stop_for_offset(current_page, PAPERS_PER_REQUEST):
            log_message(f"  达到API offset上限: offset={current_page * PAPERS_PER_REQUEST}")
            stop_reason = "api_offset_limit"
            break

        # 构建请求参数
        if query_type == "venue":
            params = {
                "venue": journal_name,
                "limit": PAPERS_PER_REQUEST,
                "offset": current_page * PAPERS_PER_REQUEST,
                "fields": FIELDS
            }
        else:  # query
            params = {
                "query": journal_name,
                "limit": PAPERS_PER_REQUEST,
                "offset": current_page * PAPERS_PER_REQUEST,
                "fields": FIELDS
            }

        # 发送请求
        data, request_error = make_request(f"{BASE_URL}/paper/search", params)

        if data is None:
            already_fetched = progress_data["journals"][journal_name].get("papers_fetched", 0) > 0
            hit_offset_boundary = request_error == "http_400" and (
                current_page > start_page or buffered_papers > 0 or already_fetched
            )
            if hit_offset_boundary:
                log_message(f"  第{current_page}页触发offset边界，结束当前期刊抓取")
                stop_reason = "offset_boundary_400"
                break
            request_error_code = request_error or "request_failed"
            log_message(f"  第{current_page}页请求失败: {request_error_code}", "WARNING")
            terminated_by_error = True
            stop_reason = request_error_code
            break

        papers = data.get("data", [])

        if not papers:
            log_message(f"  第{current_page}页无数据，获取完成")
            stop_reason = "empty_page"
            break

        # 过滤并收集论文
        page_papers = []
        for paper in papers:
            paper_id = paper.get("paperId", "")
            arxiv_id = paper.get("externalIds", {}).get("ArXiv", "")

            # 过滤arxiv（与原逻辑一致）
            if not arxiv_id and paper_id and paper_id not in seen_paper_ids:
                seen_paper_ids.add(paper_id)
                page_papers.append(paper)

        if not page_papers:
            log_message(f"  第{current_page}页无有效论文，获取完成")
            stop_reason = "no_valid_papers"
            break

        # 缓冲页面数据
        rows = []
        for paper in page_papers:
            rows.extend(paper_to_rows(paper))

        if not rows:
            log_message(f"  第{current_page}页无可写入行，跳过")
            current_page += 1
            time.sleep(REQUEST_INTERVAL)
            continue

        buffered_rows.extend(rows)
        buffered_papers += len(page_papers)
        log_message(f"  第{current_page}页: 获取{len(page_papers)}篇论文, 缓冲累计 {buffered_papers}篇/{len(buffered_rows)}行")

        # 达到阈值后统一写入
        if len(buffered_rows) >= INSERT_FLUSH_ROWS:
            success, flushed_papers, flushed_rows = flush_buffered_rows(
                ch_client, buffered_rows, buffered_papers, journal_name
            )
            if not success:
                terminated_by_error = True
                stop_reason = "insert_failed"
                break

            total_papers += flushed_papers
            total_rows += flushed_rows
            update_journal_progress(
                progress_data, journal_name,
                status="in_progress",
                current_page=current_page + 1,
                papers_fetched=progress_data["journals"][journal_name]["papers_fetched"] + flushed_papers,
                last_error=None,
                last_error_at=None,
            )
            pages_since_progress_save += 1
            if pages_since_progress_save >= PROGRESS_SAVE_EVERY_PAGES:
                save_progress(progress_data)
                pages_since_progress_save = 0
            buffered_rows = []
            buffered_papers = 0

        current_page += 1
        time.sleep(REQUEST_INTERVAL)

    # 循环结束后，写入剩余缓冲数据
    if not terminated_by_error and buffered_rows:
        success, flushed_papers, flushed_rows = flush_buffered_rows(
            ch_client, buffered_rows, buffered_papers, journal_name
        )
        if not success:
            terminated_by_error = True
            stop_reason = "insert_failed"
        else:
            total_papers += flushed_papers
            total_rows += flushed_rows
            update_journal_progress(
                progress_data, journal_name,
                status="in_progress",
                current_page=current_page,
                papers_fetched=progress_data["journals"][journal_name]["papers_fetched"] + flushed_papers,
                last_error=None,
                last_error_at=None,
            )

    # 标记状态
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if terminated_by_error:
        papers_fetched = (
            progress_data["journals"][journal_name].get("papers_fetched", 0)
            + total_papers + buffered_papers
        )
        if is_retryable_request_error(stop_reason):
            resumed_status = "valid" if papers_fetched == 0 else "in_progress"
            final_status = resumed_status
            update_journal_progress(
                progress_data, journal_name,
                status=resumed_status,
                total_pages=current_page,
                current_page=current_page,
                last_error=stop_reason,
                last_error_at=now,
            )
        else:
            final_status = "failed"
            update_journal_progress(
                progress_data, journal_name,
                status="failed",
                total_pages=current_page,
                last_error=stop_reason,
                last_error_at=now,
            )
    else:
        final_status = "completed"
        update_journal_progress(
            progress_data, journal_name,
            status="completed",
            total_pages=current_page,
            last_error=None,
            last_error_at=None,
        )
    save_progress(progress_data)

    log_message(f"✓ {journal_name}: {final_status} | 论文{total_papers}篇 | 页数{current_page - start_page} | 原因={stop_reason}")
    return total_papers, total_rows


# ============ 主执行函数 ============


def execute_journal_fetching(validated_journals: Dict[str, Dict[str, Any]],
                            progress_data: dict,
                            ch_client) -> Tuple[int, int]:
    """执行论文获取主流程

    Args:
        validated_journals: 验证通过的期刊字典
        progress_data: 进度数据
        ch_client: ClickHouse客户端

    Returns:
        tuple: (总论文数, 总行数)
    """
    log_message("开始获取论文")
    print("\n📥 获取论文...")

    total_papers = 0
    total_rows = 0

    def should_fetch_journal(name: str, journal_info: Dict[str, Any]) -> bool:
        status = journal_info.get("status")
        if status in ["valid", "in_progress"]:
            return True
        if status == "failed":
            existing = progress_data["journals"].get(name)
            if not existing:
                return False
            return (
                is_retryable_request_error(existing.get("last_error")) or
                is_legacy_retryable_failed_journal(existing)
            )
        return False

    # 统计各状态
    status_count = {
        "completed": len([j for j in progress_data["journals"].values()
                         if j["status"] == "completed"]),
        "in_progress": 0,
        "pending": 0
    }

    # 待处理的期刊
    pending_journals = [
        (name, info) for name, info in validated_journals.items()
        if should_fetch_journal(name, info)
    ]

    with tqdm(total=len(pending_journals), desc="   进度",
              unit="期刊", ncols=80) as pbar:
        for journal_name, journal_info in pending_journals:
            # 检查状态
            if journal_name in progress_data["journals"]:
                existing = progress_data["journals"][journal_name]
                if existing["status"] == "in_progress":
                    start_page = existing.get("current_page", 0)
                    status_count["in_progress"] += 1
                elif existing["status"] == "failed" and is_retryable_request_error(existing.get("last_error")):
                    start_page = existing.get("current_page", 0)
                    if existing.get("papers_fetched", 0) > 0:
                        status_count["in_progress"] += 1
                    else:
                        status_count["pending"] += 1
                else:
                    start_page = 0
                    status_count["pending"] += 1
            else:
                start_page = 0
                status_count["pending"] += 1

            # 获取论文
            query_type = journal_info.get("query_type", "venue")
            papers, rows = fetch_papers_by_journal(
                journal_name, query_type, start_page,
                progress_data, ch_client
            )

            total_papers += papers
            total_rows += rows

            pbar.update(1)
            pbar.set_postfix_str(f"已完成:{status_count['completed']} 进行中:{status_count['in_progress']}")

    print(f"\n✅ 获取完成")
    log_message(f"获取完成: {total_papers}篇论文, {total_rows}行")

    return total_papers, total_rows


def main():
    """主函数"""
    print("=" * 60)
    print("Semantic Scholar 期刊表论文获取器")
    print("=" * 60)
    print(f"CSV 文件: {CSV_PATH}")
    print(f"查询策略: venue → query")
    print(f"时间范围: 所有年份")
    print(f"请求间隔: {REQUEST_INTERVAL}秒")
    print("=" * 60)

    start_time = time.time()

    # 创建必要的目录
    setup_directories()

    # 加载进度
    progress = load_progress()

    # 创建ClickHouse客户端
    ch_client = create_clickhouse_client()
    if not ch_client:
        log_message("ClickHouse连接失败，程序退出", "ERROR")
        return

    # 1. 加载期刊列表
    print("\n📊 加载期刊列表...")
    try:
        journal_list = load_journals_from_csv(CSV_PATH)
        progress["total_journals"] = len(journal_list)
        progress["csv_loaded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_progress(progress)

        print(f"   总计: {len(journal_list)} 个期刊")
    except Exception as e:
        log_message(f"加载期刊列表失败: {e}", "ERROR")
        return

    # 2. 批量验证
    validated_journals = batch_validate_journals(journal_list, progress)

    if not validated_journals:
        log_message("没有有效的期刊，程序退出", "WARNING")
        return

    # 3. 获取论文
    total_papers, total_rows = execute_journal_fetching(
        validated_journals, progress, ch_client
    )

    # 总结
    elapsed_time = time.time() - start_time

    log_message("=" * 60)
    log_message("✅ 全部完成")
    log_message(f"📊 统计:")
    log_message(f"   总期刊: {progress['total_journals']} 个")
    log_message(f"   有效: {len(validated_journals)} 个")
    log_message(f"   失败: {progress['total_journals'] - len(validated_journals)} 个")
    log_message(f"   总论文: {total_papers:,} 篇")
    log_message(f"   总行数: {total_rows:,} 行")
    log_message(f"⏱️  总耗时: {elapsed_time:.1f} 秒 ({elapsed_time/60:.1f} 分钟)")
    log_message("=" * 60)

    print("\n" + "=" * 60)
    print("✅ 全部完成")
    print(f"📊 总期刊: {progress['total_journals']} 个 | "
          f"有效: {len(validated_journals)} 个 | "
          f"失败: {progress['total_journals'] - len(validated_journals)} 个")
    print(f"📄 总论文: {total_papers:,} 篇 | 总行数: {total_rows:,} 行")
    print(f"⏱️  总耗时: {elapsed_time:.1f} 秒 ({elapsed_time/60:.1f} 分钟)")
    print("=" * 60)


if __name__ == "__main__":
    main()
