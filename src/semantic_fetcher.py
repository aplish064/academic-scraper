#!/usr/bin/env python3
"""
Semantic Scholar Journal-Based Paper Fetcher
从期刊表CSV获取所有期刊的论文
"""

import requests
import json
import time
import os
from datetime import datetime
from pathlib import Path
import clickhouse_connect
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from tqdm import tqdm

# 获取脚本所在目录的绝对路径
SCRIPT_DIR = Path(__file__).parent.parent.absolute()

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

# 请求配置
REQUEST_INTERVAL = 1.1
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

# 查询配置
PAPERS_PER_REQUEST = 100
MAX_PAGES_PER_JOURNAL = None  # None = 无限制

# 字段列表
FIELDS = "paperId,title,authors,year,venue,journal,publicationDate,citationCount,externalIds,url,abstract"

# 输出配置
LOG_DIR = SCRIPT_DIR / "log"
PROGRESS_FILE = LOG_DIR / "journal_progress.json"
LOG_FILE = LOG_DIR / "journal_fetch.log"
ERROR_LOG_FILE = LOG_DIR / "journal_errors.log"

# ============ 全局变量 ============
headers = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json"
}


# ============ 工具函数 ============

def setup_directories():
    """创建必要的目录"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


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


def make_request(url: str, params: dict, retry_count: int = 0) -> Optional[dict]:
    """发送 HTTP 请求，带有重试机制"""
    try:
        response = requests.get(url, headers=headers, params=params,
                               timeout=REQUEST_TIMEOUT)

        if response.status_code == 429:
            log_message(f"速率限制，暂停60秒", "WARNING")
            time.sleep(60)
            if retry_count < MAX_RETRIES:
                return make_request(url, params, retry_count + 1)
            return None

        if response.status_code != 200:
            if retry_count < MAX_RETRIES:
                wait_time = (2 ** retry_count) * 2
                time.sleep(wait_time)
                return make_request(url, params, retry_count + 1)
            else:
                log_message(f"请求失败: HTTP {response.status_code}", "ERROR")
                return None

        return response.json()

    except requests.exceptions.Timeout:
        log_message(f"请求超时", "WARNING")
        if retry_count < MAX_RETRIES:
            time.sleep(5)
            return make_request(url, params, retry_count + 1)
        return None
    except Exception as e:
        log_message(f"请求异常: {e}", "ERROR")
        if retry_count < MAX_RETRIES:
            time.sleep(5)
            return make_request(url, params, retry_count + 1)
        return None


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
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
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

