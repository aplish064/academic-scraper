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
from typing import List, Dict, Any
from datetime import datetime, timedelta
from tqdm.asyncio import tqdm


# OpenAlex API 基础URL
OPENALEX_API_BASE = "https://api.openalex.org"

# CSV字段
CSV_FIELDS = [
    'author', 'uid', 'doi', 'title', 'rank', 'journal',
    'citation_count', 'tag', 'state'
]

# 日志目录和文件
LOG_DIR = "/home/apl064/apl/academic-scraper/log"
LOG_FILE = os.path.join(LOG_DIR, "openalex_fetch_fast.log")
PROGRESS_FILE = os.path.join(LOG_DIR, "openalex_fetch_progress.json")

# 配置
START_DATE = "20260410"  # 从这个日期开始往前获取
END_YEAR = 2010          # 往前获取到这一年

# 并发配置
MAX_CONCURRENT_REQUESTS = 20  # 最大并发请求数
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
    """解析 OpenAlex 作品数据"""
    # 基本信息
    paper_id = work.get('id', '')
    title = work.get('title', '')
    if title:
        title = title.replace('\n', ' ')

    doi = work.get('doi', None)
    if doi is None:
        doi = ''

    # 作者信息
    authors = []
    authorships = work.get('authorships', [])

    for idx, auth in enumerate(authorships):
        author_info = auth.get('author', {})
        if author_info and author_info.get('display_name'):
            authors.append({
                'name': author_info['display_name'],
                'rank': idx + 1
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

    return {
        'uid': paper_id,
        'doi': doi,
        'title': title,
        'authors': authors,
        'journal': journal,
        'citation_count': citation_count,
        'categories': categories
    }


def expand_authors_to_rows(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """展开为作者行"""
    rows = []
    for paper in papers:
        authors = paper['authors']
        total_authors = len(authors)

        for author_info in authors:
            author_name = author_info['name']
            rank = author_info['rank']

            tag = '其他'
            if rank == 1:
                tag = '第一作者'
            elif rank == total_authors:
                tag = '最后作者'

            rows.append({
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
    return rows


def append_to_csv(rows: List[Dict[str, Any]], filepath: str):
    """追加数据到CSV文件（线程安全）"""
    file_exists = os.path.exists(filepath)

    with open(filepath, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
        if not file_exists:
            writer.writeheader()
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
    异步获取指定日期的所有论文

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
        # 打印当前正在获取的日期
        print(f"📅 正在获取: {date_str}", flush=True)

        all_papers = []
        cursor = '*'
        per_page = 200
        retry_count = 0

        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        year = date_obj.year
        month = date_obj.month
        day = date_obj.day

        while retry_count < MAX_RETRIES:
            try:
                params = {
                    'filter': f'from_publication_date:{date_str},to_publication_date:{date_str}',
                    'per-page': per_page,
                    'cursor': cursor
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

                # 解析论文
                for work in results:
                    paper = parse_openalex_work(work)
                    all_papers.append(paper)

                # 更新论文进度条
                paper_pbar.update(len(results))

                # 检查是否还有更多结果
                meta = data.get('meta', {})
                next_cursor = meta.get('next_cursor')
                if not next_cursor:
                    break

                cursor = next_cursor

                # 小延迟避免过载
                await asyncio.sleep(0.05)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit - 检查响应内容
                    try:
                        error_data = e.response.json()
                        if 'Rate limit exceeded' in error_data.get('error', ''):
                            # API配额耗尽，立即停止
                            print(f"\n❌ API配额耗尽！")
                            print(f"   {error_data.get('message', '')}")
                            print(f"   重置时间: {error_data.get('retryAfter', 'N/A')} 秒后")
                            print(f"   💾 进度已保存，请等待配额重置后继续")
                            return {
                                'date_str': date_str,
                                'year': year,
                                'month': month,
                                'papers': [],
                                'error': 'RATE_LIMIT_EXCEEDED',
                                'fatal': True  # 标记为致命错误
                            }
                    except:
                        pass

                    # 等待后重试
                    await asyncio.sleep(5)
                    retry_count += 1
                elif e.response.status_code >= 500:
                    await asyncio.sleep(3)
                    retry_count += 1
                else:
                    return {
                        'date_str': date_str,
                        'year': year,
                        'month': month,
                        'papers': [],
                        'error': str(e)
                    }

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                await asyncio.sleep(3)
                retry_count += 1

            except Exception as e:
                return {
                    'date_str': date_str,
                    'year': year,
                    'month': month,
                    'papers': [],
                    'error': str(e)
                }

        # 更新天数进度条
        day_pbar.update(1)

        # 写入CSV（按月组织）
        if all_papers:
            rows = expand_authors_to_rows(all_papers)
            csv_file = get_csv_filename(year, month)
            append_to_csv(rows, csv_file)

            # 打印完成信息
            print(f"  ✅ {date_str}: {len(all_papers)} 篇论文 → {len(rows)} 行", flush=True)

            # ✅ 保存统计信息（在函数返回前）
            paper_count = len(all_papers)
            row_count = len(rows)

            # ✅ all_papers 和 rows 是局部变量，函数结束后自动被GC回收
            # 关键：不要在返回值中包含这些大数据

            # 更新进度文件（线程安全）- 只保存有数据的日期
            async with progress_lock:
                date_key = date_obj.strftime('%Y%m%d')
                progress['current_date'] = date_key
                progress['completed_dates'].append(date_key)
                save_progress(progress)

            # ✅ 只返回统计信息，不返回实际数据
            # 这样主函数的 results 列表不会累积大量数据
            return {
                'date_str': date_str,
                'year': year,
                'month': month,
                'paper_count': paper_count,
                'row_count': row_count,
                'csv_file': csv_file,
                'error': None
            }
        else:
            # ❌ 无数据 - 不保存到进度文件，下次会重试
            print(f"  ⚠️  {date_str}: 无数据（API限制或真实无数据）", flush=True)

            # 不更新进度文件，让这个日期下次重新获取
            return {
                'date_str': date_str,
                'year': year,
                'month': month,
                'paper_count': 0,
                'row_count': 0,
                'error': 'NO_DATA'
            }


def get_all_dates_backward() -> List[str]:
    """获取从START_DATE往前到END_YEAR的所有日期（倒序）"""
    dates = []
    start_date_obj = datetime.strptime(START_DATE, '%Y%m%d')
    end_date_obj = datetime(END_YEAR, 12, 31)

    current = start_date_obj
    while current >= end_date_obj:
        dates.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)

    return dates


def get_csv_filename(year: int, month: int) -> str:
    """获取CSV文件名（按月份组织）"""
    output_dir = '/home/apl064/apl/academic-scraper/output'
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f'{year}_{month:02d}_openalex_papers.csv')


async def main_async():
    """异步主函数"""
    print("=" * 60)
    print("OpenAlex 论文自动获取工具 - 极速版 ⚡")
    print("=" * 60)
    print()

    # 创建输出目录
    os.makedirs('output', exist_ok=True)

    # 设置日志
    setup_logging()
    print("📝 日志已启用")

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
            'Mailto': 'mailto@example.com',
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
                    # 取消所有未完成的任务
                    for task in tasks:
                        if not task.done():
                            task.cancel()
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
