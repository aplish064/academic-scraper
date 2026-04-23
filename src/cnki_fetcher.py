#!/usr/bin/env python3
"""
CNKI文献抓取器 - 全异步架构
支持：期刊论文、学位论文、会议论文、专利
"""

import asyncio
import time
import json
import os
import gc
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from tqdm.asyncio import tqdm

# Scrapling imports
from scrapling.fetchers.requests import AsyncFetcher

# ClickHouse
import clickhouse_connect
import pandas as pd

# 创建日志目录
LOG_DIR = "/home/hkustgz/Us/academic-scraper/log"
os.makedirs(LOG_DIR, exist_ok=True)

# ==================== 配置常量 ====================

# 时间范围
START_YEAR = 2000
END_DATE = datetime.now()

# ClickHouse配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'CNKI'
CH_USERNAME = 'default'
CH_PASSWORD = ''

# 并发控制
MAX_CONCURRENT_REQUESTS = 15
BATCH_SIZE = 1000
REQUEST_DELAY = (0.5, 2.0)

# 重试配置
MAX_RETRIES = 3
TIMEOUT = 30.0

# 日志配置
LOG_FILE = os.path.join(LOG_DIR, "cnki_fetch.log")
PROGRESS_FILE = os.path.join(LOG_DIR, "cnki_fetch_progress.json")

# CNKI配置
CNKI_BASE_URL = "https://cnki.net"
CNKI_SEARCH_URL = "https://cnki.net/kns8/search"

# ==================== 进度管理 ====================

def load_progress() -> Dict[str, Any]:
    """加载进度文件"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  加载进度文件失败: {e}")
    return {
        'current_date': None,
        'completed_dates': [],
        'last_update': None,
        'total_papers': 0,
        'total_rows': 0
    }


def save_progress(progress: Dict[str, Any]):
    """保存进度文件"""
    try:
        progress['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️  保存进度文件失败: {e}")

# ==================== 日志系统 ====================

def setup_logging():
    """设置日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"\n{'='*80}\n"
    log_message += f"开始时间: {timestamp}\n"
    log_message += f"抓取范围: {START_YEAR} → {END_DATE.strftime('%Y-%m-%d')}\n"
    log_message += f"并发数: {MAX_CONCURRENT_REQUESTS}\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_fetch_result(date_str: str, paper_count: int, row_count: int):
    """记录每次获取结果到日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] {date_str} | 论文: {paper_count} | 行: {row_count} | 已写入ClickHouse\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_completion(total_papers: int, total_rows: int, success_count: int, skip_count: int, elapsed_time: float):
    """记录完成状态"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"\n{'='*80}\n"
    log_message += f"完成时间: {timestamp}\n"
    log_message += f"总耗时: {elapsed_time:.2f} 秒 ({elapsed_time/3600:.2f} 小时)\n"
    log_message += f"成功: {success_count} 天\n"
    log_message += f"跳过: {skip_count} 天\n"
    log_message += f"总论文: {total_papers} 篇\n"
    log_message += f"总行数: {total_rows} 行\n"
    log_message += f"平均速度: {total_papers/elapsed_time:.1f} 篇/秒\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)