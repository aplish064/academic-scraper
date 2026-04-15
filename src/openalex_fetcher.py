#!/usr/bin/env python3
"""
OpenAlex 论文自动获取工具 - 极速版（按天）
- 异步IO + HTTP/2
- 按天获取，按月写入CSV
- 并发请求
- 预计速度提升 20-50 倍
"""

import asyncio
import httpx
import time
import csv
import sys
import json
import os
import gc
from typing import List, Dict, Any
from datetime import datetime, timedelta
from tqdm.asyncio import tqdm


# OpenAlex API 基础URL
OPENALEX_API_BASE = "https://api.openalex.org"

# API 配置
# OPENALEX_API_KEY = "Q5QcudPogcFTfvV7vFOH1r"  # 您的 API Key
# OPENALEX_EMAIL = "1509901785@qq.com"  # 您的邮箱

# CSV字段（包含机构和质量指标）
CSV_FIELDS = [
    'author_id', 'author', 'uid', 'doi', 'title', 'rank', 'journal',
    'citation_count', 'tag', 'state',
    'institution_id', 'institution_name', 'institution_country', 'institution_type',
    'raw_affiliation',
    'fwci', 'citation_percentile', 'primary_topic', 'is_retracted'
]

# 日志目录和文件
LOG_DIR = "/home/apl064/apl/academic-scraper/log"
LOG_FILE = os.path.join(LOG_DIR, "openalex_fetch_fast.log")
PROGRESS_FILE = os.path.join(LOG_DIR, "openalex_fetch_progress.json")

# 配置
START_DATE = "20260410"  # 从这个日期开始往前获取
END_YEAR = 2010          # 往前获取到这一年

# 并发配置
MAX_CONCURRENT_REQUESTS = 20  # 最大并发请求数（降低以减少内存占用）
REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 3


def load_progress() -> Dict[str, Any]:
    """加载进度文件"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        'current_date': None,
        'completed_dates': [],
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
    log_message += f"获取范围: {START_DATE} → {END_YEAR}（按天获取）\n"
    log_message += f"并发数: {MAX_CONCURRENT_REQUESTS}\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_fetch_result(date_str: str, paper_count: int, row_count: int, csv_file: str):
    """记录每次获取结果到日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] {date_str} | 论文: {paper_count} | 行: {row_count} | 文件: {csv_file}\n"

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


def parse_openalex_work(work: Dict[str, Any]) -> Dict[str, Any]:
    """解析 OpenAlex 作品数据（包含论文发表时的机构信息和质量指标）"""
    # 基本信息
    paper_id = work.get('id', '')
    title = work.get('title', '')
    if title:
        title = title.replace('\n', ' ')

    doi = work.get('doi', None)
    if doi is None:
        doi = ''

    # 作者信息（包含机构信息）
    authors = []
    authorships = work.get('authorships', [])

    for idx, auth in enumerate(authorships):
        author_info = auth.get('author', {})
        if author_info and author_info.get('display_name'):
            # 提取 author ID (格式: https://openalex.org/A1234567890)
            author_id = author_info.get('id', '')
            # 只保留数字部分
            if author_id and '/A' in author_id:
                author_id = author_id.split('/A')[-1]

            # 提取机构信息（论文发表时的机构）
            institutions = auth.get('institutions', [])
            institution_info = {
                'id': '',
                'name': '',
                'country': '',
                'type': '',
                'raw': ''
            }

            # 获取原始归属字符串（论文元数据中的自由文本）
            raw_affiliations = auth.get('raw_affiliation_strings', [])
            if raw_affiliations:
                # 使用第一个原始归属字符串
                institution_info['raw'] = raw_affiliations[0]

            # 如果有已解析的机构，使用第一个机构
            if institutions:
                first_inst = institutions[0]
                inst_id = first_inst.get('id', '')
                if inst_id and '/I' in inst_id:
                    institution_info['id'] = inst_id.split('/I')[-1]
                institution_info['name'] = first_inst.get('display_name', '')
                institution_info['country'] = first_inst.get('country_code', '')
                institution_info['type'] = first_inst.get('type', '')

            authors.append({
                'id': author_id,  # OpenAlex Author ID
                'name': author_info['display_name'],
                'orcid': author_info.get('orcid', ''),
                'rank': idx + 1,
                'institution': institution_info  # 添加机构信息
            })

    # 期刊/会议信息
    primary_location = work.get('primary_location') or {}
    source = primary_location.get('source') or {}
    journal = source.get('display_name', 'unknown')

    # 被引次数
    citation_count = work.get('cited_by_count', 0)

    # 概念/分类
    concepts = work.get('concepts', [])
    categories = [c.get('display_name', '') for c in concepts[:3] if c.get('display_name')]

    # ✅ 新增：质量指标
    # 领域加权影响因子
    fwci = work.get('fwci', 0)

    # 引用百分位
    citation_percentile_obj = work.get('cited_by_percentile_year', {})
    citation_percentile = citation_percentile_obj.get('min', 0) if citation_percentile_obj else 0

    # 主要研究主题
    primary_topic_obj = work.get('primary_topic', {})
    primary_topic = primary_topic_obj.get('display_name', '') if primary_topic_obj else ''

    # 是否撤稿
    is_retracted = work.get('is_retracted', False)

    return {
        'uid': paper_id,
        'doi': doi,
        'title': title,
        'authors': authors,
        'journal': journal,
        'citation_count': citation_count,
        'categories': categories,
        # 新增质量指标
        'fwci': fwci,
        'citation_percentile': citation_percentile,
        'primary_topic': primary_topic,
        'is_retracted': is_retracted
    }


