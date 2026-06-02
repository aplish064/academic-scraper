#!/usr/bin/env python3
"""
arXiv Paper Fetcher - 单线程同步架构
从 2026-04-22 往前获取到 1990 年的所有论文
"""

import requests
import json
import time
import gc
import os
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Set
import feedparser
import clickhouse_connect
from tqdm import tqdm

# =============================================================================
# 配置参数
# =============================================================================

# API 配置
ARXIV_API_BASE = "https://export.arxiv.org/api/query"
REQUEST_INTERVAL = 1.0        # 请求间隔（秒）
REQUEST_TIMEOUT = 30          # 请求超时（秒）
MAX_RETRIES = 3               # 最大重试次数
PER_PAGE = 3000              # 每页论文数
RATE_LIMIT_WAIT = 60          # 速率限制等待时间（秒）
TIMEOUT_RETRY_WAIT = 5        # 超时重试等待时间（秒）
DEFAULT_CONTACT_EMAIL = "academic-scraper@localhost"
RECOVERY_BASE_WAIT = 300      # 恢复重试基础等待（秒）
RECOVERY_MAX_WAIT = 3600      # 恢复重试最大等待（秒）
RECOVERY_MAX_ATTEMPTS = 12    # 恢复重试最大次数
PROBE_TIMEOUT = 15            # 可用性探测超时（秒）
PROBE_QUERY = "all:electron"
DATE_QUERY_FIELD_DEFAULT = "submittedDate"  # 按“当天发表/提交”抓取默认口径
DAILY_DAEMON_DEFAULT_RUN_AT = "00:00"
DAILY_DAEMON_DEFAULT_CHECK_DAYS = 30

# 时间范围配置
START_DATE = "2026-04-22"     # 开始日期
END_YEAR = 1990               # 结束年份

# ClickHouse 配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'arxiv'
CH_USERNAME = 'default'
CH_PASSWORD = ''

# 批量插入配置
BATCH_WRITE_THRESHOLD = 10000  # 每 10000 行写入一次
ARXIV_TABLE_COLUMNS = [
    'arxiv_id', 'uid', 'title', 'published', 'updated', 'categories', 'primary_category',
    'journal_ref', 'comment', 'url', 'pdf_url', 'author', 'rank', 'tag', 'affiliation', 'import_date'
]
# 去重键：使用业务内容字段，不包含 import_date
DEDUP_KEY_COLUMNS = [column for column in ARXIV_TABLE_COLUMNS if column != 'import_date']

# 文件路径配置
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()
LOG_DIR = PROJECT_ROOT / "log" / "papers" / "arxiv"
LEGACY_LOG_DIR = PROJECT_ROOT / "log"
PROGRESS_FILE = LOG_DIR / "arxiv_fetch_progress.json"
LOG_FILE = LOG_DIR / "arxiv_fetch.log"
ERROR_LOG_FILE = LOG_DIR / "arxiv_errors.log"
LEGACY_PROGRESS_FILE = LEGACY_LOG_DIR / "arxiv_fetch_progress.json"

# 日志配置
LOG_BUFFER_SIZE = 100         # 日志缓冲大小

# 全局变量
log_buffer = []

# =============================================================================
# 日志系统
# =============================================================================

def setup_logging():
    """创建日志目录和初始化日志系统"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 配置 logging 模块
    logger = logging.getLogger('arxiv_fetcher')
    logger.setLevel(logging.INFO)

    # Main log handler
    main_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    main_handler.setLevel(logging.INFO)
    main_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
    main_handler.setFormatter(main_formatter)
    logger.addHandler(main_handler)

    # Error log handler
    error_handler = logging.FileHandler(ERROR_LOG_FILE, encoding='utf-8')
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(main_formatter)
    logger.addHandler(error_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


def log_message(message: str, level: str = "INFO"):
    """记录日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}\n"

    # 添加到缓冲区
    log_buffer.append(log_line)

    # 缓冲区满了就写入文件
    if len(log_buffer) >= LOG_BUFFER_SIZE:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.writelines(log_buffer)
        log_buffer.clear()

    # 同时输出到控制台
    print(log_line.strip())


def flush_log_buffer():
    """刷新日志缓冲区到文件"""
    if log_buffer:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.writelines(log_buffer)
        log_buffer.clear()

# =============================================================================
# 进度管理
# =============================================================================

def load_progress() -> Dict[str, Any]:
    """加载进度文件"""
    progress_file = PROGRESS_FILE
    if not progress_file.exists() and LEGACY_PROGRESS_FILE.exists():
        progress_file = LEGACY_PROGRESS_FILE
    if progress_file.exists():
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            log_message("进度文件损坏，创建新文件", "WARNING")
            return get_empty_progress()
        except Exception as e:
            log_message(f"加载进度文件失败: {e}", "ERROR")
            return get_empty_progress()
    return get_empty_progress()


def get_empty_progress() -> Dict[str, Any]:
    """返回空的进度结构"""
    return {
        "start_date": START_DATE,
        "end_year": END_YEAR,
        "total_dates": 0,
        "completed_dates": [],
        "last_updated": None
    }


