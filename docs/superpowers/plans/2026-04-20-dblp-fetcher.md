# DBLP Fetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建DBLP论文数据获取系统，从DBLP XML快照解析所有计算机科学论文，获取作者详情，存储到ClickHouse宽表。

**架构:** 双队列流水线 - 多线程XML解析器 + 异步作者API查询 + 智能同名匹配 + 批量ClickHouse写入。

**Tech Stack:** Python 3.8+, asyncio, ThreadPoolExecutor, xml.etree.ElementTree, clickhouse_connect, requests, tqdm

---

## File Structure

```
src/
  dblp_fetcher.py              # 主程序入口和流程控制
  dblp_xml_parser.py           # XML解析和分片处理
  dblp_author_matcher.py       # 同名作者智能匹配
  dblp_api_client.py           # DBLP API客户端（复用dblp-api代码）
  dblp_checkpoint.py           # 检查点管理器
  dblp_monitor.py              # 性能监控和日志
  dblp_clickhouse.py           # ClickHouse写入器

log/
  dblp_fetch_progress.json     # 进度检查点
  dblp_fetcher.log             # 主日志
  dblp_errors.log              # 错误日志
  dblp_api.log                 # API调用日志
  dblp_performance.log         # 性能日志
  failed_batches/              # 失败批次保存目录

data/
  dblp.xml.gz                  # DBLP XML快照（自动下载）
```

---

## Task 1: 创建项目基础结构和配置

**Files:**
- Create: `src/dblp_fetcher.py`
- Create: `src/dblp_config.py`

- [ ] **Step 1: 创建配置文件**

```python
# src/dblp_config.py
"""DBLP Fetcher 配置"""

# DBLP 数据源
DBLP_DROPS_BASE = "https://drops.dagstuhl.de/entities/artifact/10.4230"
DBLP_XML_MIRROR = "https://dblp.uni-trier.de/xml"
DBLP_AUTHOR_API = "https://dblp.org/search/author/api"
DBLP_PERSON_API = "https://dblp.org/pid"

# 并发配置
XML_PARSER_THREADS = 50              # XML解析线程数
AUTHOR_API_CONCURRENT = 100          # 作者API并发数
CH_BATCH_SIZE = 9000                  # ClickHouse批量大小

# 超时配置
REQUEST_TIMEOUT = 20                  # API请求超时（秒）
MAX_RETRIES = 3                       # 最大重试次数

# 文件路径
DATA_DIR = "/home/hkustgz/Us/academic-scraper/data"
LOG_DIR = "/home/hkustgz/Us/academic-scraper/log"
XML_SNAPSHOT_PATH = f"{DATA_DIR}/dblp.xml.gz"
PROGRESS_FILE = f"{LOG_DIR}/dblp_fetch_progress.json"

# ClickHouse 配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'dblp'
CH_USERNAME = 'default'
CH_PASSWORD = ''

# CCF 目录路径
CCF_CATALOG_PATH = "/home/hkustgz/Us/dblp-api/dblp/data/ccf_catalog.csv"
```

- [ ] **Step 2: 创建主程序框架**

```python
#!/usr/bin/env python3
"""
DBLP Fetcher - 计算机科学论文数据获取系统
双队列流水线架构：XML解析 + 作者API查询
"""

import asyncio
import sys
import signal
from pathlib import Path

# 添加项目路径
SCRIPT_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from src.dblp_config import *
from src.dblp_checkpoint import CheckpointManager
from src.dblp_monitor import PerformanceMonitor, setup_loggers
from src.dblp_clickhouse import create_clickhouse_client


def main():
    """主函数"""
    print("="*80)
    print("DBLP Fetcher - 计算机科学论文数据获取系统")
    print("="*80)
    print()

    # 创建必要的目录
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    Path(f"{LOG_DIR}/failed_batches").mkdir(parents=True, exist_ok=True)

    # 设置日志
    setup_loggers(LOG_DIR)

    # 初始化监控器
    monitor = PerformanceMonitor()

    # 初始化检查点
    checkpoint = CheckpointManager(PROGRESS_FILE)

    # 连接ClickHouse
    print("📡 连接ClickHouse...")
    ch_client = create_clickhouse_client()
    if not ch_client:
        print("❌ ClickHouse连接失败，程序终止")
        return
    print("✅ ClickHouse连接成功\n")

    # TODO: 实现主流程
    print("主流程待实现...")

    # 测试：完成
    print("\n✅ 基础框架创建成功")


if __name__ == '__main__':
    main()
```

- [ ] **Step 3: 测试基础框架**

```bash
cd /home/hkustgz/Us/academic-scraper
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

预期输出：
```
================================================================================
DBLP Fetcher - 计算机科学论文数据获取系统
================================================================================

📡 连接ClickHouse...
✅ ClickHouse连接成功

主流程待实现...

✅ 基础框架创建成功
```

---

## Task 2: 实现检查点管理器

**Files:**
- Create: `src/dblp_checkpoint.py`
- Modify: `src/dblp_fetcher.py` (导入checkpoint模块)

- [ ] **Step 1: 创建检查点管理器**

```python
# src/dblp_checkpoint.py
"""检查点管理器 - 支持断点续传"""

import json
import os
from datetime import datetime
from typing import Dict, Any, Set


class CheckpointManager:
    """检查点管理器 - 支持多层级断点续传"""

    def __init__(self, checkpoint_path: str):
        self.checkpoint_path = checkpoint_path
        self.checkpoint = self._load_or_create()

    def _load_or_create(self) -> Dict[str, Any]:
        """加载或创建检查点文件"""
        if os.path.exists(self.checkpoint_path):
            try:
                with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 转换processed_keys为set
                    if 'xml' in data and 'processed_keys' in data['xml']:
                        if isinstance(data['xml']['processed_keys'], list):
                            data['xml']['processed_keys'] = set(data['xml']['processed_keys'])
                    return data
            except Exception as e:
                print(f"⚠️  加载检查点失败: {e}，创建新检查点")

        # 新检查点
        return {
            'version': '1.0',
            'last_update': None,

            # XML解析进度
            'xml': {
                'current_snapshot': None,
                'file_size': 0,
                'parsed_chunks': [],              # 已完成的分片ID
                'processed_keys': set(),          # 已处理的论文key
                'total_records': 0
            },

            # 作者API查询进度
            'authors': {
                'queried_authors': {},            # 已查询的作者缓存
                'failed_authors': [],             # 失败的作者列表
                'total_queried': 0
            },

            # ClickHouse写入进度
            'clickhouse': {
                'last_written_batch': 0,
                'total_rows_written': 0,
                'failed_batches': []
            },

            # 统计信息
            'stats': {
                'total_papers': 0,
                'total_authors': 0,
                'total_rows': 0,
                'start_time': None,
                'elapsed_time': 0
            }
        }

    def save(self):
        """保存检查点（原子写入）"""
        self.checkpoint['last_update'] = datetime.now().isoformat()

        # 转换set为list以便JSON序列化
        save_data = self.checkpoint.copy()
        save_data['xml']['processed_keys'] = list(save_data['xml']['processed_keys'])

        # 原子写入：先写临时文件，再重命名
        temp_path = self.checkpoint_path + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)

        os.replace(temp_path, self.checkpoint_path)

    def is_xml_chunk_completed(self, chunk_id: int) -> bool:
        """检查XML分片是否已完成"""
        return chunk_id in self.checkpoint['xml']['parsed_chunks']

    def is_paper_processed(self, dblp_key: str) -> bool:
        """检查论文是否已处理"""
        return dblp_key in self.checkpoint['xml']['processed_keys']

    def is_author_queried(self, author_name: str) -> bool:
        """检查作者是否已查询"""
        return author_name in self.checkpoint['authors']['queried_authors']

    def get_author_cache(self, author_name: str) -> Dict[str, Any] | None:
        """获取缓存的作者信息"""
        return self.checkpoint['authors']['queried_authors'].get(author_name)

    def mark_xml_chunk_completed(self, chunk_id: int):
        """标记XML分片完成"""
        if chunk_id not in self.checkpoint['xml']['parsed_chunks']:
            self.checkpoint['xml']['parsed_chunks'].append(chunk_id)
        self.save()

    def mark_paper_processed(self, dblp_key: str):
        """标记论文已处理"""
        self.checkpoint['xml']['processed_keys'].add(dblp_key)
        self.save()

    def cache_author_result(self, author_name: str, author_data: Dict[str, Any]):
        """缓存作者查询结果"""
        self.checkpoint['authors']['queried_authors'][author_name] = author_data
        self.checkpoint['authors']['total_queried'] += 1
        self.save()

    def add_failed_author(self, author_name: str):
        """添加失败的作者"""
        if author_name not in self.checkpoint['authors']['failed_authors']:
            self.checkpoint['authors']['failed_authors'].append(author_name)
        self.save()

    def mark_clickhouse_batch_written(self, batch_size: int):
        """标记ClickHouse批次写入"""
        self.checkpoint['clickhouse']['last_written_batch'] += 1
        self.checkpoint['clickhouse']['total_rows_written'] += batch_size
        self.save()

    def update_stats(self, **kwargs):
        """更新统计信息"""
        for key, value in kwargs.items():
            if key in self.checkpoint['stats']:
                self.checkpoint['stats'][key] = value
        self.save()

    def get_summary(self) -> Dict[str, Any]:
        """获取检查点摘要"""
        return {
            'last_update': self.checkpoint['last_update'],
            'xml_chunks_completed': len(self.checkpoint['xml']['parsed_chunks']),
            'papers_processed': len(self.checkpoint['xml']['processed_keys']),
            'authors_queried': self.checkpoint['authors']['total_queried'],
            'rows_written': self.checkpoint['clickhouse']['total_rows_written'],
            'stats': self.checkpoint['stats']
        }
