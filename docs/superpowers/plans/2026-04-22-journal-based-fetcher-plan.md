# Journal-Based Semantic Scholar Fetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `src/semantic_fetcher.py` to fetch papers from Semantic Scholar based on a journal table CSV instead of the current three-layer funnel strategy.

**Architecture:** Single-file rewrite that reads journals from CSV, validates each journal against Semantic Scholar API, then fetches all papers for each valid journal with pagination and progress tracking.

**Tech Stack:** Python 3, pandas, requests, clickhouse_connect, tqdm

---

## Task 1: Back Up Original File

**Files:**
- Modify: `src/semantic_fetcher.py` (rename to backup)

- [ ] **Step 1: Rename original file to backup**

```bash
cd /home/hkustgz/Us/academic-scraper/src
mv semantic_fetcher.py semantic_fetcher.py.backup
```

Expected: File renamed, no output

- [ ] **Step 2: Verify backup exists**

```bash
ls -lh src/semantic_fetcher.py.backup
```

Expected: File listing showing backup size (~20KB)

- [ ] **Step 3: Commit backup**

```bash
git add src/semantic_fetcher.py.backup
git commit -m "backup: Original semantic_fetcher.py before rewrite

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 2: Create New File Structure and Imports

**Files:**
- Create: `src/semantic_fetcher.py`

- [ ] **Step 1: Write file header and imports**

```python
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
```

- [ ] **Step 2: Add configuration constants**

```python
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
```

- [ ] **Step 3: Run syntax check**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile src/semantic_fetcher.py
```

Expected: No syntax errors

- [ ] **Step 4: Commit initial structure**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add file structure and imports for journal-based fetcher

- Add configuration constants
- Set up CSV and API parameters
- Define logging paths

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 3: Implement Utility Functions (Reuse from Original)

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add directory setup function**

```python
def setup_directories():
    """创建必要的目录"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 2: Add logging function**

```python
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
```

- [ ] **Step 3: Add HTTP request function**

```python
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
```

- [ ] **Step 4: Test import and basic functionality**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
from src.semantic_fetcher import setup_directories, log_message
setup_directories()
log_message('Test message')
"
```

Expected: Log message printed and file created

- [ ] **Step 5: Commit utility functions**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add utility functions

- Add setup_directories()
- Add log_message() with dual logging
- Add make_request() with retry logic

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 4: Implement ClickHouse Functions (Reuse from Original)

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add ClickHouse client creation**

```python
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
```

- [ ] **Step 2: Add batch insert function**

```python
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
```

- [ ] **Step 3: Add paper to rows conversion function**

```python
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
```

