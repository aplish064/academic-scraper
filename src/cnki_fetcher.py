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
import random
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from tqdm.asyncio import tqdm

# Scrapling imports
from scrapling import StealthyFetcher

# HTML parsing
from bs4 import BeautifulSoup

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

# ==================== ClickHouse存储 ====================

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
        # 数据清洗和类型转换
        cleaned_rows = []
        current_import_time = datetime.now()

        for row in rows:
            cleaned_row = {}
            for key, value in row.items():
                # 处理None值
                if value is None:
                    if key in ['rank', 'cited_count', 'download_count']:
                        cleaned_row[key] = 0
                    else:
                        cleaned_row[key] = ''
                # 处理NaN值
                elif isinstance(value, float) and pd.isna(value):
                    if key in ['rank', 'cited_count', 'download_count']:
                        cleaned_row[key] = 0
                    else:
                        cleaned_row[key] = ''
                # 类型转换
                else:
                    cleaned_row[key] = value

            # 添加import_time字段
            cleaned_row['import_time'] = current_import_time
            cleaned_rows.append(cleaned_row)

        # 创建DataFrame
        df = pd.DataFrame(cleaned_rows)

        # 确保数值列的类型正确
        df['rank'] = df['rank'].astype(int)
        df['cited_count'] = df['cited_count'].astype(int)
        df['download_count'] = df['download_count'].astype(int)

        # 确保日期时间列的类型正确
        df['import_time'] = pd.to_datetime(df['import_time'])

        # 使用临时表进行去重
        temp_table = 'temp_cnki_insert_dedup'

        # 创建临时表
        client.command(f'DROP TABLE IF EXISTS {CH_DATABASE}.{temp_table}')
        client.command(f'''
            CREATE TABLE {CH_DATABASE}.{temp_table} AS {CH_DATABASE}.{CH_TABLE}
            ENGINE = Memory
        ''')

        # 插入到临时表
        client.insert_df(f'{CH_DATABASE}.{temp_table}', df)

        # 从临时表插入到目标表，使用DISTINCT去重
        client.command(f'''
            INSERT INTO {CH_DATABASE}.{CH_TABLE}
            SELECT DISTINCT * FROM {CH_DATABASE}.{temp_table}
        ''')

        # 删除临时表
        client.command(f'DROP TABLE {CH_DATABASE}.{temp_table}')

        return True

    except Exception as e:
        print(f"❌ 插入ClickHouse失败: {e}")
        if rows:
            print(f"   示例数据: {rows[0]}")
        import traceback
        traceback.print_exc()
        return False


# ==================== 资源类型识别和解析 ====================

def identify_resource_type(url: str, content: str = "") -> str:
    """
    识别CNKI资源的类型
    返回: 'journal', 'thesis', 'conference', 'patent', 'unknown'
    """
    # 从URL判断
    if 'CJFD' in url or 'nav' in url:
        return 'journal'
    elif 'CDMD' in url or 'CMFD' in url:
        return 'thesis'
    elif 'CPFD' in url:
        return 'conference'
    elif 'SCOD' in url:
        return 'patent'

    # 从内容判断（如果有HTML内容）
    if content:
        soup = BeautifulSoup(content, 'html.parser')

        # 检查页面特征
        if '期刊' in content or 'Journal' in content:
            return 'journal'
        elif '学位论文' in content or 'Thesis' in content or '硕士' in content or '博士' in content:
            return 'thesis'
        elif '会议论文' in content or 'Conference' in content:
            return 'conference'
        elif '专利' in content or 'Patent' in content:
            return 'patent'

    return 'unknown'


def parse_cnki_page(html_content: str, url: str) -> Dict[str, Any]:
    """
    解析CNKI页面，根据资源类型调用相应的解析函数
    TODO: 实现具体的解析逻辑
    """
    resource_type = identify_resource_type(url, html_content)

    if resource_type == 'journal':
        return parse_journal_page(html_content, url)
    elif resource_type == 'thesis':
        return parse_thesis_page(html_content, url)
    elif resource_type == 'conference':
        return parse_conference_page(html_content, url)
    elif resource_type == 'patent':
        return parse_patent_page(html_content, url)
    else:
        return {
            'success': False,
            'error': f'Unknown resource type for URL: {url}',
            'data': None
        }


def parse_journal_page(html_content: str, url: str) -> Dict[str, Any]:
    """
    解析期刊论文页面
    TODO: 提取标题、作者、摘要、关键词、发表时间、期刊名、卷期等
    """
    # TODO: 实现期刊论文的具体解析逻辑
    return {
        'success': False,
        'error': 'Not implemented yet',
        'data': None
    }