def append_rows_to_csv(rows: List[Dict[str, Any]], filepath: str):
    """
    追加行数据到CSV文件
    每天一个文件，无需考虑并发冲突（不同天写不同文件）
    """
    file_exists = os.path.exists(filepath)

    with open(filepath, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
        if not file_exists:
            writer.writeheader()

        # 一次性写入所有行
        writer.writerows(rows)


async def fetch_openalex_day(
    client: httpx.AsyncClient,
    date_str: str,
    semaphore: asyncio.Semaphore,
    day_pbar: tqdm,
    paper_pbar: tqdm,
    progress: Dict[str, Any],
    progress_lock: asyncio.Lock
) -> Dict[str, Any]:
    """
    异步获取指定日期的所有论文（优化版：分批写入，及时释放内存）

    优化策略：
    1. 每累积 20,000 条论文记录就写入并清空
    2. 每天写入独立文件，避免锁竞争
    3. 文件组织：output/openalex/YYYY_MM/YYYY-MM-DD.csv

    Args:
        client: httpx 异步客户端
        date_str: 日期字符串 (YYYY-MM-DD)
        semaphore: 信号量（控制并发）
        day_pbar: 天数进度条
        paper_pbar: 论文数进度条
        progress: 进度字典
        progress_lock: 进度文件锁

    Returns:
        包含结果的字典
    """
    async with semaphore:
        print(f"📅 正在获取: {date_str}", flush=True)

        all_papers = []
        cursor = '*'
        per_page = 200
        retry_count = 0

        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        csv_file = get_daily_csv_filename(date_str)  # 获取每日CSV文件路径

        # 统计信息
        total_papers = 0
        total_rows = 0
        write_count = 0  # 写入次数统计

        # 分批写入阈值（论文数）
        BATCH_WRITE_THRESHOLD = 9000

        while retry_count < MAX_RETRIES:
            try:
                params = {
                    'filter': f'from_publication_date:{date_str},to_publication_date:{date_str},type:article',
                    'per-page': per_page,
                    'cursor': cursor,
                    # 'api_key': OPENALEX_API_KEY
                }

                response = await client.get(
                    f"{OPENALEX_API_BASE}/works",
                    params=params,
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()

                data = response.json()
                results = data.get('results', [])

                if not results:
                    break

                # 解析论文并添加到当前批次
                for work in results:
                    paper = parse_openalex_work(work)
                    all_papers.append(paper)

                # 更新论文进度条
                paper_pbar.update(len(results))

                # ✅ 关键优化：每累积 20,000 条就写入并清空
                if len(all_papers) >= BATCH_WRITE_THRESHOLD:
                    # 展开为作者行
                    rows = []
                    for paper in all_papers:
                        authors = paper['authors']
                        total_authors = len(authors)

                        for author_info in authors:
                            author_id = author_info.get('id', '')
                            author_name = author_info['name']
                            rank = author_info['rank']

                            tag = '其他'
                            if rank == 1:
                                tag = '第一作者'
                            elif rank == total_authors:
                                tag = '最后作者'

                            rows.append({
                                'author_id': author_id,
                                'author': author_name,
                                'uid': paper['uid'],
                                'doi': paper['doi'],
                                'title': paper['title'],
                                'rank': rank,
                                'journal': paper['journal'],
                                'citation_count': paper['citation_count'],
                                'tag': tag,
                                'state': '',
                                'institution_id': author_info.get('institution', {}).get('id', ''),
                                'institution_name': author_info.get('institution', {}).get('name', ''),
                                'institution_country': author_info.get('institution', {}).get('country', ''),
                                'institution_type': author_info.get('institution', {}).get('type', ''),
                                'raw_affiliation': author_info.get('institution', {}).get('raw', ''),
                                'fwci': paper.get('fwci', 0),
                                'citation_percentile': paper.get('citation_percentile', 0),
                                'primary_topic': paper.get('primary_topic', ''),
                                'is_retracted': paper.get('is_retracted', False)
                            })

                    # 写入CSV
                    append_rows_to_csv(rows, csv_file)

                    # 更新统计
                    total_papers += len(all_papers)
                    total_rows += len(rows)
                    write_count += 1

                    print(f"  💾 [{write_count}] {date_str}: 已写入 {len(all_papers)} 篇论文 → {len(rows)} 行", flush=True)

                    # ✅ 立即释放内存
                    del all_papers
                    del rows
                    gc.collect()

                    # 重新初始化，继续获取
                    all_papers = []

                # 检查是否还有更多结果
                meta = data.get('meta', {})
                next_cursor = meta.get('next_cursor')
                if not next_cursor:
                    break

                cursor = next_cursor
                await asyncio.sleep(0.05)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    try:
                        error_data = e.response.json()
                        if 'Rate limit exceeded' in error_data.get('error', ''):
                            print(f"\n❌ API配额耗尽！")
                            print(f"   {error_data.get('message', '')}")
                            print(f"   重置时间: {error_data.get('retryAfter', 'N/A')} 秒后")
                            print(f"   💾 进度已保存，请等待配额重置后继续")
                            return {
                                'date_str': date_str,
                                'error': 'RATE_LIMIT_EXCEEDED',
                                'fatal': True
                            }
                    except:
                        pass

                    await asyncio.sleep(5)
                    retry_count += 1
                elif e.response.status_code >= 500:
                    await asyncio.sleep(3)
                    retry_count += 1
                else:
                    return {
                        'date_str': date_str,
                        'error': str(e)
                    }

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                await asyncio.sleep(3)
                retry_count += 1

            except Exception as e:
                return {
                    'date_str': date_str,
                    'error': str(e)
                }

        # 更新天数进度条
        day_pbar.update(1)

        # ✅ 处理剩余的论文（不足 20,000 条的部分）
        if all_papers:
            # 展开为作者行
            rows = []
            for paper in all_papers:
                authors = paper['authors']
                total_authors = len(authors)

                for author_info in authors:
                    author_id = author_info.get('id', '')
                    author_name = author_info['name']
                    rank = author_info['rank']

                    tag = '其他'
                    if rank == 1:
                        tag = '第一作者'
                    elif rank == total_authors:
                        tag = '最后作者'

                    rows.append({
                        'author_id': author_id,
                        'author': author_name,
                        'uid': paper['uid'],
                        'doi': paper['doi'],
                        'title': paper['title'],
                        'rank': rank,
                        'journal': paper['journal'],
                        'citation_count': paper['citation_count'],
                        'tag': tag,
                        'state': ''
                    })

            # 写入CSV
            append_rows_to_csv(rows, csv_file)

            # 更新统计
            total_papers += len(all_papers)
            total_rows += len(rows)
            write_count += 1

            # 释放内存
            del all_papers
            del rows
            gc.collect()

        # 打印完成信息
        if total_papers > 0:
            print(f"  ✅ {date_str}: 完成！共 {total_papers} 篇论文 → {total_rows} 行 (分 {write_count} 批写入)", flush=True)

            # 更新进度文件
            async with progress_lock:
                date_key = date_obj.strftime('%Y%m%d')
                progress['current_date'] = date_key
                progress['completed_dates'].append(date_key)
                save_progress(progress)

            return {
                'date_str': date_str,
                'paper_count': total_papers,
                'row_count': total_rows,
                'csv_file': csv_file,
                'write_count': write_count,
                'error': None
            }
        else:
            print(f"  ⚠️  {date_str}: 无数据（API限制或真实无数据）", flush=True)
            return {
                'date_str': date_str,
                'paper_count': 0,
                'row_count': 0,
                'error': 'NO_DATA'
            }


def get_all_dates_backward() -> List[str]:
    """获取从START_DATE往前到END_YEAR的所有日期（倒序），跳过每个月1号"""
    dates = []
    start_date_obj = datetime.strptime(START_DATE, '%Y%m%d')
    end_date_obj = datetime(END_YEAR, 12, 31)

    current = start_date_obj
    while current >= end_date_obj:
        # 跳过每个月的1号
        if current.day != 1:
            dates.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)

    return dates


def get_daily_csv_filename(date_str: str) -> str:
    """
    获取每日CSV文件名（按年月组织文件夹，按天命名文件）
    新结构：output/openalex/2026/04/2026-04-10.csv
    """
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    year = date_obj.year
    month = date_obj.month

    # 创建年/月文件夹结构
    output_dir = f'/home/apl064/apl/academic-scraper/output/openalex/{year}/{month:02d}'
    os.makedirs(output_dir, exist_ok=True)

    # 返回日期文件路径
    return os.path.join(output_dir, f'{date_str}.csv')


async def check_api_quota():
    """检查 API 配额状态"""
    print("🔍 检查 API 配额状态...")
    # print(f"   使用 API Key: {OPENALEX_API_KEY[:8]}...")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{OPENALEX_API_BASE}/authors",
                params={
                    'per-page': 1,
                    # 'api_key': OPENALEX_API_KEY
                },
                headers={
                    'User-Agent': 'AcademicScraper/2.0-Fast',
                    # 'Mailto': OPENALEX_EMAIL,
                    'Accept': 'application/json'
                }
            )

            if response.status_code == 429:
                print("\n❌❌❌ API 配额已耗尽！❌❌❌")
                print("=" * 60)
                try:
                    error_data = response.json()
                    print(f"错误信息: {error_data.get('message', 'Rate limit exceeded')}")
                    retry_after = error_data.get('retryAfter', 'N/A')
                    print(f"配额重置时间: {retry_after} 秒后")
                except:
                    pass
                print("\n💡 解决方案：")
                print("   1. 等待配额重置")
                print("   2. 检查 API Key 是否正确")
                print("=" * 60)
                return False

            elif response.status_code == 200:
                # 检查响应中的配额信息
                try:
                    meta = response.json().get('meta', {})
                    count = meta.get('count', 0)
                    print(f"✅ API 配额正常")
                    print(f"   返回结果数: {count}\n")
                except:
                    print("✅ API 配额正常\n")
                return True

            else:
                print(f"⚠️  API 返回异常状态码: {response.status_code}")
                print("   尝试继续抓取...\n")
                return True

    except Exception as e:
        print(f"⚠️  无法检查 API 配额: {e}")
        print("   尝试继续抓取...\n")
        return True


