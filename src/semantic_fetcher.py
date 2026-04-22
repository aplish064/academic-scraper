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
        data = make_request(f"{BASE_URL}/paper/search", params)

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
        data = make_request(f"{BASE_URL}/paper/search", params)

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
    """批量验证期刊

    Returns:
        dict: {journal_name: {"query_type": str, "status": str}}
    """
    log_message("开始批量验证期刊")
    print("\n🔍 验证期刊有效性...")

    validated = {}

    with tqdm(total=len(journal_list), desc="   进度",
              unit="期刊", ncols=80) as pbar:
        for journal_info in journal_list:
            journal_name = journal_info["name"]

            # 检查是否已验证
            if journal_name in progress_data["journals"]:
                existing = progress_data["journals"][journal_name]
                if existing["status"] in ["valid", "completed", "in_progress"]:
                    validated[journal_name] = {
                        "query_type": existing.get("query_type"),
                        "status": existing["status"]
                    }
                    pbar.update(1)
                    continue

            # 验证期刊
            result = validate_journal(journal_name)

            if result["valid"]:
                validated[journal_name] = {
                    "query_type": result["query_type"],
                    "status": "valid"
                }
                update_journal_progress(
                    progress_data, journal_name,
                    status="valid",
                    query_type=result["query_type"]
                )
            else:
                update_journal_progress(
                    progress_data, journal_name,
                    status="failed",
                    query_type=None,
                    error=result.get("error", "Unknown error")
                )

            pbar.update(1)
            pbar.set_postfix_str(f"有效:{len(validated)}个")

            # 保存进度
            save_progress(progress_data)
            time.sleep(REQUEST_INTERVAL)

    valid_count = len([j for j in validated.values()
                      if j["status"] == "valid"])
    failed_count = len(journal_list) - valid_count

    print(f"   有效: {valid_count} 个 | 无效: {failed_count} 个")
    log_message(f"验证完成: {valid_count} 有效, {failed_count} 无效")

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

    while True:
        # 检查页数限制
        if MAX_PAGES_PER_JOURNAL and current_page >= MAX_PAGES_PER_JOURNAL:
            log_message(f"  达到最大页数限制: {MAX_PAGES_PER_JOURNAL}")
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
        data = make_request(f"{BASE_URL}/paper/search", params)

        if data is None:
            log_message(f"  第{current_page}页请求失败", "WARNING")
            break

        papers = data.get("data", [])

        if not papers:
            log_message(f"  第{current_page}页无数据，获取完成")
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
            break

        # 插入数据库
        rows = []
        for paper in page_papers:
            rows.extend(paper_to_rows(paper))

        if rows and batch_insert_clickhouse(ch_client, rows):
            total_papers += len(page_papers)
            total_rows += len(rows)

            # 更新进度
            update_journal_progress(
                progress_data, journal_name,
                status="in_progress",
                current_page=current_page + 1,
                papers_fetched=progress_data["journals"][journal_name]["papers_fetched"] + len(page_papers)
            )
            save_progress(progress_data)

            log_message(f"  第{current_page}页: 获取{len(page_papers)}篇论文, {len(rows)}行")
        else:
            log_message(f"  第{current_page}页插入失败", "ERROR")
            break

        current_page += 1
        time.sleep(REQUEST_INTERVAL)

    # 标记完成
    update_journal_progress(
        progress_data, journal_name,
        status="completed",
        total_pages=current_page
    )
    save_progress(progress_data)

    log_message(f"✓ {journal_name}: 完成 {total_papers}篇论文")
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
        if info["status"] == "valid" or
           (name in progress_data["journals"] and
            progress_data["journals"][name]["status"] in ["valid", "in_progress"])
    ]

    with tqdm(total=len(pending_journals), desc="   进度",
              unit="期刊", ncols=80) as pbar:
        for journal_name, journal_info in pending_journals:
            # 检查状态
            if journal_name in progress_data["journals"]:
                existing = progress_data["journals"][journal_name]
                if existing["status"] == "completed":
                    status_count["completed"] += 1
                    total_papers += existing.get("papers_fetched", 0)
                    pbar.update(1)
                    continue
                elif existing["status"] == "in_progress":
                    start_page = existing.get("current_page", 0)
                    status_count["in_progress"] += 1
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