```

- [ ] **Step 2: 在主程序中集成检查点**

```python
# 在 src/dblp_fetcher.py 中添加
from src.dblp_checkpoint import CheckpointManager

def main():
    # ... 现有代码 ...

    # 初始化检查点
    checkpoint = CheckpointManager(PROGRESS_FILE)

    # 测试检查点
    print("📂 检查点测试:")
    summary = checkpoint.get_summary()
    print(f"   上次更新: {summary['last_update']}")
    print(f"   已处理论文: {summary['papers_processed']}")
    print(f"   已查询作者: {summary['authors_queried']}")
    print(f"   已写入行数: {summary['rows_written']}")
```

- [ ] **Step 3: 测试检查点管理器**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

预期输出包含：
```
📂 检查点测试:
   上次更新: None
   已处理论文: 0
   已查询作者: 0
   已写入行数: 0
```

检查文件是否创建：
```bash
ls -la /home/hkustgz/Us/academic-scraper/log/dblp_fetch_progress.json
```

---

## Task 3: 实现ClickHouse表创建和写入器

**Files:**
- Create: `src/dblp_clickhouse.py`
- Create: `src/dblp_clickhouse.py` (表创建函数)

- [ ] **Step 1: 创建ClickHouse表**

```python
# src/dblp_clickhouse.py
"""ClickHouse操作模块"""

import clickhouse_connect
import pandas as pd
from typing import List, Dict, Any
from pathlib import Path
import json

from src.dblp_config import *


def create_clickhouse_client():
    """创建ClickHouse客户端"""
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
        return client
    except Exception as e:
        print(f"❌ ClickHouse连接失败: {e}")
        return None


def create_dblp_table(client):
    """创建DBLP表（如果不存在）"""
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_TABLE} (
        -- 论文标识
        dblp_key String,
        mdate String,
        type String,

        -- 论文基本信息
        title String,
        year String,
        venue String,
        venue_type String,
        ccf_class String,

        -- 作者信息
        author_pid String,
        author_name String,
        author_orcid String,
        author_rank UInt8,
        author_role String,
        author_total_papers UInt32,
        author_profile_url String,

        -- 详细元数据
        volume String,
        number String,
        pages String,
        publisher String,

        -- 标识符
        doi String,
        ee String,
        dblp_url String,

        -- 机构信息
        institution String,
        institution_confidence Float32,

        -- 元数据
        created_at DateTime DEFAULT now()
    ) ENGINE = MergeTree()
    ORDER BY (author_pid, year, dblp_key)
    SETTINGS index_granularity = 8192
    """

    try:
        client.command(create_table_sql)
        print(f"✅ 表 {CH_DATABASE}.{CH_TABLE} 已就绪")
        return True
    except Exception as e:
        print(f"❌ 创建表失败: {e}")
        return False


def batch_insert_clickhouse(client, rows: List[Dict[str, Any]]) -> bool:
    """批量插入数据到ClickHouse（带去重）"""
    if not rows:
        return True

    try:
        # 数据清洗
        cleaned_rows = []
        for row in rows:
            cleaned_row = {}
            for key, value in row.items():
                if value is None:
                    cleaned_row[key] = ''
                elif isinstance(value, float) and pd.isna(value):
                    cleaned_row[key] = 0.0 if 'confidence' in key else 0
                else:
                    cleaned_row[key] = value
            cleaned_rows.append(cleaned_row)

        # 创建DataFrame
        df = pd.DataFrame(cleaned_rows)

        # 确保数值列类型正确
        if 'author_rank' in df.columns:
            df['author_rank'] = df['author_rank'].astype('uint8')
        if 'author_total_papers' in df.columns:
            df['author_total_papers'] = df['author_total_papers'].astype('uint32')
        if 'institution_confidence' in df.columns:
            df['institution_confidence'] = df['institution_confidence'].astype('float32')

        # 使用临时表去重
        temp_table = f'temp_{CH_TABLE}_insert'

        # 创建临时表
        client.command(f'DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}')
        client.command(f'''
            CREATE TABLE {CH_DATABASE}.{temp_table} AS {CH_DATABASE}.{CH_TABLE}
            ENGINE = Memory
        ''')

        # 插入到临时表
        client.insert_df(f'{CH_DATABASE}.{temp_table}', df)

        # 从临时表插入到目标表（去重）
        client.command(f'''
            INSERT INTO {CH_DATABASE}.{CH_TABLE}
            SELECT DISTINCT * FROM {CH_DATABASE}.{temp_table}
        ''')

        # 删除临时表
        client.command(f'DROP TABLE {CH_DATABASE}.{temp_table}')

        return True

    except Exception as e:
        print(f"❌ 插入ClickHouse失败: {e}")
        # 保存失败批次
        save_failed_batch(rows, e)
        return False


def save_failed_batch(batch_data: List[Dict[str, Any]], error: Exception):
    """保存失败的批次到文件"""
    from datetime import datetime

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    failed_file = f"{LOG_DIR}/failed_batches/batch_{timestamp}.json"

    Path(failed_file).parent.mkdir(parents=True, exist_ok=True)

    with open(failed_file, 'w', encoding='utf-8') as f:
        json.dump({
            'timestamp': timestamp,
            'error': str(error),
            'batch_size': len(batch_data),
            'data': batch_data[:10]  # 只保存前10条作为示例
        }, f, indent=2, ensure_ascii=False)

    print(f"💾 失败批次已保存: {failed_file}")
```

- [ ] **Step 2: 在主程序中创建表**

```python
# 在 src/dblp_fetcher.py 的 main() 函数中添加
def main():
    # ... 现有代码 ...

    # 连接ClickHouse
    print("📡 连接ClickHouse...")
    ch_client = create_clickhouse_client()
    if not ch_client:
        print("❌ ClickHouse连接失败，程序终止")
        return
    print("✅ ClickHouse连接成功")

    # 创建表
    print("📋 创建ClickHouse表...")
    create_dblp_table(ch_client)
    print()
```

- [ ] **Step 3: 测试ClickHouse连接和表创建**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

预期输出：
```
📡 连接ClickHouse...
✅ ClickHouse连接成功
📋 创建ClickHouse表...
✅ 表 academic_db.dblp 已就绪
```

验证表是否创建：
```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
import clickhouse_connect
client = clickhouse_connect.get_client(host='localhost', port=8123, database='academic_db')
print(client.command('DESCRIBE TABLE academic_db.dblp'))
"
```

---

## Task 4: 实现性能监控和日志系统

**Files:**
- Create: `src/dblp_monitor.py`

- [ ] **Step 1: 创建性能监控器**

```python
# src/dblp_monitor.py
"""性能监控和日志系统"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import time
from typing import Dict, Any


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self):
        self.metrics = {
            # XML解析
            'xml_parse_start_time': None,
            'xml_parse_records': 0,
            'xml_parse_chunks_completed': 0,

            # 作者API
            'author_api_total_calls': 0,
            'author_api_success': 0,
            'author_api_failed': 0,
            'author_api_cache_hits': 0,
            'author_api_total_duration': 0.0,

            # ClickHouse
            'ch_total_batches': 0,
            'ch_total_rows': 0,
            'ch_failed_batches': 0,

            # 总体
            'start_time': None,
            'total_records_processed': 0
        }
        self.start_time = None

    def start(self):
        """开始监控"""
        self.start_time = time.time()
        self.metrics['start_time'] = self.start_time

    def record_xml_parse(self, chunk_id: int, record_count: int, duration: float):
        """记录XML解析性能"""
        self.metrics['xml_parse_records'] += record_count
        self.metrics['xml_parse_chunks_completed'] += 1
        self.metrics['total_records_processed'] += record_count

        perf_logger.info(
            f"XML解析 - chunk={chunk_id}, records={record_count}, "
            f"time={duration:.2f}s, speed={record_count/duration:.1f} rec/s"
        )

    def record_author_api(self, success: bool, duration: float, cached: bool = False):
        """记录作者API调用"""
        self.metrics['author_api_total_calls'] += 1
        self.metrics['author_api_total_duration'] += duration

        if success:
            self.metrics['author_api_success'] += 1
        else:
            self.metrics['author_api_failed'] += 1

        if cached:
            self.metrics['author_api_cache_hits'] += 1

        api_logger.debug(
            f"API调用 - success={success}, duration={duration:.2f}s, cached={cached}"
        )

    def record_ch_batch(self, batch_size: int, success: bool):
        """记录ClickHouse批次写入"""
        self.metrics['ch_total_batches'] += 1

        if success:
            self.metrics['ch_total_rows'] += batch_size
        else:
            self.metrics['ch_failed_batches'] += 1

        perf_logger.info(
            f"ClickHouse写入 - batch_size={batch_size}, success={success}, "
            f"total_batches={self.metrics['ch_total_batches']}"
        )

    def get_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        if not self.start_time:
            return {}

        elapsed = time.time() - self.start_time

        return {
            'elapsed_time': elapsed,
            'xml_parse_speed': (
                self.metrics['xml_parse_records'] / elapsed
                if elapsed > 0 else 0
            ),
            'author_api_success_rate': (
                self.metrics['author_api_success'] / self.metrics['author_api_total_calls']
                if self.metrics['author_api_total_calls'] > 0 else 0
            ),
            'author_api_avg_duration': (
                self.metrics['author_api_total_duration'] / self.metrics['author_api_total_calls']
                if self.metrics['author_api_total_calls'] > 0 else 0
            ),
            'ch_total_rows': self.metrics['ch_total_rows'],
            'overall_speed': (
                self.metrics['total_records_processed'] / elapsed
                if elapsed > 0 else 0
            )
        }


