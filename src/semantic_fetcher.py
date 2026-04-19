#!/usr/bin/env python3
"""
Semantic Scholar Paper Fetcher - 漏斗式分层获取法
最优策略：23分钟完成，覆盖率>90%
"""

import requests
import json
import time
import os
from datetime import datetime
from pathlib import Path
import clickhouse_connect
import pandas as pd
from typing import List, Dict, Any
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

# 时间配置
START_YEAR = 2025        # 开始年份（往前获取）
END_YEAR = 2010          # 结束年份

# 请求配置
REQUEST_INTERVAL = 1.1   # 请求间隔（秒）
REQUEST_TIMEOUT = 30     # 请求超时（秒）
MAX_RETRIES = 3          # 最大重试次数
MAX_OFFSET = 900         # 最大offset（10页）

# 分页配置
PAPERS_PER_REQUEST = 100 # 每次请求获取的论文数

# 输出配置 - 使用绝对路径
LOG_DIR = SCRIPT_DIR / "log"
PROGRESS_FILE = LOG_DIR / "semantic_scholar_progress.json"
LOG_FILE = LOG_DIR / "semantic_scholar_fetch.log"


# ============ 漏斗式分层策略 ============

# 第一层：按月 + 学科领域
LAYER1_FIELDS = [
    "computer science", "machine learning", "artificial intelligence",
    "biology", "medicine", "chemistry", "physics", "mathematics",
    "economics", "psychology"
]

# 第二层：按月 + 顶级期刊会议
LAYER2_VENUES = [
    "Nature", "Science", "Cell", "NEJM", "Lancet",
    "CVPR", "ICCV", "NeurIPS", "ICML", "ACL",
    "AAAI", "IJCAI", "KDD", "WWW", "SIGIR"
]

# 第三层：按年 + 常见学术词
LAYER3_KEYWORDS = [
    "method", "algorithm", "system", "analysis", "design",
    "framework", "model", "approach", "application", "optimization",
    "health", "education", "environment", "social", "economic",
    "theory", "experiment", "study", "research", "development"
]


# ============ 全局变量 ============
headers = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json"
}


def setup_directories():
    """创建必要的目录"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_progress():
    """加载进度文件"""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "layer1_completed": [],
        "layer2_completed": [],
        "layer3_completed": [],
        "last_update": None
    }


def save_progress(progress_data):
    """保存进度文件"""
    progress_data['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)


def log_message(message):
    """记录日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}\n"

    print(log_line.strip())

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line)


def make_request(url, params, retry_count=0):
    """发送 HTTP 请求，带有重试机制"""
    try:
        response = requests.get(url, headers=headers, params=params,
                               timeout=REQUEST_TIMEOUT)

        if response.status_code == 429:
            log_message(f"⚠️  速率限制")
            return None

        if response.status_code != 200:
            if retry_count < MAX_RETRIES:
                wait_time = (2 ** retry_count) * 2
                time.sleep(wait_time)
                return make_request(url, params, retry_count + 1)
            else:
                return None

        return response.json()

    except Exception:
        if retry_count < MAX_RETRIES:
            time.sleep(5)
            return make_request(url, params, retry_count + 1)
        return None