async def main_async():
    """异步主函数"""
    print("=" * 60)
    print("OpenAlex 论文自动获取工具 - 极速版 ⚡")
    print("=" * 60)
    print()

    # 创建输出目录
    os.makedirs('output/openalex', exist_ok=True)

    # 设置日志
    setup_logging()
    print("📝 日志已启用")

    # 检查 API 配额
    quota_ok = await check_api_quota()
    if not quota_ok:
        print("\n🛑 由于 API 配额耗尽，程序终止")
        print("   💾 进度已保存，请稍后重试")
        return

    # 加载进度
    progress = load_progress()

    # 加载进度
    progress = load_progress()

    if progress['current_date']:
        print(f"📂 检测到进度文件，从 {progress['current_date']} 继续")
        print(f"   已完成: {len(progress['completed_dates'])} 天")
        print()
    else:
        print("📂 开始新的获取任务")
        print()

    # 生成所有待获取日期（倒序）
    all_dates = get_all_dates_backward()

    # 过滤已完成的日期
    pending_dates = []
    for date_str in all_dates:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_key = date_obj.strftime('%Y%m%d')
        if date_key not in progress['completed_dates']:
            pending_dates.append(date_str)

    print(f"📅 待获取日期范围: {START_DATE} → {END_YEAR}（往前）")
    print(f"📊 共 {len(all_dates)} 天，待获取 {len(pending_dates)} 天")
    print(f"⚡ 并发数: {MAX_CONCURRENT_REQUESTS}")
    print()
    print("=" * 60)
    print()

    if not pending_dates:
        print("✅ 所有日期已获取完成！")
        return

    # 创建异步客户端（HTTP/2 + 连接池）
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        limits=httpx.Limits(
            max_connections=MAX_CONCURRENT_REQUESTS * 2,
            max_keepalive_connections=MAX_CONCURRENT_REQUESTS
        ),
        http2=True,
        headers={
            'User-Agent': 'AcademicScraper/2.0-Fast',
            # 'Mailto': OPENALEX_EMAIL,
            'Accept': 'application/json'
        }
    ) as client:
        # 创建信号量（控制并发）
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        # 创建进度锁
        progress_lock = asyncio.Lock()

        # 统计
        total_papers = 0
        total_rows = 0
        success_count = 0
        skip_count = len(all_dates) - len(pending_dates)

        start_time = time.time()

        # 创建两个进度条：天数和论文数
        with tqdm(total=len(pending_dates), desc="日期进度", unit="天", ncols=80) as day_pbar, \
             tqdm(total=0, desc="论文进度", unit="篇", ncols=80) as paper_pbar:

            # 创建所有任务
            tasks = [
                fetch_openalex_day(client, date_str, semaphore, day_pbar, paper_pbar, progress, progress_lock)
                for date_str in pending_dates
            ]

            # 并发执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for result in results:
                if isinstance(result, Exception):
                    print(f"❌ 任务异常: {result}")
                    continue

                # 检查是否是致命错误（API配额耗尽）
                if result.get('fatal') or result.get('error') == 'RATE_LIMIT_EXCEEDED':
                    print(f"\n{'='*60}")
                    print(f"🛑 API配额耗尽，程序停止")
                    print(f"💾 进度已保存到: {PROGRESS_FILE}")
                    print(f"{'='*60}\n")
                    return  # 退出主函数

                if result.get('error') and result.get('error') != 'NO_DATA':
                    print(f"❌ {result['date_str']}: {result['error']}")
                    continue

                # ✅ 使用新的字段名（不包含实际数据）
                paper_count = result.get('paper_count', 0)
                if paper_count > 0:
                    total_papers += paper_count
                    total_rows += result.get('row_count', 0)
                    success_count += 1

                    # 记录到日志
                    log_fetch_result(
                        result['date_str'],
                        paper_count,
                        result.get('row_count', 0),
                        result.get('csv_file', '')
                    )

        elapsed_time = time.time() - start_time

    # 最终保存进度
    save_progress(progress)

    # 记录完成状态到日志
    log_completion(total_papers, total_rows, success_count, skip_count, elapsed_time)

    # 总结
    print()
    print("=" * 60)
    print("🎉 获取完成！")
    print(f"📊 统计:")
    print(f"   - 成功: {success_count} 天")
    print(f"   - 跳过: {skip_count} 天（已完成）")
    print(f"   - 论文: {total_papers} 篇")
    print(f"   - 行数: {total_rows} 行")
    print(f"   - 耗时: {elapsed_time:.2f} 秒 ({elapsed_time/3600:.2f} 小时)")
    print(f"   - 速度: {total_papers/elapsed_time:.1f} 篇/秒")
    print(f"📁 数据文件: output/")
    print(f"📝 日志文件: {LOG_FILE}")
    print("=" * 60)


def main():
    """主函数"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        print("💾 进度已保存，下次运行将从中断处继续")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