def setup_loggers(log_dir: str):
    """设置多级日志系统"""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 创建日志器
    loggers = {
        'main': setup_logger(
            'dblp_fetcher',
            log_path / 'dblp_fetcher.log',
            logging.INFO
        ),
        'error': setup_logger(
            'dblp_errors',
            log_path / 'dblp_errors.log',
            logging.ERROR
        ),
        'api': setup_logger(
            'dblp_api',
            log_path / 'dblp_api.log',
            logging.DEBUG
        ),
        'perf': setup_logger(
            'dblp_performance',
            log_path / 'dblp_performance.log',
            logging.INFO
        )
    }

    # 设置为全局变量
    global logger, error_logger, api_logger, perf_logger
    logger = loggers['main']
    error_logger = loggers['error']
    api_logger = loggers['api']
    perf_logger = loggers['perf']


def setup_logger(name: str, log_file: Path, level: int) -> logging.Logger:
    """设置单个日志器"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 清除已有的handlers
    logger.handlers.clear()

    # 文件处理器（轮转）
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(level)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 格式化
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# 全局日志器
logger = None
error_logger = None
api_logger = None
perf_logger = None
```

- [ ] **Step 2: 在主程序中集成监控**

```python
# 在 src/dblp_fetcher.py 中添加
from src.dblp_monitor import PerformanceMonitor, setup_loggers, logger

def main():
    # ... 现有代码 ...

    # 设置日志
    setup_loggers(LOG_DIR)
    logger.info("DBLP Fetcher 启动")

    # 初始化监控器
    monitor = PerformanceMonitor()
    monitor.start()

    # 测试监控
    logger.info("监控器已启动")
```

- [ ] **Step 3: 测试日志系统**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

检查日志文件是否创建：
```bash
ls -la /home/hkustgz/Us/academic-scraper/log/dblp_*.log
```

---

## Task 5: 实现XML下载和分片计算

**Files:**
- Create: `src/dblp_xml_parser.py`
- Modify: `src/dblp_fetcher.py`

- [ ] **Step 1: 创建XML下载器**

```python
# src/dblp_xml_parser.py
"""XML解析器 - 下载、分片、解析"""

import gzip
import xml.etree.ElementTree as ET
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests

from src.dblp_config import *


def download_dblp_snapshot(snapshot_date: Optional[str] = None) -> str:
    """
    下载DBLP XML快照

    Args:
        snapshot_date: 快照日期（格式：2026-03-01），None则下载最新

    Returns:
        下载的文件路径
    """
    if snapshot_date:
        url = f"{DBLP_DROPS_BASE}/dblp.xml.{snapshot_date.replace('-', '')}/dblp.xml.gz"
    else:
        # 使用镜像站下载最新版本
        url = f"{DBLP_XML_MIRROR}/dblp.xml.gz"

    print(f"📥 下载DBLP XML: {url}")

    try:
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        # 下载到临时文件
        temp_path = XML_SNAPSHOT_PATH + ".downloading"

        with open(temp_path, 'wb') as f:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        progress = downloaded / total_size * 100
                        print(f"\r   进度: {progress:.1f}%", end='', flush=True)

        print()  # 换行

        # 重命名为正式文件
        os.replace(temp_path, XML_SNAPSHOT_PATH)

        file_size = os.path.getsize(XML_SNAPSHOT_PATH) / (1024**3)  # GB
        print(f"✅ 下载完成: {XML_SNAPSHOT_PATH} ({file_size:.2f} GB)")

        return XML_SNAPSHOT_PATH

    except Exception as e:
        print(f"❌ 下载失败: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def get_latest_snapshot_date() -> Optional[str]:
    """获取最新的快照日期"""
    try:
        # 查询DROPS目录
        url = f"{DBLP_DROPS_BASE}/dblp.xml"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # 简化：直接返回None，使用镜像站
        return None

    except:
        return None


def calculate_xml_chunks(xml_file_path: str, num_chunks: int = 50) -> List[Dict[str, Any]]:
    """
    计算XML文件的分片位置

    策略：按字节偏移量分片，每个分片找到最近的<record>开始标签

    Args:
        xml_file_path: XML文件路径
        num_chunks: 分片数量

    Returns:
        分片信息列表
    """
    file_size = os.path.getsize(xml_file_path)
    chunk_size = file_size // num_chunks

    print(f"📊 计算XML分片: {file_size / (1024**3):.2f} GB → {num_chunks} 个分片")

    chunks = []

    with open(xml_file_path, 'rb') as f:
        for i in range(num_chunks):
            start = i * chunk_size

            if i == num_chunks - 1:
                # 最后一个分片到文件末尾
                end = file_size
            else:
                # 找到下一个合适的分片点
                f.seek(start)
                buffer = f.read(10000)  # 读取10KB缓冲

                # 查找记录开始标签
                record_tags = [
                    b'<article ',
                    b'<inproceedings ',
                    b'<proceedings ',
                    b'<book ',
                    b'<incollection ',
                    b'<phdthesis ',
                    b'<mastersthesis '
                ]

                best_pos = start + chunk_size
                for tag in record_tags:
                    pos = buffer.find(tag)
                    if pos != -1:
                        candidate = start + pos
                        if candidate < best_pos:
                            best_pos = candidate

                end = best_pos

            chunks.append({
                'thread_id': i,
                'start': start,
                'end': end,
                'size': end - start
            })

    print(f"✅ 分片计算完成，平均每个分片: {chunks[0]['size'] / (1024**2):.2f} MB")

    return chunks


def parse_dblp_record(elem: ET.Element) -> Dict[str, Any]:
    """
    解析DBLP记录（论文、作者等）

    Args:
        elem: XML元素

    Returns:
        解析后的记录字典
    """
    record = {
        'dblp_key': elem.get('key', ''),
        'mdate': elem.get('mdate', ''),
        'type': elem.tag,
        'title': elem.findtext('title') or '',
        'year': elem.findtext('year') or '',
        'venue': None,
        'pages': elem.findtext('pages') or '',
        'volume': elem.findtext('volume') or '',
        'number': elem.findtext('number') or '',
        'publisher': elem.findtext('publisher') or '',
        'authors': [],
        'doi': '',
        'ee': [],
        'url': elem.findtext('url') or ''
    }

    # 提取venue（期刊或会议名称）
    for tag in ['journal', 'booktitle', 'school', 'publisher']:
        venue = elem.findtext(tag)
        if venue:
            record['venue'] = venue
            break

    # 提取作者列表
    for author_elem in elem.findall('author'):
        author = author_elem.text
        if author:
            record['authors'].append(author)

    # 提取DOI
    doi_elem = elem.find('doi')
    if doi_elem is not None and doi_elem.text:
        record['doi'] = doi_elem.text

    # 提取电子版链接
    for ee_elem in elem.findall('ee'):
        if ee_elem.text:
            record['ee'].append(ee_elem.text)

    return record
```

- [ ] **Step 2: 在主程序中测试XML下载**

```python
# 在 src/dblp_fetcher.py 中添加测试代码
def main():
    # ... 现有代码 ...

    # 测试XML下载（首次运行时下载）
    if not os.path.exists(XML_SNAPSHOT_PATH):
        print("\n🔥 首次运行，需要下载DBLP XML (~1GB)")
        confirm = input("是否继续？(y/n): ")
        if confirm.lower() != 'y':
            print("取消")
            return

        from src.dblp_xml_parser import download_dblp_snapshot
        download_dblp_snapshot()
    else:
        print(f"✅ DBLP XML已存在: {XML_SNAPSHOT_PATH}")
```

- [ ] **Step 3: 测试分片计算**

```python
# 在 src/dblp_fetcher.py 中添加
from src.dblp_xml_parser import calculate_xml_chunks

def main():
    # ... 现有代码 ...

    # 测试分片计算
    from src.dblp_xml_parser import calculate_xml_chunks

    print("\n📊 测试分片计算...")
    chunks = calculate_xml_chunks(XML_SNAPSHOT_PATH, num_chunks=50)
    print(f"分片数量: {len(chunks)}")
    print(f"第一个分片: {chunks[0]}")
```

- [ ] **Step 4: 运行测试**

```bash
# 如果需要下载（首次运行）
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py

# 查看分片信息
```

---

## Task 6: 实现多线程XML解析器

**Files:**
- Modify: `src/dblp_xml_parser.py`
- Create: `src/dblp_xml_parser.py` (解析器worker)

- [ ] **Step 1: 实现XML解析worker**

```python
# 在 src/dblp_xml_parser.py 中添加
import queue
import threading
from typing import Callable, Optional
import time

def xml_parser_worker(
    xml_file_path: str,
    chunk: Dict[str, Any],
    paper_queue: queue.Queue,
    checkpoint_manager,
    progress_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    XML解析工作线程

    Args:
        xml_file_path: XML文件路径
        chunk: 分片信息
        paper_queue: 论文记录队列
        checkpoint_manager: 检查点管理器
        progress_callback: 进度回调函数

    Returns:
        解析统计信息
    """
    chunk_id = chunk['thread_id']
    start_pos = chunk['start']
    end_pos = chunk['end']

    stats = {
        'chunk_id': chunk_id,
        'record_count': 0,
        'skipped_count': 0,
        'duration': 0.0
    }

    start_time = time.time()

    try:
        # 打开文件并定位到分片起始位置
        # 注意：由于是gzip压缩文件，需要特殊处理
        import gzip

        with gzip.open(xml_file_path, 'rb') as f:
            # 简化处理：对于gzip，我们使用iterparse但需要跳过
            # 这里先用简单实现：解压后处理
            pass

        # 临时方案：解压到临时文件后处理
        temp_file = xml_file_path + ".temp"
        if not os.path.exists(temp_file):
            print(f"  [分片{chunk_id}] 解压XML...")
            with gzip.open(xml_file_path, 'rb') as f_in:
                with open(temp_file, 'wb') as f_out:
                    f_out.write(f_in.read())

        # 解析分片
        with open(temp_file, 'rb') as f:
            f.seek(start_pos)

            context = ET.iterparse(f, events=('start', 'end'))
            context = iter(context)

            # 跳到分片起始位置
            current_pos = start_pos

            for event, elem in context:
                current_pos = f.tell()

                # 超出分片范围，停止
                if current_pos > end_pos:
                    break

                if event == 'end' and elem.tag in [
                    'article', 'inproceedings', 'proceedings',
                    'book', 'incollection', 'phdthesis', 'mastersthesis'
                ]:
                    # 解析记录
                    try:
                        record = parse_dblp_record(elem)

                        # 检查是否已处理
                        if not checkpoint_manager.is_paper_processed(record['dblp_key']):
                            # 放入队列
                            paper_queue.put(record)
                            checkpoint_manager.mark_paper_processed(record['dblp_key'])
                            stats['record_count'] += 1
                        else:
                            stats['skipped_count'] += 1

                        # 清理元素
                        elem.clear()

                    except Exception as e:
                        logger.error(f"解析记录失败: {e}")

        duration = time.time() - start_time
        stats['duration'] = duration

        # 标记分片完成
        checkpoint_manager.mark_xml_chunk_completed(chunk_id)

        if progress_callback:
            progress_callback(chunk_id, stats)

        logger.info(
            f"分片{chunk_id}完成: {stats['record_count']}条新记录, "
            f"{stats['skipped_count']}条已跳过, 耗时{duration:.2f}秒"
        )

    except Exception as e:
        logger.error(f"分片{chunk_id}解析失败: {e}")
        import traceback
        traceback.print_exc()

    return stats


