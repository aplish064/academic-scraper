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