def save_progress(progress: Dict[str, Any]):
    """保存进度文件"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        progress['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)

    except Exception as e:
        log_message(f"保存进度文件失败: {e}", "ERROR")


def date_to_key(date_str: str) -> str:
    """将日期字符串转换为进度文件键 (YYYYMMDD)"""
    return date_str.replace('-', '')


def key_to_date(key: str) -> str:
    """将进度文件键转换为日期字符串 (YYYY-MM-DD)"""
    return f"{key[:4]}-{key[4:6]}-{key[6:]}"


def get_yesterday_date(reference_datetime: Optional[datetime] = None) -> str:
    """获取参考时间的前一天（YYYY-MM-DD）"""
    reference = reference_datetime or datetime.now()
    return (reference - timedelta(days=1)).strftime('%Y-%m-%d')


def strip_arxiv_version_suffix(arxiv_id: str) -> str:
    """将 arXiv ID 的版本后缀去掉（例如 2401.0001v2 -> 2401.0001）"""
    return re.sub(r"v\d+$", "", arxiv_id or "")


def build_daily_check_dates(yesterday: str, check_days: int) -> List[str]:
    """生成昨日往前若干天的日期列表（倒序），不含昨日"""
    if check_days <= 0:
        return []

    current = datetime.strptime(yesterday, '%Y-%m-%d') - timedelta(days=1)
    dates = []
    for _ in range(check_days):
        dates.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)
    return dates


def dedupe_date_sequence(dates: List[str]) -> List[str]:
    """去重并保持顺序"""
    seen: Set[str] = set()
    output: List[str] = []
    for date_str in dates:
        if date_str not in seen:
            seen.add(date_str)
            output.append(date_str)
    return output


def build_date_query(date_str: str, date_field: str = DATE_QUERY_FIELD_DEFAULT) -> str:
    """构建按天查询条件（含整天分钟边界）"""
    date_key = date_to_key(date_str)
    return f"{date_field}:[{date_key}0000 TO {date_key}2359]"


def build_last_updated_date_query(date_str: str) -> str:
    """兼容旧调用：构建按天查询的 lastUpdatedDate 条件"""
    return build_date_query(date_str, "lastUpdatedDate")


def get_dates_in_window(date_a: str, date_b: str) -> List[str]:
    """生成 [min(date_a,date_b), max(date_a,date_b)] 的倒序日期列表（含端点）"""
    dt_a = datetime.strptime(date_a, '%Y-%m-%d')
    dt_b = datetime.strptime(date_b, '%Y-%m-%d')

    newer = max(dt_a, dt_b)
    older = min(dt_a, dt_b)

    dates = []
    current = newer
    while current >= older:
        dates.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)
    return dates


def resolve_fetch_options(
    per_page: Optional[int] = None,
    request_interval: Optional[float] = None
) -> tuple:
    """规范化分页和请求间隔参数"""
    per_page_value = per_page if per_page and per_page > 0 else PER_PAGE
    interval_value = request_interval if request_interval is not None and request_interval >= 0 else REQUEST_INTERVAL
    return per_page_value, interval_value


def mark_date_completed(progress_data: dict, date_key: str):
    """标记日期已完成并落盘"""
    if date_key not in progress_data['completed_dates']:
        progress_data['completed_dates'].append(date_key)
    save_progress(progress_data)


def compute_recovery_wait_seconds(attempt: int, base_wait: int = RECOVERY_BASE_WAIT, max_wait: int = RECOVERY_MAX_WAIT) -> int:
    """指数退避 + 抖动，计算下一次恢复重试等待秒数"""
    raw_wait = min(base_wait * (2 ** attempt), max_wait)
    jitter_multiplier = random.uniform(0.8, 1.2)
    return max(1, min(int(raw_wait * jitter_multiplier), max_wait))


def build_request_headers() -> Dict[str, str]:
    """构建请求头，满足 arXiv API 客户端标识要求"""
    contact_email = os.getenv("ARXIV_CONTACT_EMAIL", DEFAULT_CONTACT_EMAIL).strip() or DEFAULT_CONTACT_EMAIL
    user_agent = f"academic-scraper/1.0 (mailto:{contact_email})"
    return {
        "User-Agent": user_agent,
        "Accept": "application/atom+xml",
    }


def build_dedup_insert_sql(temp_table: str) -> str:
    """构建去重写入 SQL：与目标表反连接，仅插入新记录。"""
    select_columns = ', '.join([f"tmp.{column}" for column in ARXIV_TABLE_COLUMNS])
    join_condition = ' AND '.join([f"tmp.{column} = tgt.{column}" for column in DEDUP_KEY_COLUMNS])
    return f"""
        INSERT INTO {CH_DATABASE}.{CH_TABLE}
        SELECT {select_columns}
        FROM {CH_DATABASE}.{temp_table} tmp
        LEFT ANTI JOIN {CH_DATABASE}.{CH_TABLE} tgt
        ON {join_condition}
    """


def check_arxiv_api_available() -> tuple:
    """轻量探测 arXiv API 可用性，返回 (is_available, retry_after_seconds|None)"""
    try:
        response = requests.get(
            ARXIV_API_BASE,
            params={"search_query": PROBE_QUERY, "start": 0, "max_results": 1},
            timeout=PROBE_TIMEOUT,
            headers=build_request_headers()
        )
        if response.status_code == 200:
            return True, None

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                retry_seconds = int(retry_after) if retry_after else RATE_LIMIT_WAIT
            except (TypeError, ValueError):
                retry_seconds = RATE_LIMIT_WAIT
            return False, max(1, retry_seconds)

        return False, None
    except Exception:
        return False, None


def parse_total_results(xml_data: str) -> Optional[int]:
    """从 arXiv Atom XML 中解析 opensearch:totalResults。"""
    if not xml_data:
        return None
    try:
        feed = feedparser.parse(xml_data)
        value = getattr(getattr(feed, "feed", None), "opensearch_totalresults", None)
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def get_api_total_for_date(
    date_str: str,
    date_field: str = DATE_QUERY_FIELD_DEFAULT,
    request_fn: Callable[[str, dict], Optional[str]] = None
) -> Optional[int]:
    """查询某日论文总数（opensearch totalResults）"""
    request_fn = request_fn or make_request
    search_query = build_date_query(date_str, date_field)
    xml_data = request_fn(
        ARXIV_API_BASE,
        {"search_query": search_query, "start": 0, "max_results": 1}
    )
    return parse_total_results(xml_data)


def get_db_distinct_base_id_count_for_date(client, date_str: str) -> int:
    """统计某日数据库中按 base arXiv ID 去重后的数量"""
    if not client:
        return 0

    try:
        normalized_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        log_message(f"⚠️  无效日期格式，跳过数据库计数: {date_str}", "WARNING")
        return 0

    query = f"""
        SELECT countDistinct(replaceRegexpOne(arxiv_id, 'v[0-9]+$', '')) AS base_id_count
        FROM {CH_DATABASE}.{CH_TABLE}
        WHERE toDate(published) = toDate('{normalized_date}')
    """
    try:
        result = client.query(query)
        if not result or not getattr(result, "result_rows", None):
            return 0

        first_row = result.result_rows[0]
        if isinstance(first_row, dict):
            return int(next(iter(first_row.values()), 0) or 0)
        if isinstance(first_row, (tuple, list)):
            return int(first_row[0] or 0)
        return int(first_row or 0)
    except Exception as e:
        log_message(f"⚠️  读取数据库日去重计数失败: {date_str}: {e}", "WARNING")
        return 0


def find_missed_dates(
    check_dates: List[str],
    client,
    api_total_fetcher: Callable[[str, str], Optional[int]] = get_api_total_for_date,
    db_count_fetcher: Callable[[object, str], int] = get_db_distinct_base_id_count_for_date,
    api_date_field: str = DATE_QUERY_FIELD_DEFAULT
) -> List[str]:
    """找出 API 总数大于数据库去重计数的日期（疑似漏抓）"""
    missed_dates: List[str] = []
    for date_str in check_dates:
        api_total = api_total_fetcher(date_str, api_date_field)
        db_count = db_count_fetcher(client, date_str)
        if api_total is None:
            continue
        if api_total > db_count:
            missed_dates.append(date_str)
    return missed_dates


def compute_next_sleep_seconds(run_at: str, now: Optional[datetime] = None) -> int:
    """计算到下一次执行时间（HH:MM）的秒数"""
    schedule_time = datetime.strptime(run_at, "%H:%M").time()
    now_dt = now or datetime.now()
    schedule_dt = datetime.combine(now_dt.date(), schedule_time)
    if now_dt >= schedule_dt:
        schedule_dt += timedelta(days=1)
    return int((schedule_dt - now_dt).total_seconds())


def parse_run_at(value: str) -> str:
    """验证 HH:MM 参数"""
    datetime.strptime(value, "%H:%M")
    return value

# =============================================================================
# HTTP 客户端（带重试机制）
# =============================================================================

def make_request(url: str, params: dict) -> Optional[str]:
    """发送 HTTP 请求，带有重试机制

    Args:
        url: 请求 URL
        params: 查询参数

    Returns:
        响应文本，失败返回 None
    """
    for retry_count in range(MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers=build_request_headers()
            )

            # 处理速率限制
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_seconds = int(retry_after) if retry_after else RATE_LIMIT_WAIT
                except (TypeError, ValueError):
                    wait_seconds = RATE_LIMIT_WAIT
                wait_seconds = max(wait_seconds, 1)
                log_message(f"⚠️  速率限制，暂停 {wait_seconds} 秒...", "WARNING")
                resume_time = datetime.now() + timedelta(seconds=wait_seconds)
                log_message(f"   将在 {resume_time.strftime('%H:%M:%S')} 恢复", "WARNING")
                time.sleep(wait_seconds)
                continue  # 重试

            # 处理服务器错误
            elif response.status_code >= 500:
                wait_time = min((2 ** retry_count) * 2, 60)
                log_message(f"服务器错误 ({response.status_code})，等待 {wait_time} 秒后重试", "WARNING")
                time.sleep(wait_time)
                continue  # 重试

            # 处理其他错误
            elif response.status_code != 200:
                log_message(f"HTTP {response.status_code}: {response.text[:200]}", "ERROR")
                return None

            # 成功
            return response.text

        except requests.exceptions.Timeout:
            wait_time = min((2 ** retry_count) * 2, 60)
            log_message(f"请求超时，等待 {wait_time} 秒后重试", "WARNING")
            time.sleep(wait_time)
            continue  # 重试

        except Exception as e:
            wait_time = min((2 ** retry_count) * 2, 60)
            log_message(f"请求异常: {e}，等待 {wait_time} 秒后重试", "ERROR")
            time.sleep(wait_time)
            continue  # 重试

    # 达到最大重试次数
    log_message("❌ 达到最大重试次数", "ERROR")
    return None

# =============================================================================
# XML 解析器
# =============================================================================

def parse_arxiv_xml(xml_data: str) -> List[Dict[str, Any]]:
    """解析 arXiv API 返回的 Atom XML

    Args:
        xml_data: XML 字符串

    Returns:
        论文列表
    """
    if not xml_data:
        return []

    try:
        feed = feedparser.parse(xml_data)
        if not hasattr(feed, 'entries'):
            return []
        papers = []

        for entry in feed.entries:
            # 验证必需字段
            if not hasattr(entry, 'id') or not hasattr(entry, 'title'):
                log_message("跳过无效论文: 缺少必需字段", "WARNING")
                continue

            # 提取 arXiv ID
            arxiv_id = entry.id.split('/')[-1]

            # 提取作者和机构
            authors = []
            if hasattr(entry, 'authors'):
                for author in entry.authors:
                    author_info = {
                        'name': author.get('name', ''),
                        'affiliation': ''
                    }

                    # 提取机构信息
                    if hasattr(author, 'arxiv_affiliation'):
                        author_info['affiliation'] = author.arxiv_affiliation

                    authors.append(author_info)

            # 提取分类
            categories = []
            if hasattr(entry, 'tags'):
                for tag in entry.tags:
                    if hasattr(tag, 'term'):
                        categories.append(tag.term)

            # 提取主分类
            primary_category = ''
            if hasattr(entry, 'arxiv_primary_category'):
                primary_category = entry.arxiv_primary_category.get('term', '')
            elif categories:
                primary_category = categories[0]

            # 提取链接
            url = ''
            pdf_url = ''
            if hasattr(entry, 'links'):
                for link in entry.links:
                    if link.get('rel') == 'alternate' and link.get('type') == 'text/html':
                        url = link.get('href', '')
                    elif link.get('type') == 'application/pdf':
                        pdf_url = link.get('href', '')

            # 构建论文对象
            paper = {
                'arxiv_id': arxiv_id,
                'uid': entry.id,
                'title': entry.title,
                'published': entry.published if hasattr(entry, 'published') else '',
                'updated': entry.updated if hasattr(entry, 'updated') else '',
                'authors': authors,
                'categories': categories,
                'primary_category': primary_category,
                'url': url,
                'pdf_url': pdf_url,
                'journal_ref': getattr(entry, 'arxiv_journal_ref', ''),
                'comment': getattr(entry, 'arxiv_comment', '')
            }

            papers.append(paper)

        return papers

    except Exception as e:
        log_message(f"XML 解析错误: {e}", "ERROR")
        return []

# =============================================================================
# 数据转换器
# =============================================================================

def paper_to_rows(paper: Dict[str, Any]) -> List[Dict[str, Any]]:
    """将论文数据转换为数据库行（每个作者一行）

    Args:
        paper: 论文数据

    Returns:
        数据库行列表
    """
    rows = []

    arxiv_id = paper.get('arxiv_id', '')
    uid = paper.get('uid', '')
    title = paper.get('title', '')

    # 解析发布日期
    published = None
    published_str = paper.get('published', '')
    if published_str:
        try:
            published = datetime.strptime(published_str, '%Y-%m-%dT%H:%M:%SZ').date()
        except ValueError:
            pass

    # 解析更新时间
    updated = None
    updated_str = paper.get('updated', '')
    if updated_str:
        try:
            updated = datetime.strptime(updated_str, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            pass

    categories = paper.get('categories') or []
    primary_category = paper.get('primary_category', '')
    journal_ref = paper.get('journal_ref', '')
    comment = paper.get('comment', '')
    url = paper.get('url', '')
    pdf_url = paper.get('pdf_url', '')

    authors = paper.get('authors', [])

    if not authors:
        # 没有作者信息，添加一个空行
        rows.append({
            'arxiv_id': arxiv_id,
            'uid': uid,
            'title': title,
            'published': published,
            'updated': updated,
            'categories': categories,
            'primary_category': primary_category,
            'journal_ref': journal_ref,
            'comment': comment,
            'url': url,
            'pdf_url': pdf_url,
            'author': '',
            'rank': 0,
            'tag': '其他',
            'affiliation': ''
        })
    else:
        total_authors = len(authors)
        for rank, author in enumerate(authors, 1):
            # Skip invalid author entries
            if author is None or not isinstance(author, dict):
                continue
            # 确定标签
            if rank == 1:
                tag = '第一作者'
            elif rank == total_authors:
                tag = '最后作者'
            else:
                tag = '其他'

            rows.append({
                'arxiv_id': arxiv_id,
                'uid': uid,
                'title': title,
                'published': published,
                'updated': updated,
                'categories': categories,
                'primary_category': primary_category,
                'journal_ref': journal_ref,
                'comment': comment,
                'url': url,
                'pdf_url': pdf_url,
                'author': author.get('name', ''),
                'rank': rank,
                'tag': tag,
                'affiliation': author.get('affiliation', '')
            })

    return rows

# =============================================================================
# 日期生成器
# =============================================================================

def get_all_dates_backward(start_date: str, end_year: int) -> List[str]:
    """生成从 start_date 往前到 end_year 的所有日期

    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_year: 结束年份

    Returns:
        日期列表 (YYYY-MM-DD 格式)
    """
    dates = []
    start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
    end_date_obj = datetime(end_year, 1, 1)

    current = start_date_obj
    while current >= end_date_obj:
        dates.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)

    return dates

# =============================================================================
# ClickHouse 客户端
# =============================================================================

def create_clickhouse_client():
    """创建 ClickHouse 客户端"""
    try:
        client = clickhouse_connect.get_client(
            host=CH_HOST,
            port=CH_PORT,
            username=CH_USERNAME,
            password=CH_PASSWORD,
            database=CH_DATABASE
        )

        # 测试连接
        client.command('SELECT 1')

        log_message("✅ ClickHouse 连接成功")
        return client

    except Exception as e:
        log_message(f"❌ ClickHouse 连接失败: {e}", "ERROR")
        return None


def create_arxiv_table(client):
    """创建 arXiv 表（如果不存在）"""
    try:
        # 直接使用 CREATE TABLE IF NOT EXISTS
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_TABLE} (
            arxiv_id String,
            uid String,
            title String,
            published Date,
            updated DateTime,
            categories Array(String),
            primary_category String,
            journal_ref String,
            comment String,
            url String,
            pdf_url String,
            author String,
            rank UInt16,
            tag String,
            affiliation String,
            import_date Date
        ) ENGINE = MergeTree()
        ORDER BY (arxiv_id, rank)
        """

        client.command(create_table_sql)
        log_message(f"✅ 表 {CH_DATABASE}.{CH_TABLE} 就绪")

    except Exception as e:
        log_message(f"创建表失败: {e}", "ERROR")
        raise