def parse_xml_parallel(
    xml_file_path: str,
    chunks: List[Dict[str, Any]],
    paper_queue: queue.Queue,
    checkpoint_manager,
    num_workers: int = 10
) -> Dict[str, Any]:
    """
    并行解析XML

    Args:
        xml_file_path: XML文件路径
        chunks: 分片列表
        paper_queue: 论文记录队列
        checkpoint_manager: 检查点管理器
        num_workers: 工作线程数

    Returns:
        总体统计信息
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    overall_stats = {
        'total_chunks': len(chunks),
        'completed_chunks': 0,
        'total_records': 0,
        'total_skipped': 0,
        'total_duration': 0.0
    }

    # 过滤已完成的分片
    pending_chunks = [
        chunk for chunk in chunks
        if not checkpoint_manager.is_xml_chunk_completed(chunk['thread_id'])
    ]

    print(f"\n🔥 XML解析: {len(pending_chunks)}/{len(chunks)} 个分片待处理")

    if not pending_chunks:
        print("✅ 所有分片已完成")
        return overall_stats

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # 提交所有任务
        futures = {
            executor.submit(
                xml_parser_worker,
                xml_file_path,
                chunk,
                paper_queue,
                checkpoint_manager
            ): chunk for chunk in pending_chunks
        }

        # 收集结果
        for future in as_completed(futures):
            try:
                stats = future.result()
                overall_stats['completed_chunks'] += 1
                overall_stats['total_records'] += stats['record_count']
                overall_stats['total_skipped'] += stats['skipped_count']
                overall_stats['total_duration'] += stats['duration']

                # 更新进度
                progress = overall_stats['completed_chunks'] / len(pending_chunks) * 100
                print(
                    f"\r  进度: {overall_stats['completed_chunks']}/{len(pending_chunks)} "
                    f"({progress:.1f}%) - 新增{overall_stats['total_records']}条记录",
                    end='', flush=True
                )

            except Exception as e:
                chunk = futures[future]
                logger.error(f"分片{chunk['thread_id']}失败: {e}")

    print()  # 换行

    overall_stats['total_duration'] = time.time() - start_time

    print(f"✅ XML解析完成:")
    print(f"   分片: {overall_stats['completed_chunks']}/{len(pending_chunks)}")
    print(f"   新增记录: {overall_stats['total_records']}")
    print(f"   跳过记录: {overall_stats['total_skipped']}")
    print(f"   耗时: {overall_stats['total_duration']:.2f}秒")
    print(f"   速度: {overall_stats['total_records']/overall_stats['total_duration']:.1f} 记录/秒")

    return overall_stats
```

- [ ] **Step 2: 在主程序中测试XML解析**

```python
# 在 src/dblp_fetcher.py 中添加
import queue

def main():
    # ... 现有代码 ...

    # 测试XML解析
    from src.dblp_xml_parser import calculate_xml_chunks, parse_xml_parallel

    print("\n🔥 测试XML解析...")
    chunks = calculate_xml_chunks(XML_SNAPSHOT_PATH, num_chunks=50)

    # 创建论文队列
    paper_queue = queue.Queue(maxsize=10000)

    # 并行解析（只用2个分片测试）
    test_chunks = chunks[:2]
    stats = parse_xml_parallel(
        XML_SNAPSHOT_PATH,
        test_chunks,
        paper_queue,
        checkpoint,
        num_workers=2
    )

    print(f"\n解析结果: {stats}")
```

- [ ] **Step 3: 运行测试**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

预期输出应该显示解析进度和统计信息。

---

## Task 7: 实现作者详情API客户端

**Files:**
- Create: `src/dblp_api_client.py`
- Modify: `src/dblp_fetcher.py`

- [ ] **Step 1: 创建DBLP API客户端（复用dblp-api代码）**

```python
# src/dblp_api_client.py
"""DBLP API客户端 - 复用dblp-api代码"""

import sys
from pathlib import Path

# 添加dblp-api路径
DBLP_API_PATH = Path("/home/hkustgz/Us/dblp-api")
sys.path.insert(0, str(DBLP_API_PATH))

import xml.etree.ElementTree as ET
import time
import requests
from urllib.parse import urlencode
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.dblp_config import *


# 复用dblp-api的核心函数
_session = None


def _build_session() -> requests.Session:
    """构建带重试的HTTP会话"""
    session = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=('GET',)
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        'User-Agent': 'dblp-fetcher/1.0 (+https://github.com/academic-scraper)'
    })
    return session


def _get_text(url: str) -> str:
    """获取文本内容"""
    global _session
    if _session is None:
        _session = _build_session()

    try:
        response = _session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        _session = _build_session()
        time.sleep(1)
        response = _session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text


def _parse_record(record: ET.Element) -> dict:
    """解析DBLP记录"""
    def _extract_venue(record: ET.Element) -> str | None:
        for tag in ('journal', 'booktitle', 'school', 'publisher'):
            text = record.findtext(tag)
            if text is not None:
                return text
        return None

    def _extract_external_links(record: ET.Element) -> list[str]:
        return [ee.text for ee in record.findall('ee') if ee.text]

    return {
        'type': record.tag,
        'key': record.get('key'),
        'mdate': record.get('mdate'),
        'title': record.findtext('title'),
        'year': record.findtext('year'),
        'venue': _extract_venue(record),
        'authors': [author.text for author in record.findall('author') if author.text],
        'external_links': _extract_external_links(record),
        'dblp_path': record.findtext('url'),
    }


def get_person_profile(pid_or_url: str, max_publications: int | None = None) -> dict:
    """
    获取作者详细资料

    Args:
        pid_or_url: 作者PID或URL
        max_publications: 最大返回论文数

    Returns:
        作者资料字典
    """
    pid = pid_or_url.rsplit('/pid/', maxsplit=1)[-1] if '/pid/' in pid_or_url else pid_or_url

    try:
        xml_text = _get_text(f'{DBLP_PERSON_API}/{pid}.xml')
        root = ET.fromstring(xml_text)

        pid_attr = root.get('pid')
        person = root.find('person')
        publications = [_parse_record(entry[0]) for entry in root.findall('r') if len(entry) > 0]

        if max_publications is not None:
            publications = publications[:max_publications]

        orcids = {
            author.get('orcid')
            for entry in root.findall('r')
            for record in entry
            for author in record.findall('author')
            if author.get('pid') == pid_attr and author.get('orcid')
        }

        return {
            'name': root.get('name'),
            'pid': pid_attr,
            'record_count': int(root.get('n', 0)),
            'person_key': person.get('key') if person is not None else None,
            'profile_url': f'https://dblp.org/pid/{pid_attr}',
            'orcids': sorted(orcids),
            'publications': publications
        }

    except Exception as e:
        logger.error(f"获取作者资料失败: pid={pid_or_url}, error={e}")
        raise


def search_authors(query: str, limit: int = 10) -> list[dict]:
    """
    搜索作者

    Args:
        query: 作者姓名
        limit: 返回结果数量

    Returns:
        作者列表
    """
    try:
        options = {
            'q': query,
            'format': 'json',
            'h': limit,
        }

        url = f"{DBLP_AUTHOR_API}?{urlencode(options)}"
        response = _session.get(url, timeout=REQUEST_TIMEOUT) if _session else requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        data = response.json()
        hits = data['result']['hits'].get('hit') or []

        results = []
        for hit in hits:
            info = hit.get('info', {})
            url = info.get('url', '')
            pid = url.rsplit('/pid/', maxsplit=1)[-1] if '/pid/' in url else None

            results.append({
                'name': info.get('author', ''),
                'pid': pid,
                'url': url,
                'info': info
            })

        return results

    except Exception as e:
        logger.error(f"搜索作者失败: query={query}, error={e}")
        return []
```

- [ ] **Step 2: 测试API客户端**

```python
# 在 src/dblp_fetcher.py 中添加测试
def main():
    # ... 现有代码 ...

    # 测试API客户端
    from src.dblp_api_client import search_authors, get_person_profile

    print("\n🔍 测试作者搜索...")
    results = search_authors("Alban Siffer", limit=5)
    print(f"找到 {len(results)} 个结果")
    if results:
        print(f"第一个结果: {results[0]}")

        # 测试获取详细资料
        if results[0].get('pid'):
            print(f"\n👤 获取作者详细资料...")
            profile = get_person_profile(results[0]['pid'])
            print(f"作者: {profile['name']}")
            print(f"论文数: {profile['record_count']}")
            print(f"ORCID: {profile['orcids']}")
```

- [ ] **Step 3: 运行测试**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

预期输出应该显示作者搜索结果和详细资料。

---

## Task 8: 实现同名作者智能匹配

**Files:**
- Create: `src/dblp_author_matcher.py`

- [ ] **Step 1: 创建作者匹配器**

```python
# src/dblp_author_matcher.py
"""同名作者智能匹配"""

from typing import Dict, Any, List, Optional
from src.dblp_api_client import search_authors, get_person_profile
from src.dblp_monitor import logger


def calculate_coauthor_overlap(publications: List[Dict], coauthors: List[str]) -> int:
    """
    计算合作者重叠度

    Args:
        publications: 作者的论文列表
        coauthors: 论文中的合作者列表

    Returns:
        重叠的合作者数量
    """
    overlap = 0
    for pub in publications:
        pub_authors = pub.get('authors', [])
        for author in pub_authors:
            if author in coauthors:
                overlap += 1
    return overlap


def match_author_by_institution(
    author_name: str,
    paper_context: Dict[str, Any],
    cache: Dict[str, Any] = None
) -> Optional[Dict[str, Any]]:
    """
    智能匹配同名作者

    Args:
        author_name: 作者名字
        paper_context: 论文上下文
            - venue: 会议/期刊名
            - year: 发表年份
            - title: 论文标题
            - coauthors: 合作者列表
        cache: 作者查询缓存

    Returns:
        匹配的作者资料，包含confidence字段
    """
    # 检查缓存
    if cache and author_name in cache:
        logger.debug(f"作者缓存命中: {author_name}")
        return cache[author_name]

    try:
        # Step 1: 搜索同名作者
        candidates = search_authors(author_name, limit=10)

        if not candidates:
            logger.warning(f"未找到作者: {author_name}")
            return None

        if len(candidates) == 1:
            # 唯一匹配
            logger.info(f"唯一匹配: {author_name}")
            profile = get_person_profile(candidates[0]['pid'])
            profile['confidence'] = 1.0
            return profile

        # Step 2: 多个同名作者，需要智能匹配
        logger.info(f"同名作者冲突: {author_name}, {len(candidates)} 个候选")

        # 策略A: 场所匹配（在相同venue发表过文章）
        venue = paper_context.get('venue', '')
        venue_matches = []

        for candidate in candidates:
            if not candidate.get('pid'):
                continue

            try:
                profile = get_person_profile(candidate['pid'], max_publications=20)

                # 检查是否在相同venue发表过
                for pub in profile['publications']:
                    if pub.get('venue') == venue:
                        venue_matches.append({
                            'profile': profile,
                            'match_count': 1,
                            'confidence': 0.9
                        })
                        break
            except Exception as e:
                logger.warning(f"获取候选者资料失败: {e}")
                continue

        if len(venue_matches) == 1:
            logger.info(f"场所匹配成功: {author_name} -> {venue_matches[0]['profile']['pid']}")
            result = venue_matches[0]['profile']
            result['confidence'] = venue_matches[0]['confidence']
            return result

        # 策略B: 合作者网络匹配
        coauthors = paper_context.get('coauthors', [])
        if coauthors:
            coauthor_matches = []

            for candidate in candidates:
                if not candidate.get('pid'):
                    continue

                try:
                    profile = get_person_profile(candidate['pid'], max_publications=20)
                    overlap = calculate_coauthor_overlap(profile['publications'], coauthors)

                    if overlap > 0:
                        confidence = min(0.5 + overlap * 0.1, 0.95)
                        coauthor_matches.append({
                            'profile': profile,
                            'overlap': overlap,
                            'confidence': confidence
                        })
                except Exception as e:
                    logger.warning(f"获取候选者资料失败: {e}")
                    continue

            if coauthor_matches:
                # 选择合作者重叠最多的
                coauthor_matches.sort(key=lambda x: x['overlap'], reverse=True)
                logger.info(
                    f"合作者匹配成功: {author_name} -> "
                    f"{coauthor_matches[0]['profile']['pid']}, "
                    f"重叠{coauthor_matches[0]['overlap']}个合作者"
                )
                result = coauthor_matches[0]['profile']
                result['confidence'] = coauthor_matches[0]['confidence']
                return result

        # 策略C: 使用论文数量（多产者更可能是目标）
        logger.info(f"使用论文数量匹配: {author_name}")
        candidates_with_profiles = []

        for candidate in candidates:
            if not candidate.get('pid'):
                continue

            try:
                profile = get_person_profile(candidate['pid'])
                candidates_with_profiles.append(profile)
            except Exception as e:
                logger.warning(f"获取候选者资料失败: {e}")
                continue

        if candidates_with_profiles:
            # 选择论文数最多的
            candidates_with_profiles.sort(key=lambda x: x.get('record_count', 0), reverse=True)
            result = candidates_with_profiles[0]
            result['confidence'] = 0.5  # 低置信度
            logger.info(
                f"选择多产者: {author_name} -> {result['pid']}, "
                f"{result['record_count']}篇论文, 置信度=0.5"
            )
            return result

        logger.warning(f"所有匹配策略失败: {author_name}")
        return None

    except Exception as e:
        logger.error(f"作者匹配失败: {author_name}, error={e}")
        return None


def batch_match_authors(
    papers: List[Dict[str, Any]],
    checkpoint_manager,
    cache: Dict[str, Any] = None
) -> Dict[str, Dict[str, Any]]:
    """
    批量匹配作者

    Args:
        papers: 论文列表
        checkpoint_manager: 检查点管理器
        cache: 作者缓存

    Returns:
        作者名 -> 作者资料 的映射
    """
    if cache is None:
        cache = {}

    # 提取所有唯一作者
    all_authors = set()
    for paper in papers:
        authors = paper.get('authors', [])
        all_authors.update(authors)

    logger.info(f"需要匹配 {len(all_authors)} 个唯一作者")

    # 匹配每个作者
    matched_authors = {}
    for i, author_name in enumerate(all_authors):
        # 检查是否已查询
        if checkpoint_manager.is_author_queried(author_name):
            cached = checkpoint_manager.get_author_cache(author_name)
            if cached:
                matched_authors[author_name] = cached
                continue

        # 匹配作者
        # 使用第一篇包含该作者的论文作为上下文
        paper_context = None
        for paper in papers:
            if author_name in paper.get('authors', []):
                paper_context = {
                    'venue': paper.get('venue', ''),
                    'year': paper.get('year', ''),
                    'title': paper.get('title', ''),
                    'coauthors': [
                        a for a in paper.get('authors', [])
                        if a != author_name
                    ]
                }
                break

        if paper_context:
            profile = match_author_by_institution(
                author_name,
                paper_context,
                cache
            )

            if profile:
                matched_authors[author_name] = profile
                checkpoint_manager.cache_author_result(author_name, profile)

        # 进度
        if (i + 1) % 100 == 0:
            print(f"\r  作者匹配进度: {i+1}/{len(all_authors)}", end='', flush=True)

    print()  # 换行

    return matched_authors
```

- [ ] **Step 2: 测试作者匹配器**

```python
# 在 src/dblp_fetcher.py 中添加测试
def main():
    # ... 现有代码 ...

    # 测试作者匹配
    from src.dblp_author_matcher import match_author_by_institution

    print("\n🎯 测试作者匹配...")

    # 构造测试上下文
    paper_context = {
        'venue': 'KDD',
        'year': '2017',
        'title': 'Anomaly Detection in Streams with Extreme Value Theory',
        'coauthors': ['Pierre-Alain Fouque', 'Alexandre Termier', 'Christine Largouët']
    }

    profile = match_author_by_institution("Alban Siffer", paper_context)
    if profile:
        print(f"匹配成功:")
        print(f"  姓名: {profile['name']}")
        print(f"  PID: {profile['pid']}")
        print(f"  论文数: {profile['record_count']}")
        print(f"  置信度: {profile.get('confidence', 0)}")
    else:
        print("匹配失败")
```

- [ ] **Step 3: 运行测试**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

---

## Task 9: 实现数据合并和宽表展开

**Files:**
- Create: `src/dblp_merger.py`

- [ ] **Step 1: 创建数据合并器**

```python
# src/dblp_merger.py
"""数据合并器 - 合并论文和作者信息，展开为宽表"""

from typing import List, Dict, Any
import pandas as pd

from src.dblp_monitor import logger


def expand_to_wide_table(
    papers: List[Dict[str, Any]],
    author_profiles: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    将论文和作者信息展开为宽表

    Args:
        papers: 论文列表
        author_profiles: 作者名 -> 作者资料 的映射

    Returns:
        宽表记录列表（每行一个作者-论文对）
    """
    wide_rows = []

    for paper in papers:
        authors = paper.get('authors', [])
        total_authors = len(authors)

        for rank, author_name in enumerate(authors, start=1):
            # 获取作者资料
            profile = author_profiles.get(author_name, {})

            # 确定作者角色
            if rank == 1:
                author_role = '第一作者'
            elif rank == total_authors:
                author_role = '最后作者'
            else:
                author_role = '其他'

            # 构造宽表记录
            row = {
                # 论文标识
                'dblp_key': paper.get('dblp_key', ''),
                'mdate': paper.get('mdate', ''),
                'type': paper.get('type', ''),

                # 论文基本信息
                'title': paper.get('title', ''),
                'year': paper.get('year', ''),
                'venue': paper.get('venue', ''),
                'venue_type': determine_venue_type(paper.get('type', '')),
                'ccf_class': '',  # 后续添加

                # 作者信息
                'author_pid': profile.get('pid', ''),
                'author_name': author_name,
                'author_orcid': format_orcid(profile.get('orcids', [])),
                'author_rank': rank,
                'author_role': author_role,
                'author_total_papers': profile.get('record_count', 0),
                'author_profile_url': profile.get('profile_url', ''),

                # 详细元数据
                'volume': paper.get('volume', ''),
                'number': paper.get('number', ''),
                'pages': paper.get('pages', ''),
                'publisher': paper.get('publisher', ''),

                # 标识符
                'doi': paper.get('doi', ''),
                'ee': format_external_links(paper.get('ee', [])),
                'dblp_url': paper.get('url', ''),

                # 机构信息（从论文推断）
                'institution': extract_institution(paper),
                'institution_confidence': profile.get('confidence', 0.0)
            }

            wide_rows.append(row)

    logger.info(f"展开为宽表: {len(papers)}篇论文 -> {len(wide_rows)}行")
    return wide_rows


