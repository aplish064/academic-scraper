#!/usr/bin/env python3
"""
专利自动获取工具 - 多源并行
- Google Patents 批量下载
- USPTO API 补充
- EPO OPS API 补充
- 按发明人展开，写入 ClickHouse
"""

import asyncio
import httpx
import time
import sys
import json
import os
import gc
import clickhouse_connect
import csv
import traceback
from dateutil.parser import parse
from typing import List, Dict, Any
from datetime import datetime
from tqdm.asyncio import tqdm
import aiofiles
import aiohttp
from pathlib import Path


def handle_error(error: Exception, context: str = ""):
    """统一错误处理"""
    error_msg = f"错误: {context} - {str(error)}"

    if isinstance(error, KeyboardInterrupt):
        log_message("用户中断")
        raise
    elif isinstance(error, MemoryError):
        log_message(f"内存不足: {error_msg}")
        log_message("建议减少并发数或分批处理")
    elif isinstance(error, ConnectionError):
        log_message(f"网络连接错误: {error_msg}")
    else:
        log_message(f"未知错误: {error_msg}")
        log_message(f"详细信息: {traceback.format_exc()}")

    return error_msg

# ========== 配置 ==========

# 数据目录
DATA_DIR = "/home/hkustgz/Us/academic-scraper/data"
OUTPUT_DIR = "/home/hkustgz/Us/academic-scraper/output/patents"
LOG_DIR = "/home/hkustgz/Us/academic-scraper/log"

# Google Patents 配置
GOOGLE_PATENTS_DATA_DIR = os.path.join(DATA_DIR, "google_patents")
DATASET_START_YEAR = 2023
DATASET_END_YEAR = 1936

# API 配置
USPTO_API_BASE = "https://developer.uspto.gov/api/patents"
EPO_OPS_BASE = "https://ops.epo.org/3.2"

# 并发配置
MAX_CONCURRENT_DOWNLOADS = 3
MAX_CONCURRENT_REQUESTS = 20
REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 3

# ClickHouse 配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'Patents'
CH_USERNAME = 'default'
CH_PASSWORD = ''

# 进度文件
PROGRESS_FILE = os.path.join(LOG_DIR, "patent_fetch_progress.json")
LOG_FILE = os.path.join(LOG_DIR, "patent_fetch.log")
STATS_FILE = os.path.join(LOG_DIR, "patent_statistics.json")


# ========== 工具函数 ==========

def safe_int(value, default=0):
    """安全地转换为整数"""
    try:
        return int(value) if value and str(value).strip() else default
    except (ValueError, TypeError):
        return default


def load_progress() -> Dict[str, Any]:
    """加载进度文件"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            log_message(f"加载进度文件失败: {str(e)}")
    return {
        'current_phase': 'init',
        'phases': {
            'google_dataset_download': {'status': 'pending', 'completed_files': [], 'total_files': 0},
            'uspto_api_supplement': {'status': 'pending', 'completed_patents': [], 'total_to_process': 0},
            'epo_ops_supplement': {'status': 'pending', 'completed_patents': [], 'total_to_process': 0}
        },
        'last_update': None
    }


def save_progress(progress: Dict[str, Any]):
    """保存进度文件"""
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    progress['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def setup_logging():
    """设置日志"""
    os.makedirs(LOG_DIR, exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"\n{'='*80}\n"
    log_message += f"开始时间: {timestamp}\n"
    log_message += f"获取范围: {DATASET_START_YEAR} → {DATASET_END_YEAR}\n"
    log_message += f"并发数: {MAX_CONCURRENT_REQUESTS}\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_message(msg: str):
    """记录日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {msg}\n"
    print(log_line.strip())
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line)


def get_clickhouse_client():
    """获取 ClickHouse 客户端"""
    return clickhouse_connect.get_client(
        host=CH_HOST,
        port=CH_PORT,
        database=CH_DATABASE,
        username=CH_USERNAME,
        password=CH_PASSWORD
    )


# ========== 数据展开函数 ==========

def expand_patent_by_inventors(patent_data: Dict) -> List[Dict]:
    """将专利数据按发明人展开"""
    inventors = patent_data.get('inventors', [])

    if not inventors:
        # 无发明人信息，返回一行空发明人
        return [{
            'inventor_name': '',
            'inventor_rank': 0,
            **{k: v for k, v in patent_data.items() if k != 'inventors'}
        }]

    rows = []
    for rank, inventor in enumerate(inventors, start=1):
        row = {
            'inventor_name': inventor,
            'inventor_rank': rank,
            **{k: v for k, v in patent_data.items() if k != 'inventors'}
        }
        rows.append(row)
    return rows