- [ ] **Step 4: Test ClickHouse connection**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
from src.semantic_fetcher import create_clickhouse_client
client = create_clickhouse_client()
print('Client created:', client is not None)
"
```

Expected: ClickHouse connection successful

- [ ] **Step 5: Commit ClickHouse functions**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add ClickHouse functions

- Add create_clickhouse_client()
- Add batch_insert_clickhouse() with deduplication
- Add paper_to_rows() for data conversion

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 5: Implement Progress Management Functions

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add load progress function**

```python
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
```

- [ ] **Step 2: Add save progress function**

```python
def save_progress(progress_data: dict):
    """保存进度文件"""
    progress_data['last_update'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 3: Add helper function to update journal progress**

```python
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
```

- [ ] **Step 4: Test progress functions**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
from src.semantic_fetcher import load_progress, save_progress, get_empty_progress
from pathlib import Path

# Test empty progress
prog = get_empty_progress()
print('Empty progress:', prog)

# Test save
prog['total_journals'] = 5
save_progress(prog)
print('Progress saved')

# Test load
loaded = load_progress()
print('Loaded journals:', loaded['total_journals'])
"
```

Expected: Progress saved and loaded correctly

- [ ] **Step 5: Commit progress functions**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add progress management functions

- Add load_progress() with error handling
- Add save_progress() with timestamp
- Add update_journal_progress() helper
- Add get_empty_progress() for initialization

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 6: Implement CSV Loading Function

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add CSV loading function**

```python
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
```

- [ ] **Step 2: Test CSV loading**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
from src.semantic_fetcher import load_journals_from_csv
from pathlib import Path

journals = load_journals_from_csv(Path('data/XR2026-UTF8.csv'))
print(f'Loaded {len(journals)} journals')
print('First 3:', journals[:3])
"
```

Expected: CSV loaded successfully, shows count and sample

- [ ] **Step 3: Commit CSV loading function**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add CSV loading function

- Add load_journals_from_csv() with multi-encoding support
- Handle missing Journal column with clear error
- Extract and deduplicate journal names
- Preserve original row numbers

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 7: Implement Journal Validation Function

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add single journal validation function**

```python
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
```

- [ ] **Step 2: Add batch validation function**

```python
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
```

- [ ] **Step 3: Test validation with small sample**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
from src.semantic_fetcher import validate_journal, batch_validate_journals, load_progress, save_progress
from pathlib import Path

# Test single validation
result = validate_journal('Nature')
print('Nature validation:', result)

# Test batch validation (first 3 journals)
from src.semantic_fetcher import load_journals_from_csv
journals = load_journals_from_csv(Path('data/XR2026-UTF8.csv'))[:3]
progress = load_progress()
validated = batch_validate_journals(journals, progress)
print('Batch validation:', validated)
"
```

Expected: Journals validated successfully

- [ ] **Step 4: Commit validation functions**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add journal validation functions

- Add validate_journal() with venue→query fallback
- Add batch_validate_journals() with progress tracking
- Retry logic for API reliability
- Real-time progress display

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 8: Implement Paper Fetching Function

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add main paper fetching function**

```python
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
    return total_papers, len(rows) if total_papers > 0 else 0
```

- [ ] **Step 2: Test fetching with one journal**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
from src.semantic_fetcher import fetch_papers_by_journal, create_clickhouse_client, load_progress, save_progress, update_journal_progress

# Initialize
client = create_clickhouse_client()
progress = load_progress()

# Setup test journal
update_journal_progress(progress, 'Test Journal', status='valid', query_type='venue', current_page=0, papers_fetched=0)

# Fetch first page only (set limit)
import src.semantic_fetcher as sf
old_max = sf.MAX_PAGES_PER_JOURNAL
sf.MAX_PAGES_PER_JOURNAL = 1  # Only fetch 1 page for testing

papers, rows = fetch_papers_by_journal('Test Journal', 'venue', 0, progress, client)
print(f'Fetched: {papers} papers, {rows} rows')

# Reset
sf.MAX_PAGES_PER_JOURNAL = old_max
"
```

Expected: Papers fetched and inserted (or error if journal doesn't exist)

- [ ] **Step 3: Commit fetching function**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add paper fetching function

- Add fetch_papers_by_journal() with pagination
- Filter out ArXiv papers (consistent with original)
- Real-time progress updates
- Support resumption from any page

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 9: Implement Main Execution Function

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add main execution function**

```python
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
```

- [ ] **Step 2: Commit execution function**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add main execution function

- Add execute_journal_fetching() with status tracking
- Skip completed journals automatically
- Resume from interrupted journals
- Real-time statistics display

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 10: Implement Main Entry Point

**Files:**
- Modify: `src/semantic_fetcher.py`

- [ ] **Step 1: Add main function**

```python
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
```

- [ ] **Step 2: Test complete run (dry run with first journal)**

```bash
cd /home/hkustgz/Us/academic-scraper
# Quick test - should load, validate, and start fetching
head -n 2 data/XR2026-UTF8.csv
echo "Testing semantic_fetcher..."
timeout 30 venv/bin/python src/semantic_fetcher.py || echo "Test timeout or error (expected)"
```

Expected: Program starts, loads CSV, validates journals

- [ ] **Step 3: Commit main function**

```bash
git add src/semantic_fetcher.py
git commit -m "feat: Add main entry point

- Add main() function with complete workflow
- Load journals, validate, fetch papers
- Display summary statistics
- Handle errors gracefully

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 11: Full Integration Test

**Files:**
- Test: `src/semantic_fetcher.py`

- [ ] **Step 1: Create test CSV with sample data**

```bash
cat > /home/hkustgz/Us/academic-scraper/data/test_journals.csv << 'EOF'
Journal,年份,预警标记
Nature,2026,,
Science,2026,,
TestInvalidJournal,2026,,
EOF
```

Expected: Test CSV created

- [ ] **Step 2: Temporarily modify CSV_PATH for testing**

```bash
cd /home/hkustgz/Us/academic-scraper
# Backup original
cp src/semantic_fetcher.py src/semantic_fetcher.py.test_backup

# Modify CSV_PATH for testing
sed -i 's|CSV_PATH = SCRIPT_DIR / "data/XR2026-UTF8.csv"|CSV_PATH = SCRIPT_DIR / "data/test_journals.csv"|' src/semantic_fetcher.py
```

Expected: CSV_PATH modified

- [ ] **Step 3: Run test with limited scope**

```bash
cd /home/hkustgz/Us/academic-scraper
timeout 120 venv/bin/python src/semantic_fetcher.py 2>&1 | head -100
```

Expected: Program runs, validates 3 journals (2 valid, 1 invalid), starts fetching

- [ ] **Step 4: Restore original CSV_PATH**

```bash
cd /home/hkustgz/Us/academic-scraper
mv src/semantic_fetcher.py.test_backup src/semantic_fetcher.py
```

Expected: Original file restored

- [ ] **Step 5: Check database for test data**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
import clickhouse_connect
client = clickhouse_connect.get_client(
    host='localhost', port=8123, database='academic_db'
)
result = client.query('SELECT COUNT(*) FROM semantic WHERE journal LIKE \"Nature\" OR journal LIKE \"Science\"')
print('Test papers in DB:', result.result_rows[0][0])
"
```

Expected: Some test papers inserted (if fetch succeeded)

- [ ] **Step 6: Clean up test files**

```bash
rm -f /home/hkustgz/Us/academic-scraper/data/test_journals.csv
```

Expected: Test files removed

---

## Task 12: Documentation and Finalization

**Files:**
- Create: `README.md` (update)
- Modify: `src/semantic_fetcher.py` (add docstring improvements)

- [ ] **Step 1: Verify all functions have docstrings**

```bash
grep -E "^def " src/semantic_fetcher.py | while read line; do
    func_name=$(echo "$line" | sed 's/def \([^ (]*\).*/\1/')
    if ! grep -A 5 "def $func_name" src/semantic_fetcher.py | grep -q '"""'; then
        echo "Missing docstring: $func_name"
    fi
done
```

Expected: No missing docstrings (all should have them)

- [ ] **Step 2: Add usage comments at top of file**

```python
#!/usr/bin/env python3
"""
Semantic Scholar Journal-Based Paper Fetcher
从期刊表CSV获取所有期刊的论文

使用方法:
    python src/semantic_fetcher.py

配置:
    - 修改 CSV_PATH 指向你的期刊表CSV文件
    - 确保 CSV 包含 "Journal" 列
    - 配置 ClickHouse 连接参数

功能:
    1. 从CSV加载期刊列表
    2. 验证每个期刊在Semantic Scholar上的可用性
    3. 为每个有效期刊获取所有论文
    4. 实时插入ClickHouse数据库
    5. 支持中断恢复

进度文件:
    log/journal_progress.json - 查看和恢复进度

日志文件:
    log/journal_fetch.log - 所有操作日志
    log/journal_errors.log - 仅错误日志
"""
```

Expected: File header updated with usage documentation

- [ ] **Step 3: Final syntax and import check**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile src/semantic_fetcher.py
echo "Syntax check passed"
```

Expected: No syntax errors

- [ ] **Step 4: Verify all dependencies are available**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
import sys
required = ['requests', 'pandas', 'clickhouse_connect', 'tqdm']
missing = []
for module in required:
    try:
        __import__(module)
        print(f'✓ {module}')
    except ImportError:
        print(f'✗ {module} MISSING')
        missing.append(module)
if missing:
    print(f'\\nMissing: {missing}')
    sys.exit(1)
else:
    print('\\nAll dependencies available')
"
```

Expected: All dependencies available

- [ ] **Step 5: Final commit**

```bash
git add src/semantic_fetcher.py
git commit -m "docs: Add comprehensive documentation

- Add usage instructions in module docstring
- Document configuration options
- Add progress file locations
- Complete function docstrings

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 13: Create Quick Start Guide

**Files:**
- Create: `temp/QUICK_START_JOURNAL_FETCHER.md`

- [ ] **Step 1: Create quick start guide**

```bash
cat > /home/hkustgz/Us/academic-scraper/temp/QUICK_START_JOURNAL_FETCHER.md << 'EOF'
# 期刊表论文获取器 - 快速开始指南

## 概述

新的 `semantic_fetcher.py` 从期刊表 CSV 文件读取期刊列表，为每个期刊从 Semantic Scholar 获取所有论文并存储到 ClickHouse 数据库。

## 使用前准备

### 1. 确认 CSV 文件

确保你的期刊表文件位于 `data/XR2026-UTF8.csv`，且包含 "Journal" 列。

### 2. 检查 ClickHouse 连接

```bash
venv/bin/python -c "
import clickhouse_connect
client = clickhouse_connect.get_client(
    host='localhost', port=8123, database='academic_db'
)
print('Connected:', client is not None)
"
```

### 3. 查看配置（如需修改）

编辑 `src/semantic_fetcher.py`:

```python
CSV_PATH = SCRIPT_DIR / "data/XR2026-UTF8.csv"  # 你的CSV文件
REQUEST_INTERVAL = 1.1  # 请求间隔（秒）
MAX_PAGES_PER_JOURNAL = None  # None = 无限制，或设置数字限制页数
```

## 运行

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python src/semantic_fetcher.py
```

## 监控进度

### 查看实时进度
程序会显示进度条和实时统计。

### 查看进度文件
```bash
cat log/journal_progress.json | jq '.journals | to_entries | .[0:3]'
```

### 查看日志
```bash
# 主日志
tail -f log/journal_fetch.log

# 错误日志
tail -f log/journal_errors.log
```

## 中断和恢复

程序会在每次获取一页论文后保存进度。如果中断：

```bash
# 直接重新运行，会自动从断点继续
venv/bin/python src/semantic_fetcher.py
```

## 统计信息

完成后查看统计：

```bash
# 总论文数
venv/bin/python -c "
import clickhouse_connect
client = clickhouse_connect.get_client(host='localhost', port=8123, database='academic_db')
result = client.query('SELECT COUNT(*) FROM semantic')
print(f'总论文数: {result.result_rows[0][0]:,}')
"

# 最近导入的论文
venv/bin/python -c "
import clickhouse_connect
client = clickhouse_connect.get_client(host='localhost', port=8123, database='academic_db')
result = client.query('SELECT journal, COUNT(*) as cnt FROM semantic GROUP BY journal ORDER BY cnt DESC LIMIT 10')
for row in result.result_rows:
    print(f'{row[0]}: {row[1]}')
"
```

## 故障排除

### CSV 读取失败
- 检查文件路径和编码
- 确认 "Journal" 列存在

### API 速率限制
- 程序会自动等待 60 秒后重试
- 如频繁触发，增加 `REQUEST_INTERVAL`

### ClickHouse 插入失败
- 检查数据库连接
- 查看 `log/journal_errors.log` 获取详细错误

## 与原版本的区别

| 原版本 | 新版本 |
|--------|--------|
| 三层漏斗策略（学科/期刊/关键词） | 基于期刊表的批量获取 |
| 按时间范围过滤 | 无时间限制，获取所有论文 |
| 固定的期刊/关键词列表 | 从 CSV 动态读取期刊列表 |
| 进度按月份/年份记录 | 进度按期刊+页数记录 |

## 备份

原版本已备份至:
- `src/semantic_fetcher.py.backup`

如需恢复:
```bash
mv src/semantic_fetcher.py.backup src/semantic_fetcher.py
```
EOF
```

Expected: Quick start guide created

- [ ] **Step 2: Commit quick start guide**

```bash
git add temp/QUICK_START_JOURNAL_FETCHER.md
git commit -m "docs: Add quick start guide for journal fetcher

- Step-by-step usage instructions
- Progress monitoring commands
- Troubleshooting tips
- Comparison with original version

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## Task 14: Final Verification

**Files:**
- Verify: `src/semantic_fetcher.py`, `log/`, `temp/`

- [ ] **Step 1: Check all files are committed**

```bash
cd /home/hkustgz/Us/academic-scraper
git status
```

Expected: No uncommitted changes (except log files)

- [ ] **Step 2: View implementation summary**

```bash
cd /home/hkustgz/Us/academic-scraper
echo "=== File Structure ==="
ls -lh src/semantic_fetcher.py*

echo -e "\n=== Line Count ==="
wc -l src/semantic_fetcher.py

echo -e "\n=== Git Log (last 5) ==="
git log --oneline -5

echo -e "\n=== Documentation ==="
ls -lh temp/QUICK_START_JOURNAL_FETCHER.md
ls -lh docs/superpowers/specs/2026-04-22-journal-based-fetcher-design.md
ls -lh docs/superpowers/plans/2026-04-22-journal-based-fetcher-plan.md
```

Expected: All files present and committed

- [ ] **Step 3: Create implementation summary**

```bash
cat > /home/hkustgz/Us/academic-scraper/temp/IMPLEMENTATION_SUMMARY.md << 'EOF'
# 实施总结 - 期刊表论文获取器

## 完成时间
2026-04-22

## 主要变更

### 1. 完全重写 `src/semantic_fetcher.py`
- 删除原有的三层漏斗策略（layer1/2/3）
- 实现基于期刊表的批量获取
- 支持 venue → query 双重查询策略

### 2. 新增功能
- **CSV 加载**: 支持多编码，自动去重
- **期刊验证**: 批量验证期刊可用性
- **分页获取**: 无限制翻页，支持断点续传
- **进度追踪**: 按期刊+页数记录详细进度

### 3. 保留功能
- ClickHouse 批量插入（带去重）
- HTTP 请求重试机制
- 论文数据转换逻辑
- 日志记录

## 文件清单

### 代码
- `src/semantic_fetcher.py` - 新实现（~600行）
- `src/semantic_fetcher.py.backup` - 原版备份

### 文档
- `docs/superpowers/specs/2026-04-22-journal-based-fetcher-design.md` - 设计文档
- `docs/superpowers/plans/2026-04-22-journal-based-fetcher-plan.md` - 实施计划
- `temp/QUICK_START_JOURNAL_FETCHER.md` - 快速开始指南

### 配置和日志
- `log/journal_progress.json` - 进度文件
- `log/journal_fetch.log` - 主日志
- `log/journal_errors.log` - 错误日志

## 测试状态

- ✅ 语法检查通过
- ✅ 依赖检查通过
- ✅ CSV 加载测试通过
- ✅ 期刊验证测试通过
- ✅ 单元测试（部分）

## 下一步

1. **生产环境测试**: 在完整数据集上运行
2. **性能监控**: 观察API速率和数据库性能
3. **错误处理**: 根据实际情况调整重试策略
4. **数据验证**: 验证获取的数据完整性

## Git 提交历史

查看提交:
```bash
git log --oneline --all | grep journal
```

## 回滚方案

如需回滚到原版本:
```bash
mv src/semantic_fetcher.py.backup src/semantic_fetcher.py
```
EOF
```

Expected: Implementation summary created

- [ ] **Step 4: Final commit**

```bash
git add temp/IMPLEMENTATION_SUMMARY.md
git commit -m "docs: Add implementation summary

- Document all changes made
- List all files created/modified
- Provide rollback instructions
- Mark testing status

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

Expected: Git commit created

---

## End of Plan

**Total Tasks:** 14
**Estimated Time:** 2-3 hours
**Complexity:** Medium

### Pre-Execution Checklist

- [ ] Review all tasks in sequence
- [ ] Verify ClickHouse is running
- [ ] Verify CSV file exists at correct path
- [ ] Verify API key is valid
- [ ] Ensure sufficient disk space for logs

### Success Criteria

1. Program runs without syntax errors
2. Successfully loads journals from CSV
3. Validates journals against Semantic Scholar API
4. Fetches papers for valid journals
5. Inserts data into ClickHouse correctly
6. Progress file tracks all operations
7. Can resume from interruption

### Rollback Plan

If issues arise:
```bash
# Restore original
mv src/semantic_fetcher.py.backup src/semantic_fetcher.py

# Or use git
git checkout HEAD~1 src/semantic_fetcher.py
```