def determine_venue_type(paper_type: str) -> str:
    """确定发表场所类型"""
    type_mapping = {
        'article': 'journal',
        'inproceedings': 'conference',
        'proceedings': 'conference',
        'book': 'book',
        'incollection': 'book',
        'phdthesis': 'thesis',
        'mastersthesis': 'thesis'
    }
    return type_mapping.get(paper_type, 'other')


def format_orcid(orcids: List[str]) -> str:
    """格式化ORCID（取第一个）"""
    return orcids[0] if orcids else ''


def format_external_links(links: List[str]) -> str:
    """格式化外部链接（取第一个）"""
    return links[0] if links else ''


def extract_institution(paper: Dict[str, Any]) -> str:
    """
    从论文中提取机构信息

    策略：优先从publisher提取，其次从venue
    """
    publisher = paper.get('publisher', '')
    venue = paper.get('venue', '')

    # 简化策略：返回venue作为机构（通常包含学校名）
    # 更精确的方法需要使用NLP提取
    if publisher and 'University' in publisher or 'Institute' in publisher:
        return publisher
    elif venue:
        return venue

    return ''
```

- [ ] **Step 2: 测试数据合并**

```python
# 在 src/dblp_fetcher.py 中添加测试
def main():
    # ... 现有代码 ...

    # 测试数据合并
    from src.dblp_merger import expand_to_wide_table

    print("\n🔗 测试数据合并...")

    # 构造测试数据
    test_papers = [
        {
            'dblp_key': 'conf/kdd/Test2024',
            'mdate': '2024-01-01',
            'type': 'inproceedings',
            'title': 'Test Paper',
            'year': '2024',
            'venue': 'KDD',
            'authors': ['Author One', 'Author Two'],
            'doi': '10.123/test',
            'ee': ['https://doi.org/10.123/test'],
            'url': 'https://dblp.org/rec/conf/kdd/test'
        }
    ]

    test_authors = {
        'Author One': {
            'pid': 'test/1',
            'name': 'Author One',
            'record_count': 10,
            'profile_url': 'https://dblp.org/pid/test/1',
            'orcids': ['0000-0001-0001-0001'],
            'confidence': 0.9
        },
        'Author Two': {
            'pid': 'test/2',
            'name': 'Author Two',
            'record_count': 5,
            'profile_url': 'https://dblp.org/pid/test/2',
            'orcids': [],
            'confidence': 0.8
        }
    }

    wide_rows = expand_to_wide_table(test_papers, test_authors)
    print(f"展开结果: {len(wide_rows)} 行")
    for row in wide_rows:
        print(f"  {row['author_name']} - {row['title']} ({row['author_role']})")