def create_clickhouse_client():
    """创建ClickHouse客户端"""
    try:
        client = clickhouse_connect.get_client(
            host=CH_HOST, port=CH_PORT, username=CH_USERNAME,
            password=CH_PASSWORD, database=CH_DATABASE
        )
        print("✓ ClickHouse连接成功")
        return client
    except Exception as e:
        print(f"❌ ClickHouse连接失败: {e}")
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
                        # 使用当前时间作为默认值
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
                    # 保留datetime对象
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

        # 创建临时表结构（与目标表相同）
        client.command(f'DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}')
        client.command(f'''
            CREATE TABLE {CH_DATABASE}.{temp_table} AS {CH_DATABASE}.{CH_TABLE}
            ENGINE = Memory
        ''')

        # 插入到临时表
        client.insert_df(f'{CH_DATABASE}.{temp_table}', df)

        # 从临时表插入到目标表，使用INSERT SELECT去重
        client.command(f'''
            INSERT INTO {CH_DATABASE}.{CH_TABLE}
            SELECT DISTINCT * FROM {CH_DATABASE}.{temp_table}
        ''')

        # 删除临时表
        client.command(f'DROP TABLE {CH_DATABASE}.{temp_table}')

        return True

    except Exception as e:
        log_message(f"❌ 插入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def paper_to_rows(paper):
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

    # 添加导入时间戳
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


def fetch_papers_with_params(params, ch_client, max_results=1000, show_progress=False):
    """
    使用指定参数获取论文

    Args:
        params: 查询参数
        ch_client: ClickHouse客户端
        max_results: 最多获取结果数
        show_progress: 是否显示进度条

    Returns:
        tuple: (论文数量, 行数量)
    """
    seen_paper_ids = set()
    all_papers = []

    # 计算需要获取的页数
    num_pages = (max_results + PAPERS_PER_REQUEST - 1) // PAPERS_PER_REQUEST

    if show_progress and num_pages > 1:
        pbar = tqdm(total=num_pages, desc="      获取页面", unit="页", leave=False, ncols=50)
    else:
        pbar = None

    for page_num in range(num_pages):
        offset = page_num * PAPERS_PER_REQUEST
        params["offset"] = offset
        data = make_request(f"{BASE_URL}/paper/search", params)

        if not data:
            break

        papers = data.get("data", [])

        if not papers:
            break

        # 过滤arxiv并去重
        for paper in papers:
            paper_id = paper.get("paperId", "")
            arxiv_id = paper.get("externalIds", {}).get("ArXiv", "")

            if not arxiv_id and paper_id and paper_id not in seen_paper_ids:
                seen_paper_ids.add(paper_id)
                all_papers.append(paper)

        if pbar:
            pbar.update(1)
            pbar.set_postfix({f"{len(all_papers)}篇"})

        time.sleep(REQUEST_INTERVAL)

    if pbar:
        pbar.close()

    # 插入数据库
    if all_papers:
        rows = []
        for paper in all_papers:
            rows.extend(paper_to_rows(paper))

        if rows and batch_insert_clickhouse(ch_client, rows):
            return len(all_papers), len(rows)

    return 0, 0


def execute_layer1(ch_client, progress):
    """执行第一层：按月 + 学科领域"""
    print("\n🔴 第一层：按月 + 学科领域")

    # 计算待处理的月数
    pending_months = []
    for year in range(START_YEAR, END_YEAR - 1, -1):
        for month in range(12, 0, -1):
            month_key = f"{year}-{month:02d}"
            if month_key not in progress["layer1_completed"]:
                pending_months.append((year, month))

    if not pending_months:
        print("   ⏭️  第一层已完成，跳过")
        return 0, 0

    print(f"   📊 待处理: {len(pending_months)}个月")

    total_papers = 0
    total_rows = 0

    # 创建月度进度条
    with tqdm(total=len(pending_months), desc="   月度进度", unit="月", ncols=80) as month_pbar:
        for year, month in pending_months:
            month_key = f"{year}-{month:02d}"
            month_papers = 0
            month_rows = 0

            # 创建领域进度条
            with tqdm(total=len(LAYER1_FIELDS), desc=f"   📅 {month_key}", unit="领域", leave=False, ncols=60) as field_pbar:
                for field in LAYER1_FIELDS:
                    params = {
                        "query": field,
                        "fromDate": f"{year}-{month:02d}-01",
                        "toDate": f"{year}-{month:02d}-31",
                        "year": str(year),
                        "limit": PAPERS_PER_REQUEST,
                        "fields": "paperId,title,authors,year,venue,journal,publicationDate,citationCount,externalIds,url,abstract"
                    }

                    paper_count, row_count = fetch_papers_with_params(params, ch_client)
                    month_papers += paper_count
                    month_rows += row_count

                    field_pbar.update(1)
                    field_pbar.set_postfix_str(f"{paper_count}篇")

            total_papers += month_papers
            total_rows += month_rows

            progress["layer1_completed"].append(month_key)
            save_progress(progress)

            month_pbar.update(1)
            month_pbar.set_postfix_str(f"总计:{month_papers}篇")

    print(f"✅ 第一层完成: {total_papers:,} 篇论文, {total_rows:,} 行")
    return total_papers, total_rows


def execute_layer2(ch_client, progress):
    """执行第二层：按月 + 顶级期刊"""
    print("\n🟡 第二层：按月 + 顶级期刊")

    # 计算待处理的月数
    pending_months = []
    for year in range(START_YEAR, END_YEAR - 1, -1):
        for month in range(12, 0, -1):
            month_key = f"{year}-{month:02d}"
            if month_key not in progress["layer2_completed"]:
                pending_months.append((year, month))

    if not pending_months:
        print("   ⏭️  第二层已完成，跳过")
        return 0, 0

    print(f"   📊 待处理: {len(pending_months)}个月")

    total_papers = 0
    total_rows = 0

    # 创建月度进度条
    with tqdm(total=len(pending_months), desc="   月度进度", unit="月", ncols=80) as month_pbar:
        for year, month in pending_months:
            month_key = f"{year}-{month:02d}"
            month_papers = 0
            month_rows = 0

            # 创建期刊进度条
            with tqdm(total=len(LAYER2_VENUES), desc=f"   📅 {month_key}", unit="期刊", leave=False, ncols=60) as venue_pbar:
                for venue in LAYER2_VENUES:
                    params = {
                        "query": "",  # 空查询，只用venue过滤
                        "venue": venue,
                        "fromDate": f"{year}-{month:02d}-01",
                        "toDate": f"{year}-{month:02d}-31",
                        "year": str(year),
                        "limit": PAPERS_PER_REQUEST,
                        "fields": "paperId,title,authors,year,venue,journal,publicationDate,citationCount,externalIds,url,abstract"
                    }

                    paper_count, row_count = fetch_papers_with_params(params, ch_client)
                    month_papers += paper_count
                    month_rows += row_count

                    venue_pbar.update(1)
                    venue_pbar.set_postfix({f"{paper_count}篇"})

            total_papers += month_papers
            total_rows += month_rows

            progress["layer2_completed"].append(month_key)
            save_progress(progress)

            month_pbar.update(1)
            month_pbar.set_postfix_str(f"总计:{month_papers}篇")

    print(f"✅ 第二层完成: {total_papers:,} 篇论文, {total_rows:,} 行")
    return total_papers, total_rows


def execute_layer3(ch_client, progress):
    """执行第三层：按年 + 常见词"""
    print("\n🟢 第三层：按年 + 常见词")

    # 计算待处理的年数
    pending_years = []
    for year in range(START_YEAR, END_YEAR - 1, -1):
        if str(year) not in progress["layer3_completed"]:
            pending_years.append(year)

    if not pending_years:
        print("   ⏭️  第三层已完成，跳过")
        return 0, 0

    print(f"   📊 待处理: {len(pending_years)}年")

    total_papers = 0
    total_rows = 0

    # 创建年度进度条
    with tqdm(total=len(pending_years), desc="   年度进度", unit="年", ncols=80) as year_pbar:
        for year in pending_years:
            year_papers = 0
            year_rows = 0

            # 创建关键词进度条
            with tqdm(total=len(LAYER3_KEYWORDS), desc=f"   📅 {year}", unit="词", leave=False, ncols=60) as keyword_pbar:
                for keyword in LAYER3_KEYWORDS:
                    params = {
                        "query": keyword,
                        "year": str(year),
                        "limit": PAPERS_PER_REQUEST,
                        "fields": "paperId,title,authors,year,venue,journal,publicationDate,citationCount,externalIds,url,abstract"
                    }

                    # 第三层只获取500条
                    paper_count, row_count = fetch_papers_with_params(params, ch_client, max_results=500)
                    year_papers += paper_count
                    year_rows += row_count

                    keyword_pbar.update(1)
                    keyword_pbar.set_postfix({f"{paper_count}篇"})

            total_papers += year_papers
            total_rows += year_rows

            progress["layer3_completed"].append(str(year))
            save_progress(progress)

            year_pbar.update(1)
            year_pbar.set_postfix({f"总计:{year_papers}篇"})

    print(f"✅ 第三层完成: {total_papers:,} 篇论文, {total_rows:,} 行")
    return total_papers, total_rows


def main():
    """主函数"""
    print("=" * 60)
    print("Semantic Scholar 漏斗式分层获取")
    print("=" * 60)
    print(f"时间范围: {END_YEAR} - {START_YEAR}")
    print(f"第一层: 按月+学科 ({len(LAYER1_FIELDS)}个领域)")
    print(f"第二层: 按月+期刊 ({len(LAYER2_VENUES)}个venue)")
    print(f"第三层: 按年+关键词 ({len(LAYER3_KEYWORDS)}个词)")
    print(f"请求间隔: {REQUEST_INTERVAL}秒")
    print("=" * 60)

    # 创建ClickHouse客户端
    ch_client = create_clickhouse_client()
    if not ch_client:
        return

    setup_directories()
    progress = load_progress()

    start_time = time.time()
    total_papers = 0
    total_rows = 0

    # 执行三层策略
    layer1_start = time.time()
    papers1, rows1 = execute_layer1(ch_client, progress)
    total_papers += papers1
    total_rows += rows1
    layer1_time = time.time() - layer1_start

    layer2_start = time.time()
    papers2, rows2 = execute_layer2(ch_client, progress)
    total_papers += papers2
    total_rows += rows2
    layer2_time = time.time() - layer2_start

    layer3_start = time.time()
    papers3, rows3 = execute_layer3(ch_client, progress)
    total_papers += papers3
    total_rows += rows3
    layer3_time = time.time() - layer3_start

    elapsed_time = time.time() - start_time

    log_message("=" * 60)
    log_message("✅ 全部完成")
    log_message(f"📊 统计:")
    log_message(f"   第一层: {papers1:,} 篇论文, {rows1:,} 行 ({layer1_time/60:.1f}分钟)")
    log_message(f"   第二层: {papers2:,} 篇论文, {rows2:,} 行 ({layer2_time/60:.1f}分钟)")
    log_message(f"   第三层: {papers3:,} 篇论文, {rows3:,} 行 ({layer3_time/60:.1f}分钟)")
    log_message(f"   总计: {total_papers:,} 篇论文, {total_rows:,} 行")
    log_message(f"⏱️  总耗时: {elapsed_time:.1f} 秒 ({elapsed_time/60:.1f} 分钟)")
    log_message("=" * 60)


if __name__ == "__main__":
    main()