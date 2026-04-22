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