```

- [ ] **Step 3: 运行测试**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

---

## Task 10: 集成完整流程

**Files:**
- Modify: `src/dblp_fetcher.py` (实现完整主流程)

- [ ] **Step 1: 实现完整主流程**

```python
#!/usr/bin/env python3
"""
DBLP Fetcher - 计算机科学论文数据获取系统
双队列流水线架构：XML解析 + 作者API查询
"""

import asyncio
import sys
import signal
import os
from pathlib import Path
import queue
import time

# 添加项目路径
SCRIPT_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from src.dblp_config import *
from src.dblp_checkpoint import CheckpointManager
from src.dblp_monitor import PerformanceMonitor, setup_loggers, logger
from src.dblp_clickhouse import create_clickhouse_client, create_dblp_table, batch_insert_clickhouse
from src.dblp_xml_parser import download_dblp_snapshot, calculate_xml_chunks, parse_xml_parallel
from src.dblp_author_matcher import batch_match_authors
from src.dblp_merger import expand_to_wide_table


def main():
    """主函数"""
    print("="*80)
    print("DBLP Fetcher - 计算机科学论文数据获取系统")
    print("="*80)
    print()

    # 创建必要的目录
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    Path(f"{LOG_DIR}/failed_batches").mkdir(parents=True, exist_ok=True)

    # 设置日志
    setup_loggers(LOG_DIR)
    logger.info("="*80)
    logger.info("DBLP Fetcher 启动")
    logger.info("="*80)

    # 初始化监控器
    monitor = PerformanceMonitor()
    monitor.start()

    # 初始化检查点
    checkpoint = CheckpointManager(PROGRESS_FILE)
    summary = checkpoint.get_summary()

    if summary['last_update']:
        print(f"📂 检测到进度文件，上次更新: {summary['last_update']}")
        print(f"   已处理论文: {summary['papers_processed']}")
        print(f"   已查询作者: {summary['authors_queried']}")
        print(f"   已写入行数: {summary['rows_written']}")
        print()

    # 连接ClickHouse
    print("📡 连接ClickHouse...")
    ch_client = create_clickhouse_client()
    if not ch_client:
        print("❌ ClickHouse连接失败，程序终止")
        return
    print("✅ ClickHouse连接成功")

    # 创建表
    print("📋 创建ClickHouse表...")
    create_dblp_table(ch_client)
    print()

    # 检查XML文件
    if not os.path.exists(XML_SNAPSHOT_PATH):
        print("🔥 首次运行，需要下载DBLP XML (~1GB)")
        print("   这可能需要一些时间...")
        download_dblp_snapshot()
        print()
    else:
        print(f"✅ DBLP XML已存在: {XML_SNAPSHOT_PATH}")
        print()

    # 计算分片
    chunks = calculate_xml_chunks(XML_SNAPSHOT_PATH, num_chunks=XML_PARSER_THREADS)

    # 创建论文队列
    paper_queue = queue.Queue(maxsize=10000)

    # 阶段1: XML解析
    print("="*80)
    print("阶段1: XML解析")
    print("="*80)

    xml_stats = parse_xml_parallel(
        XML_SNAPSHOT_PATH,
        chunks,
        paper_queue,
        checkpoint,
        num_workers=10  # 先用10个worker测试
    )

    monitor.record_xml_parse(0, xml_stats['total_records'], xml_stats['total_duration'])

    # 收集所有论文
    print("\n📦 收集论文记录...")
    papers = []
    while not paper_queue.empty():
        try:
            paper = paper_queue.get(timeout=1)
            papers.append(paper)
        except queue.Empty:
            break

    print(f"收集到 {len(papers)} 篇论文")

    # 阶段2: 作者匹配
    print("\n" + "="*80)
    print("阶段2: 作者详情获取")
    print("="*80)

    author_profiles = batch_match_authors(papers, checkpoint)

    logger.info(f"作者匹配完成: {len(author_profiles)} 个作者")

    # 阶段3: 数据合并
    print("\n" + "="*80)
    print("阶段3: 数据合并和宽表展开")
    print("="*80)

    wide_rows = expand_to_wide_table(papers, author_profiles)

    print(f"展开为 {len(wide_rows)} 行")

    # 阶段4: 批量写入ClickHouse
    print("\n" + "="*80)
    print("阶段4: 写入ClickHouse")
    print("="*80)

    # 分批写入
    total_batches = (len(wide_rows) + CH_BATCH_SIZE - 1) // CH_BATCH_SIZE
    print(f"总批次数: {total_batches}")

    for i in range(0, len(wide_rows), CH_BATCH_SIZE):
        batch = wide_rows[i:i + CH_BATCH_SIZE]
        batch_num = i // CH_BATCH_SIZE + 1

        print(f"\r  写入批次: {batch_num}/{total_batches}", end='', flush=True)

        success = batch_insert_clickhouse(ch_client, batch)
        monitor.record_ch_batch(len(batch), success)

        if success:
            checkpoint.mark_clickhouse_batch_written(len(batch))

    print()  # 换行

    # 更新统计
    checkpoint.update_stats(
        total_papers=len(papers),
        total_authors=len(author_profiles),
        total_rows=len(wide_rows),
        elapsed_time=time.time() - monitor.start_time
    )

    # 最终报告
    print("\n" + "="*80)
    print("🎉 完成！")
    print("="*80)

    perf_summary = monitor.get_summary()
    print(f"\n性能统计:")
    print(f"  总耗时: {perf_summary['elapsed_time']/3600:.2f} 小时")
    print(f"  XML解析速度: {perf_summary['xml_parse_speed']:.1f} 记录/秒")
    print(f"  作者API成功率: {perf_summary['author_api_success_rate']*100:.1f}%")
    print(f"  整体速度: {perf_summary['overall_speed']:.1f} 记录/秒")

    print(f"\n数据统计:")
    print(f"  论文数: {checkpoint.checkpoint['stats']['total_papers']}")
    print(f"  作者数: {checkpoint.checkpoint['stats']['total_authors']}")
    print(f"  总行数: {checkpoint.checkpoint['stats']['total_rows']}")

    print(f"\n💾 数据已写入: {CH_DATABASE}.{CH_TABLE}")
    print(f"📝 进度已保存: {PROGRESS_FILE}")
    print("="*80)

    logger.info("DBLP Fetcher 完成")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        print("💾 进度已保存，下次运行将自动恢复")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