# =============================================================================
# 批量插入函数
# =============================================================================

def batch_insert_clickhouse(client, rows: List[Dict[str, Any]]) -> bool:
    """批量插入数据到 ClickHouse（使用临时表去重）

    Args:
        client: ClickHouse 客户端
        rows: 数据行列表

    Returns:
        是否成功
    """
    if not rows:
        return True

    # 生成唯一的临时表名以避免并发冲突
    import uuid
    temp_table = f'temp_arxiv_insert_dedup_{uuid.uuid4().hex[:8]}'

    try:
        import pandas as pd

        # 清洗数据
        cleaned_rows = []
        current_import_date = datetime.now().date()

        for row in rows:
            cleaned_row = {}

            # 处理每个字段
            cleaned_row['arxiv_id'] = str(row.get('arxiv_id', ''))
            cleaned_row['uid'] = str(row.get('uid', ''))
            cleaned_row['title'] = str(row.get('title', ''))

            # 验证并处理日期字段
            published = row.get('published')
            if isinstance(published, str):
                try:
                    published = datetime.strptime(published, '%Y-%m-%d').date()
                except ValueError:
                    published = current_import_date
            elif published is None:
                published = current_import_date
            cleaned_row['published'] = published

            # 验证并处理更新时间
            updated = row.get('updated')
            if isinstance(updated, str):
                try:
                    updated = datetime.strptime(updated, '%Y-%m-%dT%H:%M:%SZ')
                except ValueError:
                    updated = datetime.now()
            elif updated is None:
                updated = datetime.now()
            cleaned_row['updated'] = updated

            # 验证 categories 字段类型
            categories = row.get('categories', [])
            cleaned_row['categories'] = categories if isinstance(categories, list) else []

            cleaned_row['primary_category'] = str(row.get('primary_category', ''))
            cleaned_row['journal_ref'] = str(row.get('journal_ref', ''))
            cleaned_row['comment'] = str(row.get('comment', ''))
            cleaned_row['url'] = str(row.get('url', ''))
            cleaned_row['pdf_url'] = str(row.get('pdf_url', ''))
            cleaned_row['author'] = str(row.get('author', ''))
            cleaned_row['rank'] = int(row.get('rank', 0)) if row.get('rank') else 0
            cleaned_row['tag'] = str(row.get('tag', ''))
            cleaned_row['affiliation'] = str(row.get('affiliation', ''))
            cleaned_row['import_date'] = current_import_date

            cleaned_rows.append(cleaned_row)

        # 创建 DataFrame
        df = pd.DataFrame(cleaned_rows)

        # 删除可能存在的临时表
        client.command(f'DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}')

        # 创建临时表
        client.command(f'''
            CREATE TABLE {CH_DATABASE}.{temp_table} AS {CH_DATABASE}.{CH_TABLE}
            ENGINE = Memory
        ''')

        # 插入到临时表
        client.insert_df(f'{CH_DATABASE}.{temp_table}', df)

        # 与目标表反连接，只插入不存在的记录（忽略 import_date 差异）
        client.command(build_dedup_insert_sql(temp_table))

        return True

    except Exception as e:
        log_message(f"批量插入失败: {e}", "ERROR")
        return False
    finally:
        # 确保临时表被删除，避免资源泄漏
        try:
            client.command(f'DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}')
        except Exception:
            pass  # 忽略清理时的错误