async def download_google_patents_dataset() -> Dict[str, Any]:
    """下载 Google Patents 公开数据集"""
    log_message("开始下载 Google Patents 数据集")

    os.makedirs(GOOGLE_PATENTS_DATA_DIR, exist_ok=True)
    progress = load_progress()

    # Google Patents Public Data 下载链接
    base_url = "https://patents.google.com"

    # 生成年份列表
    years = list(range(DATASET_START_YEAR, DATASET_END_YEAR + 1))

    downloaded_files = []
    failed_files = []

    # 创建并发限制信号量
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

    async def download_with_limit(url, filename, year):
        async with semaphore:
            return await download_single_file(url, filename, year)

    # 创建下载任务
    download_tasks = []
    for year in years:
        filename = f"google_patents_{year}.tsv"
        url = f"{base_url}/download/patents/{year}"

        download_tasks.append(download_with_limit(url, filename, year))

    # 并发下载
    results = await asyncio.gather(*download_tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            log_message(f"下载异常: {type(result).__name__}: {str(result)}")
            failed_files.append(str(result))
        elif result:
            downloaded_files.append(result)

    # 更新进度
    progress['phases']['google_dataset_download']['status'] = 'completed'
    progress['phases']['google_dataset_download']['completed_files'] = downloaded_files
    progress['phases']['google_dataset_download']['total_files'] = len(years)
    save_progress(progress)

    log_message(f"下载完成: {len(downloaded_files)} 个文件, {len(failed_files)} 个失败")

    return {
        'downloaded': downloaded_files,
        'failed': failed_files
    }


async def download_single_file(url: str, filename: str, year: int) -> str:
    """下载单个文件（带重试机制）"""
    file_path = os.path.join(GOOGLE_PATENTS_DATA_DIR, str(year), filename)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # 检查文件是否已存在
    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
        if file_size > 1000:  # 大于 1KB 认为下载成功
            log_message(f"文件已存在: {filename}")
            return file_path

    log_message(f"开始下载: {filename}")

    # 重试逻辑
    for attempt in range(MAX_RETRIES):
        try:
            timeout = aiohttp.ClientTimeout(total=3600)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        async with aiofiles.open(file_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(1024 * 1024):
                                await f.write(chunk)

                        file_size = os.path.getsize(file_path)
                        log_message(f"下载完成: {filename} ({file_size / 1024 / 1024:.2f} MB)")
                        return file_path
                    else:
                        log_message(f"下载失败: {filename}, 状态码: {response.status}")
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = 2 ** attempt
                log_message(f"下载失败，{wait_time}秒后重试 ({attempt + 1}/{MAX_RETRIES}): {filename}")
                await asyncio.sleep(wait_time)
            else:
                log_message(f"下载失败，已达最大重试次数: {filename}")
                raise
        except Exception as e:
            log_message(f"下载异常: {filename}, 错误: {type(e).__name__}: {str(e)}")
            raise


# ========== TSV 解析函数 ==========

def parse_google_patents_tsv(file_path: str) -> List[Dict]:
    """解析 Google Patents TSV 文件"""
    log_message(f"开始解析: {file_path}")

    patents = []
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f, delimiter='\t')

        for row_num, row in enumerate(reader, 1):
            try:
                patent_data = {
                    'patent_id': row.get('patent_id', ''),
                    'title': row.get('title', ''),
                    'inventors': parse_array_field(row.get('inventors', '')),
                    'applicants': parse_array_field(row.get('applicants', '')),
                    'assignees': parse_array_field(row.get('assignees', '')),
                    'application_date': parse_date(row.get('application_date')),
                    'publication_date': parse_date(row.get('publication_date')),
                    'grant_date': parse_date(row.get('grant_date')),
                    'patent_type': row.get('patent_type', 'unknown'),
                    'classifications': parse_array_field(row.get('classifications', '')),
                    'citations': safe_int(row.get('citations', 0)),
                    'family_size': safe_int(row.get('family_size', 1)),
                    'source': 'google_patents',
                    'fetched_at': datetime.now()
                }
                patents.append(patent_data)
            except Exception as e:
                log_message(f"解析第 {row_num} 行失败: {str(e)}\n{traceback.format_exc()}")
                continue

    log_message(f"解析完成: {len(patents)} 条专利")
    return patents


def parse_array_field(array_str: str) -> List[str]:
    """解析数组或分隔符分隔的字符串"""
    if not array_str:
        return []

    array_str = array_str.strip()

    if array_str.startswith('['):
        try:
            return json.loads(array_str.replace("'", '"'))
        except json.JSONDecodeError:
            pass

    return [item.strip() for item in array_str.split(';') if item.strip()]


def parse_date(date_str: str) -> str:
    """解析日期字符串"""
    if not date_str:
        return None

    try:
        dt = parse(date_str)
        return dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return date_str


# ========== ClickHouse 批量插入 ==========

BATCH_SIZE = 10000


def batch_insert_patents(client, patents: List[Dict]) -> int:
    """批量插入专利数据到 ClickHouse"""
    log_message(f"开始插入 {len(patents)} 条专利")

    inserted_rows = 0

    for i in range(0, len(patents), BATCH_SIZE):
        batch = patents[i:i + BATCH_SIZE]

        # 按发明人展开
        expanded_rows = []
        for patent in batch:
            expanded = expand_patent_by_inventors(patent)
            expanded_rows.extend(expanded)

        # 转换为 ClickHouse 格式
        ch_rows = []
        for row in expanded_rows:
            ch_row = (
                row['inventor_name'],
                row['inventor_rank'],
                row['patent_id'],
                row['title'],
                row['applicants'],
                row['assignees'],
                row['application_date'],
                row['publication_date'],
                row['grant_date'],
                row['patent_type'],
                row['classifications'],
                row['citations'],
                row['family_size'],
                row['source'],
                row['fetched_at']
            )
            ch_rows.append(ch_row)

        # 批量插入
        try:
            client.execute(f'INSERT INTO {CH_TABLE} VALUES', ch_rows)
            inserted_rows += len(ch_rows)
            log_message(f"已插入 {inserted_rows}/{len(patents)} 行")
        except Exception as e:
            log_message(f"插入失败: {str(e)}\n{traceback.format_exc()}")
            continue

        # 释放内存
        del ch_rows
        del batch
        del expanded_rows

    log_message(f"插入完成: {inserted_rows} 行")
    return inserted_rows


async def process_google_patents_file(file_path: str, client) -> Dict[str, int]:
    """处理单个 Google Patents 文件"""
    log_message(f"开始处理文件: {file_path}")

    # 解析文件
    patents = parse_google_patents_tsv(file_path)

    if not patents:
        log_message(f"文件为空或解析失败: {file_path}")
        return {'patent_count': 0, 'row_count': 0}

    patent_count = len(patents)

    # 批量插入
    row_count = batch_insert_patents(client, patents)

    # 释放内存
    del patents
    gc.collect()

    # 更新进度
    progress = load_progress()
    if 'processed_files' not in progress['phases']:
        progress['phases']['processed_files'] = []
    if file_path not in progress['phases']['processed_files']:
        progress['phases']['processed_files'].append(file_path)
    save_progress(progress)

    return {
        'patent_count': patent_count,
        'row_count': row_count
    }


# ========== USPTO API 补充功能 ==========

async def fetch_uspto_patent(patent_id: str, session: httpx.AsyncClient) -> Dict:
    """从 USPTO API 获取单个专利信息"""
    # 提取专利号（移除 US 前缀和后缀）
    clean_id = patent_id.replace('US', '').split('-')[0].split('A')[0].split('B')[0]

    # TODO: Verify correct USPTO API endpoint path
    url = f"{USPTO_API_BASE}"  # May need to add specific endpoint path
    params = {
        'patentNumber': clean_id,
        'api_key': ''
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = await session.get(url, params=params, timeout=REQUEST_TIMEOUT)

            if response.status_code == 200:
                data = response.json()

                # 解析 USPTO 响应（根据实际 API 响应格式调整）
                patent_data = {
                    'patent_id': patent_id,
                    'title': data.get('title', ''),
                    'inventors': parse_uspto_inventors(data.get('inventors', [])),
                    'applicants': [data.get('assignee', {}).get('name', '')],
                    'assignees': [data.get('assignee', {}).get('name', '')],
                    'application_date': parse_date(data.get('applicationDate')),
                    'publication_date': parse_date(data.get('grantDate')),
                    'grant_date': parse_date(data.get('grantDate')),
                    'patent_type': data.get('patentType', 'utility'),
                    # TODO: Verify correct field for classifications in USPTO API response
                    'classifications': parse_uspto_classifications(data.get('citations', [])),
                    'citations': len(data.get('citations', [])),
                    'family_size': 1,
                    'source': 'uspto_api',
                    'fetched_at': datetime.now()
                }

                return patent_data

            elif response.status_code == 404:
                log_message(f"专利不存在: {patent_id}")
                return None

            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                log_message(f"USPTO API 限流，等待 {retry_after} 秒")
                await asyncio.sleep(retry_after)
                continue

            else:
                log_message(f"USPTO API 错误: {patent_id}, 状态码: {response.status_code}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    return None

        except Exception as e:
            log_message(f"USPTO API 请求异常: {patent_id}, 错误: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                return None

    return None


def parse_uspto_inventors(inventors_data: list) -> List[str]:
    """解析 USPTO 发明人数据"""
    inventors = []
    for inv in inventors_data:
        name = inv.get('name', '')
        if name:
            inventors.append(name)
    return inventors


def parse_uspto_classifications(citations_data: list) -> List[str]:
    """解析 USPTO 分类号"""
    classifications = []
    for cit in citations_data:
        cpc = cit.get('cpc', {})
        classification = cpc.get('classification', '')
        if classification:
            classifications.append(classification)
    return classifications


async def supplement_uspto_data(client, limit: int = 100):
    """使用 USPTO API 补充美国专利数据"""
    log_message("开始 USPTO API 补充")

    progress = load_progress()

    # 查询需要补充的美国专利
    result = client.query('''
        SELECT DISTINCT patent_id
        FROM Patents
        WHERE patent_id LIKE 'US%'
        AND source = 'google_patents'
        LIMIT {}
    '''.format(limit))

    us_patents = [row[0] for row in result.result_rows]

    if not us_patents:
        log_message("没有需要补充的美国专利")
        return

    log_message(f"需要补充的美国专利: {len(us_patents)} 条")

    completed_patents = progress['phases']['uspto_api_supplement'].get('completed_patents', [])

    # 过滤已完成的
    pending_patents = [p for p in us_patents if p not in completed_patents]

    log_message(f"待补充的美国专利: {len(pending_patents)} 条")

    # 创建 HTTP 客户端
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as session:
        # 批量查询
        updated_count = 0

        for i in range(0, len(pending_patents), MAX_CONCURRENT_REQUESTS):
            batch = pending_patents[i:i + MAX_CONCURRENT_REQUESTS]

            tasks = [fetch_uspto_patent(patent_id, session) for patent_id in batch]
            results = await asyncio.gather(*tasks)

            for patent_id, patent_data in zip(batch, results):
                if patent_data:
                    # 删除旧记录
                    client.execute(f"DELETE FROM {CH_TABLE} WHERE patent_id = '{patent_id}'")

                    # 插入新记录
                    expanded = expand_patent_by_inventors(patent_data)
                    ch_rows = []
                    for row in expanded:
                        ch_row = (
                            row['inventor_name'],
                            row['inventor_rank'],
                            row['patent_id'],
                            row['title'],
                            row['applicants'],
                            row['assignees'],
                            row['application_date'],
                            row['publication_date'],
                            row['grant_date'],
                            row['patent_type'],
                            row['classifications'],
                            row['citations'],
                            row['family_size'],
                            row['source'],
                            row['fetched_at']
                        )
                        ch_rows.append(ch_row)

                    client.execute(f'INSERT INTO {CH_TABLE} VALUES', ch_rows)
                    updated_count += 1
                    log_message(f"更新成功: {patent_id}")
                    completed_patents.append(patent_id)  # Only add if successful

            # 更新进度
            progress['phases']['uspto_api_supplement']['completed_patents'] = completed_patents
            progress['phases']['uspto_api_supplement']['total_to_process'] = len(us_patents)
            save_progress(progress)

            # 避免请求过快
            await asyncio.sleep(1)

    log_message(f"USPTO API 补充完成: {updated_count} 条专利")


# ========== 统计和报告功能 ==========

def generate_statistics(client) -> Dict:
    """生成统计信息"""
    stats = {
        'total_patents': 0,
        'total_rows': 0,
        'data_sources': {},
        'coverage': {},
        'date_range': {},
        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    # 总专利数（按 patent_id 去重）
    result = client.query('SELECT count(DISTINCT patent_id) FROM Patents')
    stats['total_patents'] = result.result_rows[0][0]

    # 总行数
    result = client.query('SELECT count(*) FROM Patents')
    stats['total_rows'] = result.result_rows[0][0]

    # 按来源统计
    result = client.query('''
        SELECT source, count(DISTINCT patent_id) as cnt
        FROM Patents
        GROUP BY source
    ''')

    for source, count in result.result_rows:
        stats['data_sources'][source] = count

    # 按国家/地区统计
    result = client.query('''
        SELECT
            substring(patent_id, 1, 2) as country,
            count(DISTINCT patent_id) as cnt
        FROM Patents
        GROUP BY country
        ORDER BY cnt DESC
    ''')

    for country, count in result.result_rows:
        stats['coverage'][country] = count

    # 日期范围
    result = client.query('''
        SELECT
            min(publication_date) as earliest,
            max(publication_date) as latest
        FROM Patents
        WHERE publication_date != ''
    ''')

    if result.result_rows:
        earliest, latest = result.result_rows[0]
        stats['date_range']['earliest'] = earliest
        stats['date_range']['latest'] = latest

    # 保存统计文件
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    return stats


def print_statistics(stats: Dict):
    """打印统计信息"""
    log_message("=" * 80)
    log_message("数据统计报告")
    log_message("=" * 80)

    log_message(f"总专利数: {stats['total_patents']:,}")
    log_message(f"总行数: {stats['total_rows']:,}")
    log_message("")

    log_message("数据源分布:")
    for source, count in stats['data_sources'].items():
        log_message(f"  {source}: {count:,}")

    log_message("")
    log_message("地区分布:")
    for country, count in list(stats['coverage'].items())[:10]:
        log_message(f"  {country}: {count:,}")

    log_message("")
    log_message("日期范围:")
    log_message(f"  最早: {stats['date_range'].get('earliest', 'N/A')}")
    log_message(f"  最新: {stats['date_range'].get('latest', 'N/A')}")

    log_message("=" * 80)


# ========== 主函数 ==========

async def main():
    """主函数"""
    try:
        setup_logging()
        log_message("专利获取器启动")

        progress = load_progress()
        client = get_clickhouse_client()

        # 阶段 1: Google Patents 数据集下载
        if progress['phases']['google_dataset_download']['status'] != 'completed':
            try:
                download_result = await download_google_patents_dataset()
                log_message(f"Google Patents 下载阶段完成")
            except Exception as e:
                handle_error(e, "Google Patents 下载")
                return
        else:
            log_message("Google Patents 下载阶段已完成，跳过")

        # 阶段 2: 处理下载的文件
        if progress['phases']['google_dataset_download']['status'] == 'completed':
            log_message("开始处理下载的文件")

            completed_files = progress['phases']['google_dataset_download'].get('completed_files', [])

            total_patents = 0
            total_rows = 0

            for file_path in completed_files:
                if os.path.exists(file_path):
                    try:
                        result = await process_google_patents_file(file_path, client)
                        total_patents += result['patent_count']
                        total_rows += result['row_count']
                    except Exception as e:
                        handle_error(e, f"处理文件 {file_path}")
                        continue
                else:
                    log_message(f"文件不存在: {file_path}")

            log_message(f"处理完成: {total_patents} 条专利, {total_rows} 行")

        # 阶段 3: USPTO API 补充（可选）
        if progress['phases']['google_dataset_download']['status'] == 'completed':
            log_message("开始 USPTO API 补充")
            try:
                await supplement_uspto_data(client, limit=100)
            except Exception as e:
                handle_error(e, "USPTO API 补充")
                # Don't return - continue to statistics

        # 生成统计报告
        log_message("生成统计报告...")
        stats = generate_statistics(client)
        print_statistics(stats)

        log_message("专利获取器完成")

    except KeyboardInterrupt:
        log_message("用户中断，正在保存进度...")
        progress = load_progress()
        save_progress(progress)
        log_message("进度已保存")
    except Exception as e:
        handle_error(e, "主流程")
        return


if __name__ == '__main__':
    asyncio.run(main())