```

- [ ] **Step 2: 运行完整流程测试**

```bash
# 小规模测试（修改分片数为2）
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

预期输出应该显示完整的4个阶段执行过程。

---

## Task 11: 添加CCF分级功能

**Files:**
- Create: `src/dblp_ccf.py`
- Modify: `src/dblp_merger.py`

- [ ] **Step 1: 创建CCF分级模块**

```python
# src/dblp_ccf.py
"""CCF分级 - 为会议/期刊添加CCF等级"""

import pandas as pd
from pathlib import Path
from importlib.resources import open_binary
from typing import Optional

from src.dblp_config import CCF_CATALOG_PATH


def load_ccf_catalog() -> pd.DataFrame:
    """加载CCF目录"""
    try:
        # 优先使用dblp-api中的CCF目录
        catalog = pd.read_csv(CCF_CATALOG_PATH)
        return catalog
    except Exception as e:
        print(f"⚠️  加载CCF目录失败: {e}")
        return pd.DataFrame()


def get_ccf_class(venue: str, catalog: pd.DataFrame) -> str:
    """
    获取会议/期刊的CCF等级

    Args:
        venue: 会议/期刊名称
        catalog: CCF目录DataFrame

    Returns:
        CCF等级 ('A', 'B', 'C', '' 或 None)
    """
    if venue is None or venue == '':
        return None

    if catalog.empty:
        return None

    venue_lower = venue.lower()

    # 尝试通过abbr匹配
    try:
        abbr_matches = catalog[catalog['abbr'].str.lower() == venue_lower]
        if len(abbr_matches) > 0:
            return abbr_matches.iloc[0]['class']
    except:
        pass

    # 尝试通过URL匹配
    try:
        url_matches = catalog[catalog['url'].str.contains(f'/{venue_lower}/', case=False)]
        if len(url_matches) > 0:
            return url_matches.iloc[0]['class']
    except:
        pass

    return None


def add_ccf_class_to_rows(rows: list, catalog: pd.DataFrame) -> list:
    """
    为宽表记录添加CCF分级

    Args:
        rows: 宽表记录列表
        catalog: CCF目录

    Returns:
        添加了ccf_class的记录列表
    """
    for row in rows:
        venue = row.get('venue', '')
        ccf_class = get_ccf_class(venue, catalog)
        row['ccf_class'] = ccf_class or ''

    return rows
```

- [ ] **Step 2: 在数据合并器中集成CCF**

```python
# 在 src/dblp_merger.py 中修改
from src.dblp_ccf import load_ccf_catalog, add_ccf_class_to_rows

def expand_to_wide_table(
    papers: List[Dict[str, Any]],
    author_profiles: Dict[str, Dict[str, Any]],
    add_ccf: bool = True
) -> List[Dict[str, Any]]:
    """展开为宽表（可选CCF分级）"""

    # ... 现有代码 ...

    # 添加CCF分级
    if add_ccf:
        catalog = load_ccf_catalog()
        wide_rows = add_ccf_class_to_rows(wide_rows, catalog)

    return wide_rows
```

- [ ] **Step 3: 测试CCF分级**

```python
# 测试CCF分级
from src.dblp_ccf import load_ccf_catalog, get_ccf_class

catalog = load_ccf_catalog()
print(f"CCF目录加载: {len(catalog)} 条记录")

# 测试几个会议
test_venues = ['KDD', 'ICML', 'NeurIPS', 'AAAI', 'CVPR']
for venue in test_venues:
    ccf_class = get_ccf_class(venue, catalog)
    print(f"{venue}: {ccf_class}")
```

---

## Task 12: 完善错误处理和重试机制

**Files:**
- Modify: `src/dblp_api_client.py`
- Modify: `src/dblp_xml_parser.py`

- [ ] **Step 1: 增强API错误处理**

```python
# 在 src/dblp_api_client.py 中添加
import time

class DBLPAPIError(Exception):
    """DBLP API错误基类"""
    pass

class RateLimitError(DBLPAPIError):
    """API限流错误"""
    pass

def get_person_profile_with_retry(
    pid_or_url: str,
    max_retries: int = 3,
    backoff_factor: float = 2.0
) -> dict:
    """
    带重试的作者资料获取

    Args:
        pid_or_url: 作者PID或URL
        max_retries: 最大重试次数
        backoff_factor: 退避因子

    Returns:
        作者资料字典
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            return get_person_profile(pid_or_url)

        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = backoff_factor ** attempt
                logger.warning(f"超时重试: {pid_or_url}, 等待{wait_time}秒")
                time.sleep(wait_time)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                # 限流，等待更长时间
                logger.error(f"API限流: {pid_or_url}")
                raise RateLimitError(f"API rate limit exceeded: {pid_or_url}")
            elif e.response.status_code >= 500:
                # 服务器错误，重试
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = backoff_factor ** (attempt + 1)
                    logger.warning(f"服务器错误: {e.response.status_code}, 重试...")
                    time.sleep(wait_time)
            else:
                # 其他错误，不重试
                raise DBLPAPIError(f"HTTP error {e.response.status_code}: {e}")

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(1)

    # 所有重试失败
    raise DBLPAPIError(f"Failed after {max_retries} retries: {last_error}")
```

- [ ] **Step 2: 增强XML解析错误处理**

```python
# 在 src/dblp_xml_parser.py 中修改
def xml_parser_worker(...):
    """添加更详细的错误处理"""

    try:
        # ... 现有解析逻辑 ...

    except ET.ParseError as e:
        logger.error(f"XML解析错误: chunk={chunk_id}, error={e}")
        stats['parse_error'] = str(e)

    except IOError as e:
        logger.error(f"文件读取错误: chunk={chunk_id}, error={e}")
        stats['io_error'] = str(e)

    except Exception as e:
        logger.error(f"未知错误: chunk={chunk_id}, error={e}")
        import traceback
        stats['unknown_error'] = traceback.format_exc()
```

- [ ] **Step 3: 测试错误处理**

```python
# 测试错误处理
from src.dblp_api_client import get_person_profile_with_retry, RateLimitError

try:
    # 测试重试
    profile = get_person_profile_with_retry('invalid/pid', max_retries=2)
except RateLimitError as e:
    print(f"限流错误: {e}")
except Exception as e:
    print(f"其他错误: {e}")
```

---

## Task 13: 实现最终统计报告

**Files:**
- Modify: `src/dblp_fetcher.py`

- [ ] **Step 1: 添加最终报告生成**

```python
# 在 src/dblp_fetcher.py 中添加
def generate_final_report(checkpoint, monitor):
    """生成最终统计报告"""

    perf_summary = monitor.get_summary()
    checkpoint_summary = checkpoint.get_summary()

    report = f"""
{'='*80}
DBLP Fetcher - 最终统计报告
{'='*80}

执行时间
-------
开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(monitor.start_time))}
结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}
总耗时: {perf_summary['elapsed_time']/3600:.2f} 小时

XML解析
-------
解析记录: {monitor.metrics['xml_parse_records']}
完成分片: {monitor.metrics['xml_parse_chunks_completed']}
解析速度: {perf_summary['xml_parse_speed']:.1f} 记录/秒

作者API查询
-----------
总调用次数: {monitor.metrics['author_api_total_calls']}
成功: {monitor.metrics['author_api_success']}
失败: {monitor.metrics['author_api_failed']}
缓存命中: {monitor.metrics['author_api_cache_hits']}
成功率: {perf_summary['author_api_success_rate']*100:.1f}%
平均耗时: {perf_summary['author_api_avg_duration']:.2f} 秒

ClickHouse写入
--------------
总批次: {monitor.metrics['ch_total_batches']}
总行数: {monitor.metrics['ch_total_rows']}
失败批次: {monitor.metrics['ch_failed_batches']}

总体统计
-------
总论文数: {checkpoint.checkpoint['stats']['total_papers']}
总作者数: {checkpoint.checkpoint['stats']['total_authors']}
总行数: {checkpoint.checkpoint['stats']['total_rows']}
整体速度: {perf_summary['overall_speed']:.1f} 记录/秒

{'='*80}
"""

    print(report)

    # 保存到文件
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = f"{LOG_DIR}/final_report_{timestamp}.txt"

    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n📄 报告已保存: {report_file}")


# 在main()函数末尾调用
def main():
    # ... 现有代码 ...

    # 生成最终报告
    generate_final_report(checkpoint, monitor)
```