# =============================================================================
# 论文获取函数
# =============================================================================

def fetch_papers_by_date(
    date_str: str,
    progress_data: dict,
    ch_client,
    per_page: Optional[int] = None,
    request_interval: Optional[float] = None,
    dry_run: bool = False,
    enable_recovery_retry: bool = False,
    recovery_max_attempts: int = RECOVERY_MAX_ATTEMPTS,
    recovery_base_wait: int = RECOVERY_BASE_WAIT,
    recovery_max_wait: int = RECOVERY_MAX_WAIT,
    date_field: str = DATE_QUERY_FIELD_DEFAULT
) -> bool:
    """获取指定日期的所有论文

    Args:
        date_str: 日期字符串 (YYYY-MM-DD)
        progress_data: 进度数据
        ch_client: ClickHouse 客户端

    Returns:
        是否成功并更新了进度
    """
    # 验证日期格式
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        log_message(f"❌ Invalid date format: {date_str}", "ERROR")
        return False

    log_message(f"📅 正在获取: {date_str}")

    try:
        all_papers = []
        start = 0
        per_page_value, interval_value = resolve_fetch_options(per_page, request_interval)

        # 构建查询参数：使用全天分钟边界
        date_key = date_to_key(date_str)
        search_query = build_date_query(date_str, date_field)
        expected_total = None

        # 分页获取
        while True:
            # 构建请求参数
            params = {
                "search_query": search_query,
                "start": start,
                "max_results": per_page_value
            }

            # 发送请求
            xml_data = make_request(ARXIV_API_BASE, params)

            if xml_data is None and enable_recovery_retry:
                for recovery_attempt in range(recovery_max_attempts):
                    available, retry_after_hint = check_arxiv_api_available()
                    wait_seconds = compute_recovery_wait_seconds(
                        recovery_attempt,
                        base_wait=recovery_base_wait,
                        max_wait=recovery_max_wait
                    )
                    if retry_after_hint is not None:
                        wait_seconds = max(wait_seconds, retry_after_hint)
                    status_text = "可用" if available else "不可用"
                    log_message(
                        f"⚠️  {date_str}: API探测{status_text}，第 {recovery_attempt + 1}/{recovery_max_attempts} 次恢复等待 {wait_seconds} 秒",
                        "WARNING"
                    )
                    time.sleep(wait_seconds)
                    xml_data = make_request(ARXIV_API_BASE, params)
                    if xml_data is not None:
                        log_message(f"✅ {date_str}: API恢复，继续抓取")
                        break

            if xml_data is None:
                log_message(f"❌ {date_str}: 获取数据失败", "ERROR")
                return False

            # 解析 XML
            papers = parse_arxiv_xml(xml_data)
            if expected_total is None:
                expected_total = parse_total_results(xml_data)

            if not papers:
                # 没有更多数据
                break

            all_papers.extend(papers)
            log_message(f"  📄 第 {start // per_page_value + 1} 页: 获取 {len(papers)} 篇论文")

            # 检查是否是最后一页
            if len(papers) < per_page_value:
                break

            start += per_page_value
            time.sleep(interval_value)

        if not all_papers:
            # 无数据日期视为成功完成，避免重复重试
            mark_date_completed(progress_data, date_key)
            log_message(f"ℹ️  {date_str}: 无数据，已标记完成")
            return True

        # 转换为数据库行
        rows = []
        for paper in all_papers:
            paper_rows = paper_to_rows(paper)
            rows.extend(paper_rows)

        # 批量插入（dry-run 只验证抓取与解析，不写库）
        if rows and not dry_run:
            # 分批写入（每 BATCH_WRITE_THRESHOLD 行）
            for i in range(0, len(rows), BATCH_WRITE_THRESHOLD):
                batch = rows[i:i + BATCH_WRITE_THRESHOLD]
                success = batch_insert_clickhouse(ch_client, batch)

                if not success:
                    log_message(f"❌ {date_str}: 数据库插入失败", "ERROR")
                    return False

                log_message(f"  💾 已写入 {len(batch)} 行")
        elif dry_run:
            log_message(f"  🧪 dry-run: 跳过写库，预计 {len(rows)} 行")

        # 全部成功，更新进度
        mark_date_completed(progress_data, date_key)

        if expected_total is not None:
            status = "匹配" if len(all_papers) == expected_total else "不匹配"
            log_message(
                f"  🔎 totalResults={expected_total}, 实际抓取={len(all_papers)} ({status})"
            )

        log_message(f"✅ {date_str}: 完成 {len(all_papers)} 篇论文 → {len(rows)} 行")
        return True

    except Exception as e:
        log_message(f"❌ {date_str}: 处理异常 - {e}", "ERROR")
        return False

