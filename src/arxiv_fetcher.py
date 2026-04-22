#!/usr/bin/env python3
"""
arXiv Paper Fetcher - 单线程同步架构
从 2026-04-22 往前获取到 1990 年的所有论文
"""

import requests
import json
import time
import gc
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import feedparser
import clickhouse_connect
from tqdm import tqdm

# =============================================================================
# 配置参数
# =============================================================================

# API 配置
ARXIV_API_BASE = "http://export.arxiv.org/api/query"
REQUEST_INTERVAL = 1.0        # 请求间隔（秒）
REQUEST_TIMEOUT = 30          # 请求超时（秒）
MAX_RETRIES = 3               # 最大重试次数
PER_PAGE = 3000              # 每页论文数
RATE_LIMIT_WAIT = 60          # 速率限制等待时间（秒）
TIMEOUT_RETRY_WAIT = 5        # 超时重试等待时间（秒）

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

# 文件路径配置
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
LOG_DIR = PROJECT_ROOT / "log"
PROGRESS_FILE = LOG_DIR / "arxiv_fetch_progress.json"
LOG_FILE = LOG_DIR / "arxiv_fetch.log"
ERROR_LOG_FILE = LOG_DIR / "arxiv_errors.log"

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
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.writelines(log_buffer)
        log_buffer.clear()

# =============================================================================
# 进度管理
# =============================================================================

def load_progress() -> Dict[str, Any]:
    """加载进度文件"""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
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
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

            # 处理速率限制
            if response.status_code == 429:
                log_message("⚠️  速率限制，暂停 60 秒...", "WARNING")
                resume_time = datetime.now() + timedelta(seconds=RATE_LIMIT_WAIT)
                log_message(f"   将在 {resume_time.strftime('%H:%M:%S')} 恢复", "WARNING")
                time.sleep(RATE_LIMIT_WAIT)
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