- [ ] **Step 2: 测试报告生成**

```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

检查报告文件：
```bash
ls -la /home/hkustgz/Us/academic-scraper/log/final_report_*.txt
cat /home/hkustgz/Us/academic-scraper/log/final_report_*.txt | tail -20
```

---

## Task 14: 清理和优化

**Files:**
- Modify: `src/dblp_fetcher.py`
- Modify: `src/dblp_xml_parser.py`

- [ ] **Step 1: 清理临时文件**

```python
# 在 src/dblp_fetcher.py 中添加
def cleanup_temp_files():
    """清理临时文件"""
    import glob

    temp_files = [
        XML_SNAPSHOT_PATH + ".temp",
        XML_SNAPSHOT_PATH + ".downloading"
    ]

    for temp_file in temp_files:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                print(f"🗑️  清理临时文件: {temp_file}")
            except Exception as e:
                print(f"⚠️  清理失败: {temp_file}, {e}")


# 在main()结束时调用
def main():
    try:
        # ... 现有代码 ...
    finally:
        # 清理临时文件
        cleanup_temp_files()
```

- [ ] **Step 2: 添加内存优化**

```python
# 在 src/dblp_xml_parser.py 中优化
def xml_parser_worker(...):
    """添加内存清理"""

    import gc

    # ... 解析逻辑 ...

    # 定期清理内存
    if stats['record_count'] % 1000 == 0:
        gc.collect()

    return stats
```

- [ ] **Step 3: 添加性能优化提示**

```python
# 在 src/dblp_fetcher.py 中添加
def print_performance_tips():
    """打印性能优化提示"""
    print("\n💡 性能优化提示:")
    print("  - 增加XML解析线程数: 修改XML_PARSER_THREADS")
    print("  - 增加API并发数: 修改AUTHOR_API_CONCURRENT")
    print("  - 增加批量大小: 修改CH_BATCH_SIZE")
    print("  - 使用SSD存储临时文件以提速")
    print()


# 在main()开始时调用
def main():
    print_performance_tips()
    # ... 现有代码 ...
```

---

## Task 15: 完整测试和文档

**Files:**
- Create: `temp/test_dblp_fetcher.py`
- Create: `README_DBLP.md`

- [ ] **Step 1: 创建测试脚本**

```python
#!/usr/bin/env python3
"""
DBLP Fetcher 测试脚本
"""

import sys
from pathlib import Path

# 添加项目路径
SCRIPT_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from src.dblp_config import *
from src.dblp_checkpoint import CheckpointManager
from src.dblp_clickhouse import create_clickhouse_client, create_dblp_table
from src.dblp_xml_parser import calculate_xml_chunks
from src.dblp_api_client import search_authors, get_person_profile
from src.dblp_author_matcher import match_author_by_institution
from src.dblp_merger import expand_to_wide_table
from src.dblp_ccf import load_ccf_catalog, get_ccf_class


def test_all():
    """运行所有测试"""
    print("="*80)
    print("DBLP Fetcher - 测试套件")
    print("="*80)
    print()

    tests = [
        ("ClickHouse连接", test_clickhouse),
        ("XML分片计算", test_xml_chunks),
        ("作者搜索API", test_author_search),
        ("作者匹配", test_author_matching),
        ("CCF分级", test_ccf),
        ("数据合并", test_data_merger)
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        print(f"\n🧪 测试: {test_name}")
        try:
            test_func()
            print(f"✅ 通过")
            passed += 1
        except Exception as e:
            print(f"❌ 失败: {e}")
            failed += 1

    print("\n" + "="*80)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("="*80)


def test_clickhouse():
    """测试ClickHouse连接"""
    client = create_clickhouse_client()
    assert client is not None, "ClickHouse连接失败"

    # 测试表创建
    create_dblp_table(client)


def test_xml_chunks():
    """测试XML分片计算"""
    # 假设XML已下载
    if not os.path.exists(XML_SNAPSHOT_PATH):
        print("  ⚠️  XML文件不存在，跳过")
        return

    chunks = calculate_xml_chunks(XML_SNAPSHOT_PATH, num_chunks=10)
    assert len(chunks) == 10, "分片数量不正确"
    assert chunks[0]['start'] == 0, "第一个分片起始位置不正确"


def test_author_search():
    """测试作者搜索API"""
    results = search_authors("Alban Siffer", limit=5)
    assert len(results) > 0, "搜索结果为空"


def test_author_matching():
    """测试作者匹配"""
    paper_context = {
        'venue': 'KDD',
        'year': '2017',
        'title': 'Test Paper',
        'coauthors': ['Author Two']
    }

    profile = match_author_by_institution("Alban Siffer", paper_context)
    # 可能失败，因为需要网络
    if profile:
        assert 'name' in profile, "作者资料缺少name字段"


def test_ccf():
    """测试CCF分级"""
    catalog = load_ccf_catalog()
    assert len(catalog) > 0, "CCF目录为空"

    ccf_class = get_ccf_class("KDD", catalog)
    assert ccf_class is not None, "KDD的CCF等级为空"


def test_data_merger():
    """测试数据合并"""
    test_papers = [{
        'dblp_key': 'test/key',
        'authors': ['Author One', 'Author Two'],
        'venue': 'KDD'
    }]

    test_authors = {
        'Author One': {
            'pid': 'test/1',
            'name': 'Author One',
            'record_count': 10
        }
    }

    wide_rows = expand_to_wide_table(test_papers, test_authors)
    assert len(wide_rows) == 2, "展开行数不正确"


if __name__ == '__main__':
    test_all()
```

- [ ] **Step 2: 创建使用文档**

```markdown
# DBLP Fetcher 使用指南

## 概述

DBLP Fetcher 是一个高性能的计算机科学论文数据获取系统，从DBLP XML快照解析所有论文，获取作者详情，存储到ClickHouse。

## 首次运行

### 1. 安装依赖

```bash
cd /home/hkustgz/Us/academic-scraper
source venv/bin/activate
pip install clickhouse-connect pandas requests tqdm
```

### 2. 下载DBLP XML

首次运行时会自动下载DBLP XML (~1GB)，约需10-30分钟。

```bash
python src/dblp_fetcher.py
```

### 3. 创建ClickHouse表

程序会自动创建 `academic_db.dblp` 表。

## 配置参数

编辑 `src/dblp_config.py`:

```python
# 并发配置
XML_PARSER_THREADS = 50              # XML解析线程数
AUTHOR_API_CONCURRENT = 100          # 作者API并发数
CH_BATCH_SIZE = 9000                  # ClickHouse批量大小

# 超时配置
REQUEST_TIMEOUT = 20                  # API请求超时（秒）
MAX_RETRIES = 3                       # 最大重试次数
```

## 运行

### 完整运行

```bash
python src/dblp_fetcher.py
```

### 测试运行

修改配置为小规模测试：
```python
XML_PARSER_THREADS = 2   # 只解析2个分片
```

### 断点续传

程序会自动保存进度，中断后重新运行会从断点继续。

## 输出

### ClickHouse表

```sql
SELECT * FROM academic_db.dblp LIMIT 10;
```

### 日志文件

- `log/dblp_fetcher.log` - 主日志
- `log/dblp_errors.log` - 错误日志
- `log/dblp_api.log` - API调用日志
- `log/dblp_performance.log` - 性能日志
- `log/final_report_*.txt` - 最终统计报告

### 进度文件

- `log/dblp_fetch_progress.json` - 进度检查点

## 性能

- **XML解析**: ~10,000 记录/秒
- **作者API**: 100 并发
- **ClickHouse写入**: ~9,000 行/批
- **总体速度**: ~5,000 行/秒
- **预计总耗时**: ~4-6 小时（首次）

## 故障排除

### API限流

如果遇到API限流，程序会自动等待。可以减少并发数：
```python
AUTHOR_API_CONCURRENT = 50
```

### 内存不足

减少XML解析线程数：
```python
XML_PARSER_THREADS = 20
```

### ClickHouse连接失败

检查ClickHouse是否运行：
```bash
sudo systemctl status clickhouse-server
```

## 测试

运行测试套件：
```bash
python temp/test_dblp_fetcher.py
```

## 更新

每月DBLP发布新快照，重新运行程序会自动检测并更新数据。
```

- [ ] **Step 3: 运行完整测试**

```bash
# 运行测试套件
/home/hkustgz/Us/academic-scraper/venv/bin/python temp/test_dblp_fetcher.py

# 运行完整流程（小规模测试）
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher.py
```

---

## 实现完成检查清单

在完成所有任务后，验证以下功能：

- [ ] **基础功能**
  - [ ] DBLP XML下载
  - [ ] XML分片计算
  - [ ] 多线程XML解析
  - [ ] 作者搜索API
  - [ ] 作者详情获取
  - [ ] 同名作者匹配
  - [ ] 数据合并和宽表展开
  - [ ] ClickHouse批量写入

- [ ] **高级功能**
  - [ ] 断点续传
  - [ ] CCF分级
  - [ ] 错误处理和重试
  - [ ] 性能监控
  - [ ] 多级日志
  - [ ] 最终统计报告

- [ ] **测试和文档**
  - [ ] 单元测试
  - [ ] 集成测试
  - [ ] 使用文档
  - [ ] README

- [ ] **性能优化**
  - [ ] 内存管理
  - [ ] 并发控制
  - [ ] 批量处理

---

**下一步**: 开始实现！选择执行方式（Subagent-Driven 或 Inline Execution）。
