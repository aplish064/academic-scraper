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