# =============================================================================
# 主执行流程
# =============================================================================

class ArxivFetcher:
    """arXiv 论文获取器"""

    def __init__(
        self,
        start_date: str,
        end_year: int,
        ch_client=None,
        test_days=None,
        request_interval: float = REQUEST_INTERVAL,
        per_page: int = PER_PAGE,
        dry_run: bool = False,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        respect_progress_in_window: bool = False,
        enable_recovery_retry: bool = False,
        recovery_max_attempts: int = RECOVERY_MAX_ATTEMPTS,
        recovery_base_wait: int = RECOVERY_BASE_WAIT,
        recovery_max_wait: int = RECOVERY_MAX_WAIT,
        date_field: str = DATE_QUERY_FIELD_DEFAULT,
        daily_daemon: bool = False,
        daily_check_days: int = DAILY_DAEMON_DEFAULT_CHECK_DAYS,
        daily_run_at: str = DAILY_DAEMON_DEFAULT_RUN_AT,
        daily_run_once: bool = False
    ):
        """初始化

        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_year: 结束年份
            ch_client: ClickHouse 客户端（可选）
            test_days: 测试模式，只获取指定天数（可选）
        """
        self.start_date = start_date
        self.end_year = end_year
        self.ch_client = ch_client or create_clickhouse_client()
        self.progress = load_progress()
        self.test_days = test_days
        self.request_interval = request_interval if request_interval >= 0 else REQUEST_INTERVAL
        self.per_page = per_page if per_page > 0 else PER_PAGE
        self.dry_run = dry_run
        self.from_date = from_date
        self.to_date = to_date
        self.respect_progress_in_window = respect_progress_in_window
        self.enable_recovery_retry = enable_recovery_retry
        self.recovery_max_attempts = max(0, recovery_max_attempts)
        self.recovery_base_wait = max(1, recovery_base_wait)
        self.recovery_max_wait = max(self.recovery_base_wait, recovery_max_wait)
        self.date_field = date_field if date_field in ("submittedDate", "lastUpdatedDate") else DATE_QUERY_FIELD_DEFAULT
        self.daily_daemon = daily_daemon
        self.daily_check_days = max(0, daily_check_days)
        self.daily_run_at = daily_run_at
        self.daily_run_once = daily_run_once

    def _run_daily_cycle(self, reference_datetime: Optional[datetime] = None) -> Dict[str, int]:
        """执行一次每日增量周期（用于 daemon 或 run-once）"""
        yesterday = get_yesterday_date(reference_datetime)
        log_message(f"昨日日期: {yesterday}")

        check_dates = build_daily_check_dates(yesterday, self.daily_check_days)
        missed_dates = find_missed_dates(
            check_dates,
            self.ch_client,
            api_date_field=DATE_QUERY_FIELD_DEFAULT
        )
        if missed_dates:
            log_message(f"发现缺漏日期: {missed_dates}")
        else:
            log_message("缺漏日期: 无")

        target_dates = dedupe_date_sequence([yesterday] + missed_dates)
        stats = {"successful_dates": 0, "failed_dates": 0}

        for date_str in target_dates:
            success = fetch_papers_by_date(
                date_str,
                self.progress,
                self.ch_client,
                per_page=self.per_page,
                request_interval=self.request_interval,
                dry_run=self.dry_run,
                enable_recovery_retry=self.enable_recovery_retry,
                recovery_max_attempts=self.recovery_max_attempts,
                recovery_base_wait=self.recovery_base_wait,
                recovery_max_wait=self.recovery_max_wait,
                date_field=DATE_QUERY_FIELD_DEFAULT
            )
            if success:
                stats['successful_dates'] += 1
            else:
                stats['failed_dates'] += 1

        return stats

    def run_daily_once(self):
        """运行一次每日模式周期（测试/手动触发）"""
        if not self.ch_client:
            log_message("❌ 无法连接到 ClickHouse", "ERROR")
            return

        log_message("=" * 60)
        log_message("arXiv Daily Daemon：单次运行")
        log_message("=" * 60)

        create_arxiv_table(self.ch_client)
        return self._run_daily_cycle()

    def run_daily_loop(self):
        """循环运行 daily daemon。可通过 --daily-run-once 跳出循环"""
        if not self.ch_client:
            log_message("❌ 无法连接到 ClickHouse", "ERROR")
            return

        create_arxiv_table(self.ch_client)

        while True:
            cycle_start = datetime.now()
            log_message("=" * 60)
            log_message(f"Cycle Start: {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
            log_message("=" * 60)

            self._run_daily_cycle(cycle_start)

            if self.daily_run_once:
                log_message("single-run 模式，退出 daemon 循环")
                break

            cycle_end = datetime.now()
            sleep_seconds = compute_next_sleep_seconds(self.daily_run_at, now=cycle_end)
            next_run = cycle_end + timedelta(seconds=sleep_seconds)
            log_message(f"下一轮运行: {next_run.strftime('%Y-%m-%d %H:%M:%S')}（{sleep_seconds}s）")
            time.sleep(sleep_seconds)

    def run(self):
        """执行主流程"""
        start_time = time.time()

        log_message("=" * 60)
        log_message("arXiv 论文获取工具")
        log_message("=" * 60)
        log_message(f"开始日期: {self.start_date}")
        log_message(f"结束年份: {self.end_year}")
        log_message(f"请求间隔: {self.request_interval} 秒")
        log_message(f"每页论文数: {self.per_page}")
        log_message(f"dry-run: {'是' if self.dry_run else '否'}")
        log_message(f"恢复重试: {'开启' if self.enable_recovery_retry else '关闭'}")
        log_message(f"日期口径: {self.date_field}")
        log_message("=" * 60)

        # 创建表
        if not self.ch_client:
            log_message("❌ 无法连接到 ClickHouse", "ERROR")
            return

        create_arxiv_table(self.ch_client)

        # 生成日期列表
        if self.from_date or self.to_date:
            if not self.from_date or not self.to_date:
                raise ValueError("窗口模式需要同时指定 --from-date 和 --to-date")
            all_dates = get_dates_in_window(self.from_date, self.to_date)
            log_message(f"🎯 窗口重抓模式: {all_dates[-1]} ~ {all_dates[0]}（共 {len(all_dates)} 天）")
        else:
            all_dates = get_all_dates_backward(self.start_date, self.end_year)

        # 测试模式：限制天数
        if self.test_days:
            all_dates = all_dates[:self.test_days]
            log_message(f"🧪 测试模式：仅处理前 {self.test_days} 天")

        self.progress['total_dates'] = len(all_dates)

        # 过滤待处理日期
        if self.from_date and self.to_date and not self.respect_progress_in_window:
            pending_dates = all_dates
        else:
            pending_dates = [
                d for d in all_dates
                if date_to_key(d) not in self.progress['completed_dates']
            ]

        log_message(f"总日期数: {len(all_dates)}")
        log_message(f"已完成: {len(all_dates) - len(pending_dates)}")
        log_message(f"待处理: {len(pending_dates)}")
        log_message("=" * 60)

        if not pending_dates:
            log_message("✅ 所有日期已完成！")
            return

        # 统计信息
        stats = {
            'successful_dates': 0,
            'failed_dates': 0
        }

        # 使用 tqdm 显示进度
        with tqdm(total=len(pending_dates), desc="日期进度", unit="天", ncols=80) as pbar:
            for date_str in pending_dates:
                success = fetch_papers_by_date(
                    date_str,
                    self.progress,
                    self.ch_client,
                    per_page=self.per_page,
                    request_interval=self.request_interval,
                    dry_run=self.dry_run,
                    enable_recovery_retry=self.enable_recovery_retry,
                    recovery_max_attempts=self.recovery_max_attempts,
                    recovery_base_wait=self.recovery_base_wait,
                    recovery_max_wait=self.recovery_max_wait,
                    date_field=self.date_field
                )

                if success:
                    stats['successful_dates'] += 1
                else:
                    stats['failed_dates'] += 1

                pbar.update(1)
                pbar.set_postfix_str(f"成功:{stats['successful_dates']} 失败:{stats['failed_dates']}")

        # 刷新日志
        flush_log_buffer()

        # 打印最终统计
        elapsed_time = time.time() - start_time

        log_message("=" * 60)
        log_message("🎉 arXiv 论文获取完成！")
        log_message("=" * 60)
        log_message(f"📊 统计信息:")
        log_message(f"   - 成功日期: {stats['successful_dates']} 天")
        log_message(f"   - 失败日期: {stats['failed_dates']} 天")
        log_message(f"   - 总耗时: {elapsed_time/60:.1f} 分钟")
        log_message(f"💾 数据已写入: {CH_DATABASE}.{CH_TABLE}")
        log_message(f"📝 日志文件: {LOG_FILE}")
        log_message("=" * 60)


def parse_args(argv=None):
    """解析参数"""
    import argparse

    parser = argparse.ArgumentParser(description='arXiv 论文获取工具')
    parser.add_argument('--start-date', default=START_DATE,
                       help='开始日期 (格式: YYYY-MM-DD)')
    parser.add_argument('--end-year', type=int, default=END_YEAR,
                       help='结束年份')
    parser.add_argument('--interval', type=float, default=REQUEST_INTERVAL,
                       help='请求间隔（秒）')
    parser.add_argument('--per-page', type=int, default=PER_PAGE,
                       help='每页论文数')
    parser.add_argument('--dry-run', action='store_true',
                       help='试运行模式，不写入数据库')
    parser.add_argument('--test-days', type=int, default=None,
                       help='测试模式：只获取指定天数的数据')
    parser.add_argument('--from-date', default=None,
                       help='窗口模式起始日期 (YYYY-MM-DD)')
    parser.add_argument('--to-date', default=None,
                       help='窗口模式结束日期 (YYYY-MM-DD)')
    parser.add_argument('--respect-progress-in-window', action='store_true',
                       help='窗口模式下也跳过已完成日期（默认会重抓窗口内全部日期）')
    parser.add_argument('--recovery-retry', action='store_true',
                       help='启用可用性探测 + 指数退避 + 长间隔恢复重试')
    parser.add_argument('--recovery-max-attempts', type=int, default=RECOVERY_MAX_ATTEMPTS,
                       help='恢复重试最大次数')
    parser.add_argument('--recovery-base-wait', type=int, default=RECOVERY_BASE_WAIT,
                       help='恢复重试基础等待秒数')
    parser.add_argument('--recovery-max-wait', type=int, default=RECOVERY_MAX_WAIT,
                       help='恢复重试最大等待秒数')
    parser.add_argument('--date-field', choices=['submittedDate', 'lastUpdatedDate'], default=DATE_QUERY_FIELD_DEFAULT,
                       help='按天抓取口径：submittedDate(当天提交) 或 lastUpdatedDate(当天更新)')
    parser.add_argument('--daily-daemon', action='store_true',
                       help='启用 daily daemon 模式')
    parser.add_argument('--daily-check-days', type=int, default=DAILY_DAEMON_DEFAULT_CHECK_DAYS,
                       help='daily 模式下检查前 N 天是否缺漏（默认 30）')
    parser.add_argument('--daily-run-at', default=DAILY_DAEMON_DEFAULT_RUN_AT, type=parse_run_at,
                       help='daily daemon 的运行时间点，格式 HH:MM')
    parser.add_argument('--daily-run-once', action='store_true',
                       help='daily daemon 模式下只运行一个周期后退出')

    args = parser.parse_args(argv)

    if args.daily_check_days < 0:
        parser.error('--daily-check-days 必须 >= 0')

    return args


def create_fetcher_from_args(args):
    """根据参数创建 Fetcher"""
    return ArxivFetcher(
        args.start_date,
        args.end_year,
        test_days=args.test_days,
        request_interval=args.interval,
        per_page=args.per_page,
        dry_run=args.dry_run,
        from_date=args.from_date,
        to_date=args.to_date,
        respect_progress_in_window=args.respect_progress_in_window,
        enable_recovery_retry=args.recovery_retry,
        recovery_max_attempts=args.recovery_max_attempts,
        recovery_base_wait=args.recovery_base_wait,
        recovery_max_wait=args.recovery_max_wait,
        date_field=args.date_field,
        daily_daemon=args.daily_daemon,
        daily_check_days=args.daily_check_days,
        daily_run_at=args.daily_run_at,
        daily_run_once=args.daily_run_once
    )


def main(argv=None):
    """主函数"""
    args = parse_args(argv)

    # 设置日志
    setup_logging()

    try:
        # 创建 fetcher
        fetcher = create_fetcher_from_args(args)

        # 运行
        if args.daily_daemon:
            fetcher.run_daily_loop()
        else:
            fetcher.run()

    except KeyboardInterrupt:
        log_message("\n⚠️  用户中断")
        log_message("💾 进度已保存，下次运行将从中断处继续")

    except Exception as e:
        log_message(f"\n❌ 发生错误: {e}", "ERROR")
        import traceback
        traceback.print_exc()

    finally:
        flush_log_buffer()


if __name__ == '__main__':
    main()