def parse_thesis_page(html_content: str, url: str) -> Dict[str, Any]:
    """
    解析学位论文页面
    TODO: 提取标题、作者、导师、学校、摘要、关键词、授予时间等
    """
    # TODO: 实现学位论文的具体解析逻辑
    return {
        'success': False,
        'error': 'Not implemented yet',
        'data': None
    }


def parse_conference_page(html_content: str, url: str) -> Dict[str, Any]:
    """
    解析会议论文页面
    TODO: 提取标题、作者、摘要、关键词、会议名称、会议时间等
    """
    # TODO: 实现会议论文的具体解析逻辑
    return {
        'success': False,
        'error': 'Not implemented yet',
        'data': None
    }


def parse_patent_page(html_content: str, url: str) -> Dict[str, Any]:
    """
    解析专利页面
    TODO: 提取专利名称、发明人、申请人、摘要、专利号、申请日期等
    """
    # TODO: 实现专利的具体解析逻辑
    return {
        'success': False,
        'error': 'Not implemented yet',
        'data': None
    }


# ==================== 抓取引擎 ====================

def create_fetcher():
    """
    创建StealthyFetcher实例，启用隐身模式
    """
    fetcher = StealthyFetcher()
    return fetcher


def fetch_page(url: str, fetcher, retry_count: int = 0) -> Optional[str]:
    """
    抓取页面（同步）

    Args:
        url: 目标URL
        fetcher: StealthyFetcher实例
        retry_count: 当前重试次数

    Returns:
        HTML内容字符串，失败返回None
    """
    try:
        # 使用StealthyFetcher抓取页面
        response = fetcher.get(url)

        if response is None:
            raise Exception("No response received")

        # 获取HTML内容
        html_content = response.text if hasattr(response, 'text') else str(response)

        return html_content

    except Exception as e:
        print(f"❌ 抓取失败 ({retry_count + 1}/{MAX_RETRIES}): {url}")
        print(f"   错误: {e}")

        # 重试逻辑
        if retry_count < MAX_RETRIES - 1:
            delay = min(2 ** retry_count, 10)  # 指数退避，最大10秒
            print(f"   {delay}秒后重试...")
            time.sleep(delay)
            return fetch_page(url, fetcher, retry_count + 1)

        return None


def get_all_dates() -> List[str]:
    """
    生成所有需要抓取的日期列表（YYYY-MM-DD格式）
    从START_YEAR到END_DATE，按日期倒序排列
    """
    dates = []
    current_date = END_DATE

    # 生成日期列表
    while current_date.year >= START_YEAR:
        date_str = current_date.strftime('%Y-%m-%d')
        dates.append(date_str)
        current_date -= timedelta(days=1)

    return dates


# ==================== 主调度逻辑 ====================

async def main_async():
    """
    主异步函数：协调整个抓取流程
    """
    print("="*80)
    print("CNKI文献抓取器启动")
    print("="*80)

    # 初始化
    setup_logging()
    progress = load_progress()
    all_dates = get_all_dates()

    # 过滤已完成的日期
    pending_dates = [d for d in all_dates if d not in progress.get('completed_dates', [])]

    print(f"\n总日期数: {len(all_dates)}")
    print(f"已完成: {len(progress.get('completed_dates', []))}")
    print(f"待处理: {len(pending_dates)}")

    if not pending_dates:
        print("\n✓ 所有日期已完成！")
        return

    # 创建ClickHouse客户端
    client = create_clickhouse_client()
    if not client:
        print("❌ 无法连接ClickHouse，退出")
        return

    # 创建抓取器
    fetcher = create_fetcher()

    # 统计变量
    total_papers = progress.get('total_papers', 0)
    total_rows = progress.get('total_rows', 0)
    success_count = 0
    skip_count = 0

    start_time = time.time()

    # TODO: 实现并发抓取逻辑
    # for date in pending_dates:
    #     # TODO: 构造CNKI搜索URL
    #     # TODO: 抓取页面
    #     # TODO: 解析数据
    #     # TODO: 存入ClickHouse
    #     # TODO: 更新进度
    #     pass

    print("\n" + "="*80)
    print("抓取任务完成（框架已完成，解析逻辑待实现）")
    print("="*80)


def main():
    """
    程序入口点
    """
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断，进度已保存")
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()