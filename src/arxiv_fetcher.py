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
ARXIV_API_BASE = "https://export.arxiv.org/api/query"
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

        # 从临时表插入到目标表，使用 DISTINCT 去重
        client.command(f'''
            INSERT INTO {CH_DATABASE}.{CH_TABLE}
            SELECT DISTINCT * FROM {CH_DATABASE}.{temp_table}
        ''')

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

def fetch_papers_by_date(date_str: str, progress_data: dict, ch_client) -> bool:
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
        per_page = PER_PAGE

        # 构建查询参数（修复：移除 + 号，使用空格）
        date_key = date_to_key(date_str)
        search_query = f"lastUpdatedDate:[{date_key} TO {date_key}]"

        # 分页获取
        while True:
            # 构建请求参数
            params = {
                "search_query": search_query,
                "start": start,
                "max_results": per_page
            }

            # 发送请求
            xml_data = make_request(ARXIV_API_BASE, params)

            if xml_data is None:
                log_message(f"❌ {date_str}: 获取数据失败", "ERROR")
                return False

            # 解析 XML
            papers = parse_arxiv_xml(xml_data)

            if not papers:
                # 没有更多数据
                break

            all_papers.extend(papers)
            log_message(f"  📄 第 {start // per_page + 1} 页: 获取 {len(papers)} 篇论文")

            # 检查是否是最后一页
            if len(papers) < per_page:
                break

            start += per_page
            time.sleep(REQUEST_INTERVAL)

        if not all_papers:
            log_message(f"⚠️  {date_str}: 没有论文数据", "WARNING")
            return False

        # 转换为数据库行
        rows = []
        for paper in all_papers:
            paper_rows = paper_to_rows(paper)
            rows.extend(paper_rows)

        # 批量插入
        if rows:
            # 分批写入（每 BATCH_WRITE_THRESHOLD 行）
            for i in range(0, len(rows), BATCH_WRITE_THRESHOLD):
                batch = rows[i:i + BATCH_WRITE_THRESHOLD]
                success = batch_insert_clickhouse(ch_client, batch)

                if not success:
                    log_message(f"❌ {date_str}: 数据库插入失败", "ERROR")
                    return False

                log_message(f"  💾 已写入 {len(batch)} 行")

        # 全部成功，更新进度（修复：添加重复检查）
        if date_key not in progress_data['completed_dates']:
            progress_data['completed_dates'].append(date_key)
        save_progress(progress_data)

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

    def __init__(self, start_date: str, end_year: int, ch_client=None, test_days=None):
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

    def run(self):
        """执行主流程"""
        start_time = time.time()

        log_message("=" * 60)
        log_message("arXiv 论文获取工具")
        log_message("=" * 60)
        log_message(f"开始日期: {self.start_date}")
        log_message(f"结束年份: {self.end_year}")
        log_message(f"请求间隔: {REQUEST_INTERVAL} 秒")
        log_message(f"每页论文数: {PER_PAGE}")
        log_message("=" * 60)

        # 创建表
        if not self.ch_client:
            log_message("❌ 无法连接到 ClickHouse", "ERROR")
            return

        create_arxiv_table(self.ch_client)

        # 生成日期列表
        all_dates = get_all_dates_backward(self.start_date, self.end_year)

        # 测试模式：限制天数
        if self.test_days:
            all_dates = all_dates[:self.test_days]
            log_message(f"🧪 测试模式：仅处理前 {self.test_days} 天")

        self.progress['total_dates'] = len(all_dates)

        # 过滤已完成的日期
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
                success = fetch_papers_by_date(date_str, self.progress, self.ch_client)

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


def main():
    """主函数"""
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

    args = parser.parse_args()

    # 设置日志
    setup_logging()

    try:
        # 创建 fetcher
        fetcher = ArxivFetcher(args.start_date, args.end_year, test_days=args.test_days)

        # 运行
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
